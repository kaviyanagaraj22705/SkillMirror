"""Parsing model output and building the single repair round (spec §12.3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import AppError, llm_refused, llm_schema_invalid, llm_truncated_output

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ParseFailure(Exception):
    """Internal signal: the text could not be turned into valid JSON of the right shape."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class ParseAttempt(Generic[T]):
    """Three-way outcome: a value, a repairable error, or a terminal catalogued error."""

    value: T | None = None
    error: str = ""
    terminal: AppError | None = None


def strip_fences(text: str) -> str:
    """Remove a markdown fence if the whole payload is wrapped in one."""
    match = _FENCE.search(text)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return text.strip()


def extract_json_object(text: str) -> str:
    """Find the first balanced JSON object, tolerating leading prose and trailing notes."""
    start = text.find("{")
    if start == -1:
        raise ParseFailure("no JSON object found in the response")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    # Unbalanced: the response was cut off mid-object.
    raise ParseFailure("unterminated JSON object (response was truncated)")


def _tidy(candidate: str) -> str:
    """Remove trailing commas, the most common near-miss."""
    return re.sub(r",(\s*[}\]])", r"\1", candidate)


def parse_and_validate(text: str, model_cls: type[T]) -> T:
    """Return a validated model, or raise the catalogued error that fits the failure."""
    if not (text or "").strip():
        raise llm_refused()

    candidate = strip_fences(text)
    try:
        candidate = extract_json_object(candidate)
    except ParseFailure as exc:
        if "truncated" in exc.message:
            raise llm_truncated_output() from exc
        raise llm_schema_invalid(exc.message) from exc

    try:
        raw: Any = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            raw = json.loads(_tidy(candidate))
        except json.JSONDecodeError as exc:
            raise llm_schema_invalid(str(exc)) from exc

    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise ParseFailure(exc.json()[:1500]) from exc


def attempt_parse(text: str, model_cls: type[T]) -> ParseAttempt[T]:
    """Non-raising variant used by the client's repair loop.

    A schema failure is *repairable*; truncation and refusal are terminal, so they
    come back in ``terminal`` and the client raises them without a repair call.
    """
    try:
        return ParseAttempt(value=parse_and_validate(text, model_cls))
    except ParseFailure as exc:
        return ParseAttempt(error=exc.message)
    except AppError as exc:
        if exc.code == "LLM_SCHEMA_INVALID":
            return ParseAttempt(error=str(exc.details.get("detail") if exc.details else exc.code))
        return ParseAttempt(terminal=exc)


def build_repair_messages(
    original_messages: list[dict[str, str]], bad_text: str, error: str
) -> list[dict[str, str]]:
    """Exactly one repair turn, appending the validation error (§12.3)."""
    return [
        *original_messages,
        {"role": "assistant", "content": bad_text[:8000]},
        {
            "role": "user",
            "content": (
                "That response did not satisfy the required JSON schema. "
                f"Validation error:\n{error[:1500]}\n\n"
                "Return ONLY a corrected JSON object that satisfies the schema. "
                "No prose, no markdown fences."
            ),
        },
    ]
