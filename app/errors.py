"""Error hierarchy and the catalogued error codes (spec §10.3, Appendix A).

Every failure that can reach a client is an ``AppError`` with a stable ``code``.
Raw library exceptions never propagate past their service boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppError(Exception):
    code: str
    http_status: int
    message: str
    details: dict | None = field(default=None)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ValidationAppError(AppError):
    pass


class NotFoundError(AppError):
    pass


class ConflictError(AppError):
    pass


class UpstreamError(AppError):
    pass


class ConfigError(AppError):
    pass


# ── Constructors grouped by area, so call sites read as intent ─────────────


def validation_error(message: str, details: dict | None = None) -> ValidationAppError:
    return ValidationAppError("VALIDATION_ERROR", 422, message, details)


def field_validation(field_name: str, message: str) -> ValidationAppError:
    return ValidationAppError(
        "VALIDATION_ERROR",
        422,
        "Some fields need attention.",
        {"fields": [{"field": field_name, "message": message}]},
    )


def analysis_not_found(analysis_id: str) -> NotFoundError:
    return NotFoundError(
        "ANALYSIS_NOT_FOUND", 404, "That analysis no longer exists.", {"analysis_id": analysis_id}
    )


def job_not_found(job_id: str) -> NotFoundError:
    return NotFoundError(
        "JOB_NOT_FOUND", 404, "That run could not be found.", {"job_id": job_id}
    )


def job_not_cancellable() -> ConflictError:
    return ConflictError("JOB_NOT_CANCELLABLE", 409, "That run has already finished.")


def job_already_running(analysis_id: str) -> ConflictError:
    return ConflictError(
        "JOB_ALREADY_RUNNING",
        409,
        "An analysis is already running for this resume.",
        {"analysis_id": analysis_id},
    )


def duplicate_analysis(analysis_id: str) -> ConflictError:
    return ConflictError(
        "DUPLICATE_ANALYSIS",
        409,
        "This exact analysis was just started.",
        {"analysis_id": analysis_id},
    )


def no_gaps_to_roadmap() -> ConflictError:
    return ConflictError(
        "NO_GAPS_TO_ROADMAP",
        409,
        "There are no gaps to build a roadmap from.",
    )


def upload_too_large(max_mb: int, received_mb: float | None = None) -> AppError:
    return AppError(
        "UPLOAD_TOO_LARGE",
        413,
        f"That file is larger than {max_mb} MB. Try a smaller PDF or paste the text.",
        {"max_mb": max_mb, "received_mb": received_mb},
    )


def upload_type_not_allowed(allowed: list[str]) -> AppError:
    return AppError(
        "UPLOAD_TYPE_NOT_ALLOWED",
        415,
        "Only PDF and DOCX files are supported.",
        {"allowed": allowed},
    )


def upload_magic_mismatch() -> AppError:
    return AppError(
        "UPLOAD_MAGIC_MISMATCH",
        415,
        "That file's contents don't match its extension.",
    )


def pdf_parse_failed(reason: str = "") -> AppError:
    return AppError(
        "PDF_PARSE_FAILED",
        400,
        "We couldn't read that PDF. Try pasting the text instead.",
        {"reason": reason} if reason else None,
    )


def pdf_scanned_no_text(reason: str = "") -> AppError:
    return AppError(
        "PDF_SCANNED_NO_TEXT",
        400,
        "That PDF has no selectable text — it may be a scan. Paste the text instead.",
        {"reason": reason} if reason else None,
    )


def pdf_ocr_unavailable() -> AppError:
    return AppError(
        "PDF_OCR_UNAVAILABLE",
        400,
        "That PDF is a scanned image, and OCR isn't installed. Install Tesseract "
        "OCR or paste the text instead.",
    )


def pdf_encrypted() -> AppError:
    return AppError(
        "PDF_ENCRYPTED",
        400,
        "That PDF is password-protected. Remove the password and try again.",
    )


def pdf_too_many_pages(limit: int) -> AppError:
    return AppError(
        "PDF_TOO_MANY_PAGES", 400, f"That PDF has more than {limit} pages.", {"limit": limit}
    )


def docx_parse_failed(reason: str = "") -> AppError:
    return AppError(
        "DOCX_PARSE_FAILED",
        400,
        "We couldn't read that Word file. Try saving it again or pasting the text.",
        {"reason": reason} if reason else None,
    )


def resume_too_short(min_chars: int) -> ValidationAppError:
    return field_validation(
        "resume", f"Add at least {min_chars} characters so there's enough to analyze."
    )


def resume_text_empty() -> AppError:
    return AppError("RESUME_TEXT_EMPTY", 400, "No text could be read from that document.")


def jd_no_skills() -> AppError:
    return AppError(
        "JD_NO_SKILLS",
        400,
        "We couldn't find any skills in that job description. Try pasting the full posting.",
    )


def rate_limited(limit: int, retry_after: int) -> AppError:
    return AppError(
        "RATE_LIMITED",
        429,
        f"You've run {limit} analyses in the last hour. Try again shortly.",
        {"limit": limit, "retry_after_s": retry_after},
    )


def llm_disabled() -> UpstreamError:
    return UpstreamError(
        "LLM_DISABLED",
        503,
        "Skill matching used keyword search only. Add an OpenRouter key for a full analysis.",
    )


def llm_auth_failed() -> UpstreamError:
    return UpstreamError(
        "LLM_AUTH_FAILED", 502, "OpenRouter rejected the API key. Check your .env file."
    )


def llm_model_unavailable(model: str) -> UpstreamError:
    return UpstreamError(
        "LLM_MODEL_UNAVAILABLE",
        502,
        "The configured model isn't available. Check the model name.",
        {"model": model},
    )


def llm_timeout(stage: str) -> UpstreamError:
    return UpstreamError(
        "LLM_TIMEOUT", 502, "The model took too long to respond. Try again.", {"stage": stage}
    )


def llm_rate_limited() -> UpstreamError:
    return UpstreamError(
        "LLM_RATE_LIMITED", 502, "The model provider is rate-limiting. Try again in a minute."
    )


def llm_schema_invalid(detail: str = "") -> UpstreamError:
    return UpstreamError(
        "LLM_SCHEMA_INVALID",
        502,
        "The model's response didn't match the expected format.",
        {"detail": detail[:300]} if detail else None,
    )


def llm_truncated_output() -> UpstreamError:
    return UpstreamError(
        "LLM_TRUNCATED_OUTPUT", 502, "The model's response was cut off. Try again."
    )


def llm_refused() -> UpstreamError:
    return UpstreamError("LLM_REFUSED", 502, "The model declined to process this document.")


def llm_upstream_error(detail: str = "") -> UpstreamError:
    return UpstreamError(
        "LLM_UPSTREAM_ERROR",
        502,
        "The model provider returned an error.",
        {"detail": detail[:300]} if detail else None,
    )


def job_interrupted() -> ConflictError:
    return ConflictError(
        "JOB_INTERRUPTED", 409, "The previous run was interrupted. Start it again."
    )


def db_schema_too_new(found: int, supported: int) -> ConfigError:
    return ConfigError(
        "DB_SCHEMA_TOO_NEW",
        500,
        "The database was created by a newer version of SkillMirror.",
        {"found_version": found, "supported_version": supported},
    )


def internal_error() -> AppError:
    return AppError(
        "INTERNAL_ERROR", 500, "Something went wrong on our side. The details are below."
    )
