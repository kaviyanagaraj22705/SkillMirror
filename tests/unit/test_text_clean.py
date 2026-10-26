"""Text cleaning: NFKC, control chars, page furniture, truncation (§11.2, §16.2)."""

from __future__ import annotations

from app.services.text_clean import (
    clean_text,
    normalize,
    remove_page_furniture,
    sanitize_evidence,
)


def clean(raw: str, **kwargs):
    return clean_text(raw, max_chars=kwargs.pop("max_chars", 10_000), **kwargs)


def test_nfkc_folds_compatibility_characters():
    cleaned = clean("Ｃ＋＋ and ﬁnance and Ⅳ")
    assert "C++" in cleaned.text
    assert "finance" in cleaned.text
    assert "IV" in cleaned.text


def test_control_characters_are_removed():
    cleaned = clean("Python\x00 and\x07 FastAPI\x1b")
    assert "\x00" not in cleaned.text
    assert "\x07" not in cleaned.text
    assert "\x1b" not in cleaned.text
    assert "Python" in cleaned.text


def test_punctuation_in_skill_labels_survives():
    """``C#``, ``.NET``, ``Node.js``, ``C++`` must not lose their punctuation (§11.3)."""
    text = "Languages: C++, C#, .NET, Node.js, ASP.NET Core"
    cleaned = clean(text)
    for label in ("C++", "C#", ".NET", "Node.js", "ASP.NET Core"):
        assert label in cleaned.text


def test_internal_whitespace_is_collapsed():
    cleaned = clean("Line one\n\n\n\nLine   two\t\tthree")
    assert "Line one" in cleaned.text
    assert "Line two three" in cleaned.text
    assert "\n\n\n" not in cleaned.text


def test_resume_truncation_is_reported_and_respects_the_cap():
    cleaned = clean("word " * 5000, max_chars=1000)
    assert cleaned.truncated is True
    assert len(cleaned.text) <= 1000
    assert cleaned.original_chars > cleaned.final_chars


def test_no_truncation_when_under_the_cap():
    cleaned = clean("short resume text", max_chars=1000)
    assert cleaned.truncated is False
    assert cleaned.original_chars == cleaned.final_chars


def test_jd_truncation_respects_the_cap_and_keeps_the_requirements_block():
    jd = (
        "About the role\n"
        + "Build payment systems. " * 60
        + "\n\nRequirements\nKubernetes, Terraform, PostgreSQL\n"
    )
    cleaned = clean(jd, max_chars=1200, kind="jd")
    assert cleaned.truncated is True
    assert len(cleaned.text) <= 1200
    # The intro is kept first by design (§11.2 step 7); the requirements block follows.
    assert "About the role" in cleaned.text
    assert "Kubernetes" in cleaned.text


def test_jd_truncation_prefers_requirements_over_late_filler():
    """Once the budget is tight, the requirements block ranks ahead of the tail."""
    jd = (
        "About the role\nShort intro.\n\n"
        "Benefits\n" + "Free lunch and a gym. " * 80 + "\n\n"
        "Requirements\nKubernetes\n"
    )
    cleaned = clean(jd, max_chars=400, kind="jd")
    assert "Kubernetes" in cleaned.text


def test_page_furniture_is_dropped():
    pages = [
        "Alex Rivera\nPage 1 of 3\nPython, FastAPI",
        "Alex Rivera\nPage 2 of 3\nPostgreSQL, Redis",
        "Alex Rivera\nPage 3 of 3\nDocker, AWS",
    ]
    text, removed = remove_page_furniture("\n".join(pages), pages=3)
    assert "Page 1 of 3" not in text
    assert "Page 2 of 3" not in text
    # Two distinct furniture lines ("Alex Rivera", "Page # of 3"), numbered pages folded.
    assert removed == 2
    assert "PostgreSQL" in text
    assert text.count("Alex Rivera") == 0


def test_page_furniture_is_left_alone_for_short_documents():
    text, removed = remove_page_furniture("a\nb\nc", pages=2)
    assert removed == 0
    assert text == "a\nb\nc"


def test_sanitize_evidence_strips_markup_and_caps_length():
    evidence = sanitize_evidence("<script>alert(1)</script>" + "x" * 400)
    assert "<" not in evidence
    assert len(evidence) <= 200


def test_sanitize_evidence_rejects_delimiter_tokens():
    assert sanitize_evidence("<<<SKILLMIRROR:0123456789abcdef>>>") is None


def test_sanitize_evidence_handles_none_and_blank():
    assert sanitize_evidence(None) is None
    assert sanitize_evidence("   ") is None


def test_normalize_is_idempotent():
    once = normalize("  C++\r\n\r\n\r\n  Resume\ttext  ")
    assert normalize(once) == once
