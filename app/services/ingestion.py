"""Upload and paste intake: validation order, magic bytes, in-memory parsing (spec §15.3).

The uploaded bytes are parsed in memory and then dropped. Nothing is written to disk
unless ``KEEP_UPLOADS=true``, and even then the path is a server-chosen UUID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.errors import (
    resume_text_empty,
    resume_too_short,
    upload_magic_mismatch,
    upload_too_large,
    upload_type_not_allowed,
)
from app.schemas.common import ResumeSource
from app.services.parsing_docx import extract_docx_text
from app.services.parsing_pdf import extract_pdf_text
from app.services.text_clean import clean_text

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = ("pdf", "docx")
LEGACY_EXTENSIONS = ("doc", "rtf", "pages", "odt")
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


@dataclass(frozen=True)
class IngestResult:
    text: str
    source: ResumeSource
    filename: str | None
    meta: dict = field(default_factory=dict)
    truncated: bool = False
    original_chars: int = 0


def sniff_kind(data: bytes) -> str | None:
    """Return ``"pdf"``, ``"docx"``, or ``None`` from the leading bytes, not the extension."""
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        # A DOCX is a zip that must contain the document part (§15.3 step 5).
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return None
        return "docx" if "word/document.xml" in names else None
    return None


def extension_of(filename: str | None) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def check_extension(filename: str | None) -> str:
    """Steps 2–3 of §15.3. Returns the lower-case extension."""
    ext = extension_of(filename)
    if ext in LEGACY_EXTENSIONS:
        raise upload_type_not_allowed(list(ALLOWED_EXTENSIONS))
    if ext not in ALLOWED_EXTENSIONS:
        raise upload_type_not_allowed(list(ALLOWED_EXTENSIONS))
    return ext


def check_size(size_bytes: int, settings: Settings) -> None:
    """The streaming reader enforces this too; this catches an honest oversize early."""
    cap = settings.MAX_UPLOAD_MB * 1024 * 1024
    if size_bytes > cap:
        raise upload_too_large(settings.MAX_UPLOAD_MB, round(size_bytes / 1024 / 1024, 1))


def ingest_paste(raw_text: str, settings: Settings) -> IngestResult:
    cleaned = clean_text(raw_text, max_chars=settings.MAX_RESUME_CHARS, kind="resume")
    if not cleaned.text.strip():
        raise resume_text_empty()
    if cleaned.final_chars < settings.MIN_TEXT_CHARS:
        raise resume_too_short(settings.MIN_TEXT_CHARS)
    return IngestResult(
        text=cleaned.text,
        source=ResumeSource.PASTE,
        filename=None,
        meta={"parser_used": "paste", "original_chars": cleaned.original_chars},
        truncated=cleaned.truncated,
        original_chars=cleaned.original_chars,
    )


def ingest_file(data: bytes, filename: str | None, settings: Settings) -> IngestResult:
    """Steps 2–8 of §15.3, in order, short-circuiting on the first failure."""
    ext = check_extension(filename)
    check_size(len(data), settings)

    kind = sniff_kind(data)
    if kind is None:
        raise upload_magic_mismatch()
    if kind != ext:
        # A .pdf that is really a ZIP (or vice versa) is a spoof, not a mistake.
        raise upload_magic_mismatch()

    if kind == "pdf":
        raw, parse_meta = extract_pdf_text(
            data,
            enable_ocr=settings.OCR_ENABLE,
            ocr_dpi=settings.OCR_DPI,
            ocr_lang=settings.OCR_LANG,
        )
        source = ResumeSource.PDF
    else:
        raw, parse_meta = extract_docx_text(data)
        source = ResumeSource.DOCX

    pages = parse_meta.get("pages")
    cleaned = clean_text(
        raw, max_chars=settings.MAX_RESUME_CHARS, kind="resume", pages=pages
    )
    if not cleaned.text.strip():
        raise resume_text_empty()
    if cleaned.final_chars < settings.MIN_TEXT_CHARS:
        raise resume_too_short(settings.MIN_TEXT_CHARS)

    parse_meta["original_chars"] = cleaned.original_chars
    parse_meta["removed_page_furniture"] = cleaned.removed_page_furniture
    return IngestResult(
        text=cleaned.text,
        source=source,
        filename=(Path(filename).name[:120] if filename else None),
        meta=parse_meta,
        truncated=cleaned.truncated,
        original_chars=cleaned.original_chars,
    )


def clean_jd(raw_text: str, settings: Settings) -> tuple[str, bool, int]:
    """Return ``(text, truncated, chars)`` for the job description."""
    cleaned = clean_text(raw_text, max_chars=settings.MAX_JD_CHARS, kind="jd")
    return cleaned.text, cleaned.truncated, cleaned.final_chars


def store_upload(data: bytes, kind: str, settings: Settings) -> str | None:
    """Only when ``KEEP_UPLOADS`` is on; the name is a UUID, never the client's (§15.3)."""
    if not settings.KEEP_UPLOADS:
        return None
    import uuid

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = (settings.upload_dir / f"{uuid.uuid4().hex}.{kind}").resolve()
    if not target.is_relative_to(settings.upload_dir.resolve()):
        logger.error("Refused to write an upload outside UPLOAD_DIR")
        return None
    target.write_bytes(data)
    return target.name


def remove_upload(filename: str | None, settings: Settings) -> None:
    if not filename or not settings.KEEP_UPLOADS:
        return
    target = (settings.upload_dir / filename).resolve()
    if target.is_relative_to(settings.upload_dir.resolve()) and target.is_file():
        target.unlink(missing_ok=True)
