"""Upload intake through the real multipart endpoint (§15.3, §16.2).

Sends actual PDF bytes (normal, scanned, encrypted) over the ASGI transport
and asserts the resulting envelope. These hit the same validation stack the
browser uses — including the streaming size cap and magic-byte sniffing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DATA_PDF = Path(__file__).resolve().parents[2] / "data" / "_t.pdf"


def _upload(file_bytes: bytes, filename: str, resume_text: str = "") -> tuple[dict, dict]:
    """Return ``(form_fields, files)`` couples for the multipart request."""
    form = {"resume_text": resume_text, "jd_text": "Requirements: Python Kubernetes"}
    files = {"file": (filename, file_bytes, "application/pdf")}
    return form, files


@pytest.fixture
def scan_pdf() -> bytes:
    return (FIXTURES / "scanned_resume.pdf").read_bytes()


@pytest.fixture
def encrypted_pdf() -> bytes:
    return (FIXTURES / "encrypted_resume.pdf").read_bytes()


async def test_scanned_pdf_upload_returns_scanned_error(client, scan_pdf):
    """A textless PDF must come back as the generic scanned error with OCR off."""
    form, files = _upload(scan_pdf, "scan.pdf")
    response = await client.post("/api/analyses/form", data=form, files=files)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "PDF_SCANNED_NO_TEXT"


async def test_encrypted_pdf_upload_is_distinct(client, encrypted_pdf):
    """Password-protected PDFs get their own error, not a generic parse failure."""
    form, files = _upload(encrypted_pdf, "pass.pdf")
    response = await client.post("/api/analyses/form", data=form, files=files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PDF_ENCRYPTED"


async def test_non_pdf_extension_is_rejected_by_magic(client):
    """A .pdf that is really a zip must be refused as a spoof, not parsed."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("something.txt", "not a docx")
    form, files = _upload(buffer.getvalue(), "fake.pdf")
    response = await client.post("/api/analyses/form", data=form, files=files)
    assert response.status_code == 415  # upload_magic_mismatch


async def test_ocr_enabled_upload_tells_user_to_install_tesseract(
    client, scan_pdf
):
    """With OCR opted in but Tesseract not installed, the message must name the
    missing dependency rather than falling back to the vague 'no text' copy."""
    from app.services.parsing_pdf import _ocr_available

    if _ocr_available():
        pytest.skip("Tesseract installed; this targets the missing-binary path")

    # Rebuild the app with OCR enabled *and* override the route's settings
    # dependency (it reads get_settings(), not app.state.settings).
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings
    from app.dependencies import get_settings
    from app.main import create_app

    ocr_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_PATH=Path("data/_ocr_upload_test.db"),
        UPLOAD_DIR=Path("data/_ocr_uploads"),
        OPENROUTER_API_KEY=None,
        LLM_ENABLED=False,
        OCR_ENABLE=True,
    )
    application = create_app(ocr_settings)
    application.dependency_overrides[get_settings] = lambda: ocr_settings
    transport = ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            form, files = _upload(scan_pdf, "scan.pdf")
            response = await ac.post("/api/analyses/form", data=form, files=files)
            assert response.status_code == 400
            body = response.json()
            assert body["error"]["code"] == "PDF_OCR_UNAVAILABLE"
            assert "OCR" in body["error"]["message"]
    for leftover in Path("data").glob("_ocr_*"):
        if leftover.is_file():
            leftover.unlink()