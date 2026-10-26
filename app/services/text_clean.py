"""Text normalization and section-aware truncation (spec §11.2).

Order matters: NFKC first, then line handling, then page furniture, then truncation.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.schemas.common import CleanResult

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_WS = re.compile(r"[ \t]+")
JD_SECTION = re.compile(
    r"(?i)^\s*(requirements|qualifications|required|skills|responsibilities|"
    r"what you.{0,3}ll do|who you are|must have|nice to have|about the role|"
    r"what we.{0,3}re looking for|you will|the role)\b"
)


def normalize(text: str) -> str:
    """NFKC + line-ending + control-character normalization."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = text.replace("\t", "    ")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _furniture_key(line: str) -> str:
    """Digits are folded before counting so ``Page 1 of 3`` also matches ``Page 2 of 3``.

    Headers and footers are the most common page furniture, and numbered ones are the
    most common of all — counting them verbatim would never catch them.
    """
    return re.sub(r"\d+", "#", line.strip())


def remove_page_furniture(text: str, pages: int | None) -> tuple[str, int]:
    """Drop lines repeated on >=60% of pages (headers/footers), when we know the page count."""
    if not pages or pages < 3:
        return text, 0
    lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 2]
    counts = Counter(_furniture_key(line) for line in lines)
    threshold = max(3, int(pages * 0.6))
    furniture = {key for key, count in counts.items() if count >= threshold}
    if not furniture:
        return text, 0
    kept = [line for line in text.split("\n") if _furniture_key(line) not in furniture]
    return "\n".join(kept), len(furniture)


# Section names that end a requirement block without starting another one. These are the
# headings that appear between the parts of a posting a reader cares about, and they are
# listed explicitly rather than inferred: a bare capitalized line is usually a bullet
# ("Kubernetes"), and treating it as a heading would cut the requirements apart.
OTHER_SECTION = re.compile(
    r"(?i)^\s*(benefits|perks|about us|about the company|about you|our offer|"
    r"what we offer|why join|compensation|salary|location|the team|our stack|"
    r"equal opportunity|how to apply)\b"
)


def _is_heading(stripped: str) -> bool:
    """A known section name, an explicit label ending in a colon — nothing looser."""
    if not stripped or len(stripped) >= 80:
        return False
    if JD_SECTION.match(stripped) or OTHER_SECTION.match(stripped):
        return True
    return stripped.endswith(":") and len(stripped.split()) <= 6


def _blocks(text: str) -> list[tuple[bool, str]]:
    """Split into (is_requirement_block, block_text) using heading detection."""
    lines = text.split("\n")
    blocks: list[tuple[bool, str]] = []
    current: list[str] = []
    in_requirements = False

    def flush() -> None:
        if current:
            blocks.append((in_requirements, "\n".join(current)))
            current.clear()

    for line in lines:
        stripped = line.strip()
        if _is_heading(stripped):
            flush()
            in_requirements = bool(JD_SECTION.match(stripped))
        current.append(line)
    flush()

    # Order: the opening intro first, then requirements, then responsibilities, then the rest.
    def rank(indexed: tuple[int, tuple[bool, str]]) -> int:
        index, (is_req, body) = indexed
        if index == 0:
            return -1
        if is_req:
            return 0
        if re.search(r"(?i)responsibilit|you will|day to day", body[:120]):
            return 2
        return 3

    return [block for _, block in sorted(enumerate(blocks), key=rank)]


def truncate_section_aware(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep the most job-relevant blocks first when a JD must be shortened.

    Block order is fixed by ``_blocks`` (intro → requirements → responsibilities → rest).
    An oversized block is trimmed to the remaining budget rather than skipped, but space
    is reserved for requirement blocks further down the list — otherwise one long
    "About us" paragraph could consume the entire budget on its own.
    """
    if len(text) <= max_chars:
        return text, False

    blocks = _blocks(text)
    kept: list[str] = []
    used = 0

    for position, (_, body) in enumerate(blocks):
        if used >= max_chars:
            break
        remaining = max_chars - used
        if len(body) + 1 <= remaining:
            kept.append(body)
            used += len(body) + 1
            continue

        # Reserve room for requirement blocks that still lie ahead of this one.
        reserved = sum(
            len(later) + 2
            for later_is_req, later in blocks[position + 1 :]
            if later_is_req
        )
        allowance = remaining - reserved if reserved < remaining - 80 else remaining
        if allowance <= 80:
            # Not enough left to say anything useful here; let the reserved blocks have it.
            continue
        cut = body[:allowance]
        head = cut.rsplit(" ", 1)[0] if " " in cut[-80:] else cut
        kept.append(head)
        used += len(head) + 2

    result = "\n\n".join(kept).strip()
    if not result:
        result = text[:max_chars]
    return result, True


def clean_text(
    raw: str,
    *,
    max_chars: int,
    kind: str = "resume",
    pages: int | None = None,
) -> CleanResult:
    """Full cleaning pipeline. ``kind`` selects plain vs section-aware truncation."""
    original_chars = len(raw or "")
    text = normalize(raw)
    text, removed = remove_page_furniture(text, pages)

    if kind == "jd":
        text, truncated = truncate_section_aware(text, max_chars)
    else:
        truncated = len(text) > max_chars
        if truncated:
            cut = text[:max_chars]
            text = cut.rsplit(" ", 1)[0] if " " in cut[-80:] else cut

    return CleanResult(
        text=text,
        original_chars=original_chars,
        final_chars=len(text),
        truncated=truncated,
        pages=pages,
        removed_page_furniture=removed,
    )


def sanitize_evidence(quote: str | None, limit: int = 200) -> str | None:
    """Evidence quotes are stored and shown; strip markup and cap length (§12.12).

    Delimiters are removed *before* markup: the generic ``<...>`` strip would otherwise
    reduce ``<<<RESUME_START:ab12>>>`` to ``>>`` and leave the nonce half-detached.
    """
    if not quote:
        return None
    text = re.sub(r"<<<[A-Z_]{1,40}(?::[0-9a-fA-F]{1,64})?>>>", " ", quote)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    text = normalize(text)
    text = re.sub(r"\{nonce\}", " ", text)
    text = _WS.sub(" ", text).strip()
    if not text:
        return None
    return text[:limit]
