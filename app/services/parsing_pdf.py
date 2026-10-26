"""PDF text extraction: PyMuPDF primary, pypdf → pdfplumber fallback, OCR last.

Layered so a document that defeats one parser still gets read by a stronger one:

1. **PyMuPDF (``fitz``)** — reliable text-layer extraction, tolerant of the
   broken fonts and odd encodings that make ``pypdf`` return garbage.
2. **pypdf, then pdfplumber** — the codebase's original parsers, kept as the
   fallback so machines without PyMuPDF still work unchanged.
3. **OCR (pytesseract + Tesseract)** — for scanned, image-only PDFs. Each page
   is rendered to an image with PyMuPDF and OCR'd in page order. If Tesseract
   is not installed the document fails with a clear, distinct error instead of
   the misleading "no text" one.

Every failure is a catalogued ``AppError``; raw library exceptions never leak
past this module (spec §10.3).
"""

from __future__ import annotations

import io
import logging

from app.errors import (
    AppError,
    pdf_encrypted,
    pdf_ocr_unavailable,
    pdf_parse_failed,
    pdf_scanned_no_text,
    pdf_too_many_pages,
)

logger = logging.getLogger(__name__)

MAX_PAGES = 40
MIN_TOTAL_CHARS = 200
MIN_CHARS_PER_PAGE = 50

# OCR is off by default so a missing Tesseract install fails loudly at the
# boundary rather than silently. ``settings`` overrides via OCR_ENABLE / OCR_DPI.
OCR_ENABLE = False
OCR_DPI = 300
OCR_LANG = "eng"


def _import_pymupdf():
    """PyMuPDF ships two package names; prefer the modern one, fall back to ``fitz``.

    Returns ``None`` when the package is absent rather than raising, so the
    caller can fall through to the next parser instead of failing the file.
    """
    try:
        import pymupdf as mupdf  # PyMuPDF >= 1.24
        return mupdf
    except ImportError:
        pass
    try:
        import fitz as mupdf  # older releases
        return mupdf
    except ImportError:
        return None


def _extract_pymupdf(data: bytes) -> tuple[str, int]:
    """Text-layer extraction with PyMuPDF; return ``(text, page_count)``."""
    mupdf = _import_pymupdf()
    if mupdf is None:
        raise RuntimeError("PyMuPDF not installed")  # generic: the chain skips it

    try:
        document = mupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - library-specific failure modes
        raise pdf_parse_failed(str(exc)[:120]) from exc

    try:
        pages = document.page_count
        if pages > MAX_PAGES:
            raise pdf_too_many_pages(MAX_PAGES)

        chunks: list[str] = []
        for page in document:
            try:
                chunks.append(page.get_text("text") or "")
            except Exception:  # noqa: BLE001 - one bad page should not lose the rest
                chunks.append("")
        return "\n\n".join(chunks), pages
    finally:
        document.close()


def _extract_pypdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise pdf_parse_failed(str(exc)[:120]) from exc

    if reader.is_encrypted:
        try:
            # Empty password opens the very common "owner password only" case.
            if reader.decrypt("") == 0:
                raise pdf_encrypted()
        except Exception as exc:  # noqa: BLE001 - library-specific failure modes
            if getattr(exc, "code", None) == "PDF_ENCRYPTED":
                raise
            raise pdf_encrypted() from exc

    pages = len(reader.pages)
    if pages > MAX_PAGES:
        raise pdf_too_many_pages(MAX_PAGES)

    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page should not lose the rest
            chunks.append("")
    return "\n\n".join(chunks), pages


def _extract_pdfplumber(data: bytes) -> tuple[str, int]:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            if pages > MAX_PAGES:
                raise pdf_too_many_pages(MAX_PAGES)
            chunks = [(page.extract_text() or "") for page in pdf.pages]
        return "\n\n".join(chunks), pages
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", None):
            raise
        raise pdf_parse_failed(str(exc)[:120]) from exc


def _pymupdf_available() -> bool:
    """True when either PyMuPDF import name resolves."""
    return _import_pymupdf() is not None


def _extract_ocr(data: bytes, *, dpi: int = OCR_DPI, lang: str = OCR_LANG) -> tuple[str, int]:
    """OCR an image-only PDF page by page with Tesseract.

    Rendering is done with PyMuPDF when available (bundled in pyproject);
    pypdfium2 (a renderer that ships with pdfplumber) is the fallback so a
    scanned file still gets read even on a machine that skipped PyMuPDF.
    """
    import pytesseract
    from PIL import Image

    pytesseract.get_tesseract_version()  # raises TesseractNotFoundError if missing

    if _pymupdf_available():
        mupdf = _import_pymupdf()

        document = mupdf.open(stream=data, filetype="pdf")
        try:
            pages = document.page_count
            if pages > MAX_PAGES:
                raise pdf_too_many_pages(MAX_PAGES)
            chunks: list[str] = []
            for page in document:
                pix = page.get_pixmap(dpi=dpi, colorspace=mupdf.csRGB, alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                chunks.append(pytesseract.image_to_string(image, lang=lang))
            return "\n\n".join(chunks), pages
        finally:
            document.close()

    # Rendering fallback without PyMuPDF: rasterize via pypdfium2 (ships as a
    # dependency of pdfplumber on this project), so a scanned file still gets
    # read even on a machine that skipped the optional PyMuPDF install.
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        pages = len(document)
        if pages > MAX_PAGES:
            raise pdf_too_many_pages(MAX_PAGES)
        chunks: list[str] = []
        for index in range(pages):
            page = document[index]
            bitmap = page.render(scale=dpi / 72).to_pil()
            chunks.append(pytesseract.image_to_string(bitmap, lang=lang))
        return "\n\n".join(chunks), pages
    finally:
        document.close()


def _ocr_available() -> bool:
    """True only when pytesseract *and* the Tesseract binary are installed."""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - import or exec missing
        return False
    return True


def _means_empty(text: str, pages: int) -> bool:
    non_blank = bool(text.strip())
    if not non_blank:
        return True
    chars_per_page = len(text) / pages if pages else 0
    return len(text.strip()) < MIN_TOTAL_CHARS or chars_per_page < MIN_CHARS_PER_PAGE


def extract_pdf_text(
    data: bytes,
    *,
    enable_ocr: bool = OCR_ENABLE,
    ocr_dpi: int = OCR_DPI,
    ocr_lang: str = OCR_LANG,
) -> tuple[str, dict]:
    """Return ``(text, parse_meta)`` or raise a catalogued ``AppError``.

    Parser chain, in order of preference:
    PyMuPDF → pypdf → pdfplumber → OCR. The first that yields enough text wins.
    ``parse_meta`` records which parser produced the text and, for OCR, whether
    every page had a text layer (diagnostics, not user-facing copy).
    """
    if not data.startswith(b"%PDF-"):
        raise pdf_parse_failed("missing PDF header")

    meta: dict = {"parser_used": "pypdf", "fallback_used": False,
                  "ocr_pages": 0, "scanned_pages": 0}
    pages = 0
    text = ""
    owner: str | None = None  # parser that produced ``text``; set at assignment time

    # Layered text-layer attempt: strongest parser first. Each fallback only
    # runs when the previous one produced too little text to be confident of it,
    # and never overrides a *longer* extract (a broken font can make the
    # strongest parser return garbage while a weaker one reads cleanly).
    for parser_name, extractor in (
        ("pymupdf", _extract_pymupdf),
        ("pypdf", _extract_pypdf),
        ("pdfplumber", _extract_pdfplumber),
    ):
        try:
            alt_text, alt_pages = extractor(data)
        except AppError:
            raise  # encrypted / too many pages carry intent; don't paper over them
        except Exception as exc:  # noqa: BLE001 - best-effort fallback
            logger.warning("%s extraction failed (%s); trying next parser", parser_name, exc)
            continue
        if len(alt_text.strip()) > len(text.strip()):
            text, pages, owner = alt_text, alt_pages, parser_name
        if not _means_empty(text, pages):
            break

    if not _means_empty(text, pages):
        meta.update(
            parser_used=owner or "pypdf",
            fallback_used=owner not in (None, "pymupdf"),
            pages=pages,
            chars_per_page=round(len(text) / pages, 1) if pages else 0,
        )
        return text, meta

    if text.strip():
        # Real (if thin) text survived the chain. Don't mislabel a short PDF
        # "scanned" — the ingestion layer's MIN_TEXT_CHARS check handles shortness.
        meta.update(
            parser_used=owner or "pypdf",
            fallback_used=owner not in (None, "pymupdf"),
            pages=pages,
            chars_per_page=round(len(text) / pages, 1) if pages else 0,
        )
        return text, meta

    # 3) OCR the scanned/image-only document. Only reached when every text-layer
    #    parser produced no usable text at all.
    if enable_ocr:
        if not _ocr_available():
            raise pdf_ocr_unavailable()
        try:
            text, pages = _extract_ocr(data, dpi=ocr_dpi, lang=ocr_lang)
        except Exception as exc:  # noqa: BLE001 - library-specific failure modes
            logger.warning("OCR extraction failed: %s", exc)
            raise pdf_parse_failed("OCR failed to read the scanned pages.") from exc
        if text.strip():
            meta.update(
                parser_used="ocr",
                fallback_used=True,
                pages=pages,
                chars_per_page=round(len(text) / pages, 1) if pages else 0,
                ocr_pages=pages,
                scanned_pages=pages,
            )
            return text, meta
        raise pdf_parse_failed("The scan was too faint or damaged to OCR.")

    raise pdf_scanned_no_text()