"""PDF parsing: parser chain, OCR gating, and error taxonomy (§10.4, §16.2).

Real fixtures (generated at test setup and committed under tests/fixtures):
- ``data/_t.pdf``                 — a normal single-page text PDF
- ``tests/fixtures/multipage_text.pdf`` — a 3-page text PDF
- ``tests/fixtures/scanned_resume.pdf`` — an image-only PDF (simulated scan,
  no text layer; OCR turns it back into text when Tesseract is present)
- ``tests/fixtures/encrypted_resume.pdf`` — AES-encrypted
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import AppError
from app.services import parsing_pdf as pp

DATA_PDF = Path(__file__).resolve().parents[2] / "data" / "_t.pdf"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(relative: str) -> bytes:
    return (FIXTURES / relative).read_bytes()


def test_normal_pdf_extracts_with_pymupdf():
    data = _read_helper(DATA_PDF)
    text, meta = pp.extract_pdf_text(data)
    assert text.strip()
    assert meta["parser_used"] == "pymupdf"


def _read_helper(path: Path) -> bytes:
    return path.read_bytes()


def test_multipage_pdf_extracts_all_pages_in_order():
    data = _read("multipage_text.pdf")
    text, meta = pp.extract_pdf_text(data)
    assert meta["pages"] == 3
    assert "Page One" in text
    assert "Page Two" in text
    assert "Page Three" in text
    # Page order preserved: page 2's paragraph comes between pages 1 and 3.
    assert text.index("Page One") < text.index("Page Two") < text.index("Page Three")


def test_scanned_pdf_without_ocr_raises_scanned_no_text():
    data = _read("scanned_resume.pdf")
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(data)
    assert excinfo.value.code == "PDF_SCANNED_NO_TEXT"


def test_scanned_pdf_with_ocr_enabled_but_missing_tesseract_is_distinct():
    """OCR is *requested* but Tesseract isn't on the machine: the error must be
    honest about the missing dependency, not a vague 'no text'."""
    data = _read("scanned_resume.pdf")
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(data, enable_ocr=True)
    assert excinfo.value.code == "PDF_OCR_UNAVAILABLE"


def test_ocr_falls_back_cleanly_when_tesseract_is_absent():
    """Same as above but via the settings plumbing used by ingestion."""
    data = _read("scanned_resume.pdf")
    if pp._ocr_available():
        pytest.skip("Tesseract is installed; this test targets the missing-binary path")
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(data, enable_ocr=True, ocr_dpi=200)
    assert excinfo.value.code == "PDF_OCR_UNAVAILABLE"


def test_encrypted_pdf_raises_encrypted():
    data = _read("encrypted_resume.pdf")
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(data)
    assert excinfo.value.code == "PDF_ENCRYPTED"


def test_non_pdf_bytes_raise_parse_failed():
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(b"this is not a pdf at all")
    assert excinfo.value.code == "PDF_PARSE_FAILED"


def test_truncated_pdf_raises_parse_failed_or_scanned():
    # A file starting with the PDF magic but ending abruptly: the parsers must
    # not raise an unhandled exception out of the module.
    data = _read("multipage_text.pdf")
    truncated = data[: len(data) // 2]
    assert truncated.startswith(b"%PDF-")
    try:
        pp.extract_pdf_text(truncated)
    except AppError as exc:
        assert exc.code in {"PDF_PARSE_FAILED", "PDF_SCANNED_NO_TEXT"}
    else:
        # Some parsers tolerate truncation and return partial text; that's fine.
        pass


def test_thin_text_is_returned_not_mislabelled_scanned():
    """A genuine PDF with very little text is returned; the ingestion layer
    (not the parser) is responsible for the too-short verdict (§15.3)."""
    data = _read_helper(DATA_PDF)
    text, meta = pp.extract_pdf_text(data)
    assert text.strip()
    assert len(text.strip()) < pp.MIN_TOTAL_CHARS  # the fixture is deliberately thin
    assert meta["parser_used"] == "pymupdf"


def test_thin_text_is_not_sent_to_ocr():
    """OCR must only run when there is genuinely no text at all — a short but
    readable PDF should keep its text even with OCR enabled (otherwise a faint
    scan reader could clobber real content)."""
    from unittest.mock import patch

    data = _read_helper(DATA_PDF)

    # Force pymupdf to yield nothing so pypdf wins the text-layer chain; OCR
    # must still not run because real text survived.
    with patch.object(pp, "_extract_pymupdf", return_value=("", 1)):
        with patch.object(pp, "_extract_ocr", side_effect=AssertionError("OCR must not run")):
            text, meta = pp.extract_pdf_text(data, enable_ocr=True)
    assert text.strip()
    assert meta["parser_used"] == "pypdf"


def test_full_multipage_ingestion_keeps_all_pages_and_strips_furniture(settings):
    """A realistic multi-page resume flows through ingest_file whole: page
    numbers repeated per page are treated as furniture and dropped, while the
    content of every page survives (§11.2, §15.3)."""
    from app.services.ingestion import ingest_file

    data = (FIXTURES / "full_multipage_resume.pdf").read_bytes()
    result = ingest_file(data, "resume.pdf", settings)
    assert result.source.value == "pdf"
    assert result.meta["pages"] == 3
    assert result.meta["parser_used"] == "pymupdf"
    assert result.meta["removed_page_furniture"] >= 1
    # Content from every page is present.
    for token in ("ALEX MORGAN", "Experience", "Skills", "Education"):
        assert token in result.text
    # Numbered page footers were dropped.
    assert "Page 1 of 3" not in result.text
    assert result.text.count("Page 2 of 3") == 0


def test_max_pages_enforced():
    # A 41-page PDF must be refused up front, before any slow fallback chain.
    py = __import__("pypdf")
    writer = py.PdfWriter()
    for _ in range(pp.MAX_PAGES + 1):
        writer.add_blank_page(width=200, height=200)
    import io

    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    with pytest.raises(AppError) as excinfo:
        pp.extract_pdf_text(data)
    assert excinfo.value.code == "PDF_TOO_MANY_PAGES"


def test_pymupdf_render_ocr_path_returns_text(monkeypatch):
    """When Tesseract *is* available, a scanned PDF is OCR'd end-to-end.

    Guarded so the test never depends on Tesseract being installed locally:
    it monkeypatches pytesseract's call to return canned text, and patches
    ``_ocr_available`` so the gate passes without a real binary.
    """
    data = _read("scanned_resume.pdf")

    if pp._ocr_available():
        # Real Tesseract present: OCR the actual page.
        text, meta = pp.extract_pdf_text(data, enable_ocr=True)
        assert text.strip()
        assert meta["parser_used"] == "ocr"
        assert meta["pages"] == 1
        return

    # No Tesseract binary: simulate it with a fake OCR function.
    import pytesseract

    calls = {"n": 0}

    def fake_image_to_string(image, lang=None):
        calls["n"] += 1
        return "ALEX MORGAN Backend Engineer Python Django PostgreSQL Docker AWS"

    monkeypatch.setattr(pytesseract, "image_to_string", fake_image_to_string)
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "fake")
    monkeypatch.setattr(pp, "_ocr_available", lambda: True)

    text, meta = pp.extract_pdf_text(data, enable_ocr=True)
    assert text.strip()
    assert calls["n"] == 1  # one page OCR'd once
    assert meta["parser_used"] == "ocr"
    assert meta["ocr_pages"] == 1
    assert meta["scanned_pages"] == 1