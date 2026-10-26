"""Deterministic scoring, bands, counts, gaps (§11.5–§11.6, §16.5)."""

from __future__ import annotations

import json

import pytest

from app.schemas.common import Band, Importance, Priority, Side
from app.schemas.scoring import BreakdownRow
from app.services import scoring as scoring_mod
from app.services.scoring import (
    BAND_CUTOFFS,
    band_for,
    build_breakdown,
    build_gaps,
    compute_score,
    score,
    weight_for,
)


def mention(name: str, display: str, importance: Importance, *, evidence: str | None = "x"
            ) -> scoring_mod.SkillMention:
    from app.schemas.common import ExtractionSource
    from app.schemas.skills import SkillMention

    return SkillMention(
        side=Side.JD,
        raw_label=display,
        canonical_name=name,
        display_name=display,
        category="other",
        importance=importance,
        evidence=evidence,
        confidence=0.9,
        extraction_source=ExtractionSource.SEED,
        verified=bool(evidence),
    )


def resume_mention(name: str, display: str, *, evidence: str | None = "used it daily"):
    from app.schemas.common import ExtractionSource
    from app.schemas.skills import SkillMention

    return SkillMention(
        side=Side.RESUME,
        raw_label=display,
        canonical_name=name,
        display_name=display,
        category="other",
        evidence=evidence,
        confidence=0.9,
        extraction_source=ExtractionSource.SEED,
        verified=bool(evidence),
    )


# ── the worked example from §11.5 ────────────────────────────────────────


def test_worked_example_matches_the_spec(resolver):
    jd = [
        mention("python", "Python", Importance.REQUIRED),
        mention("kubernetes", "Kubernetes", Importance.REQUIRED),
        mention("terraform", "Terraform", Importance.REQUIRED),
        mention("docker", "Docker", Importance.PREFERRED),
    ]
    resume = [
        resume_mention("python", "Python"),
        resume_mention("docker", "Docker"),
        resume_mention("aws", "AWS"),
    ]
    result, adjacency = score(jd, resume, resolver=resolver)

    assert result.value == 52
    assert result.band is Band.STRETCH
    assert result.coverage == pytest.approx(0.523, abs=0.001)
    assert adjacency == {"terraform": "AWS"}

    strengths = {row.canonical_name: row.strength for row in result.rows}
    assert strengths["python"] == 1.0
    assert strengths["kubernetes"] == 0.0
    assert strengths["terraform"] == 0.25
    assert strengths["docker"] == 1.0


def test_weights_match_the_spec():
    assert weight_for(Importance.REQUIRED) == 3.0
    assert weight_for(Importance.PREFERRED) == 2.0
    assert weight_for(Importance.MENTIONED) == 1.0
    assert weight_for(None) == 1.0


# ── bands ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (100, Band.STRONG),
        (80, Band.STRONG),
        (79, Band.COMPETITIVE),
        (65, Band.COMPETITIVE),
        (64, Band.STRETCH),
        (45, Band.STRETCH),
        (44, Band.FOUNDATIONAL_GAP),
        (0, Band.FOUNDATIONAL_GAP),
    ],
)
def test_band_cutoffs(value, band):
    assert band_for(value) is band


def test_band_cutoffs_are_ordered():
    minimums = [minimum for _, minimum in BAND_CUTOFFS]
    assert minimums == sorted(minimums, reverse=True)


# ── formula ──────────────────────────────────────────────────────────────


def test_compute_score_clamps_to_zero_and_hundred():
    rows = [
        BreakdownRow(
            canonical_name="a", display_name="A", importance=Importance.REQUIRED,
            weight=3.0, strength=1.0, contribution=3.0, status="matched",
        )
    ]
    value, coverage, band = compute_score(rows)
    assert value == 100
    assert coverage == 1.0
    assert band is Band.STRONG


def test_compute_score_with_no_rows_is_zero():
    value, coverage, _ = compute_score([])
    assert value == 0
    assert coverage == 0.0


def test_rounding_happens_once_at_the_end():
    """Half-up would give 63; the spec mandates Python's ``round()`` (§11.5)."""
    rows = [
        BreakdownRow(
            canonical_name=f"s{index}", display_name=f"S{index}",
            importance=Importance.MENTIONED, weight=1.0, strength=0.625,
            contribution=0.625, status="partial",
        )
        for index in range(8)
    ]
    value, coverage, _ = compute_score(rows)
    assert coverage == 0.625
    assert value == 62  # round(62.5) -> 62 under banker's rounding


def test_scoring_is_deterministic(resolver):
    jd = [mention("python", "Python", Importance.REQUIRED), mention("redis", "Redis", Importance.PREFERRED)]
    resume = [resume_mention("python", "Python")]

    first, _ = score(jd, resume, resolver=resolver)
    second, _ = score(jd, resume, resolver=resolver)
    assert first.model_dump_json() == second.model_dump_json()


def test_breakdown_order_is_stable(resolver):
    jd = [
        mention("redis", "Redis", Importance.PREFERRED),
        mention("python", "Python", Importance.REQUIRED),
        mention("go", "Go", Importance.REQUIRED),
    ]
    rows, _ = build_breakdown(jd, [], resolver=resolver)
    # Required (weight 3) first, then alphabetical within a weight.
    assert [r.canonical_name for r in rows] == ["go", "python", "redis"]


def test_name_only_match_scores_three_quarters(resolver):
    jd = [mention("python", "Python", Importance.REQUIRED)]
    resume = [resume_mention("python", "Python", evidence=None)]
    result, _ = score(jd, resume, resolver=resolver)
    assert result.rows[0].strength == 0.75
    assert result.value == 75
    assert result.counts.partial == 1


def test_adjacent_credit_is_configurable(resolver):
    jd = [mention("terraform", "Terraform", Importance.REQUIRED)]
    resume = [resume_mention("aws", "AWS")]
    result, _ = score(jd, resume, adjacent_credit=0.5, resolver=resolver)
    assert result.rows[0].strength == 0.5


def test_adjacency_is_one_hop_only(resolver):
    """A related-of-related skill must not earn credit (§11.4)."""
    jd = [mention("helm", "Helm", Importance.REQUIRED)]
    resume = [resume_mention("docker", "Docker")]
    result, _ = score(jd, resume, resolver=resolver)
    assert result.rows[0].strength == 0.0


def test_direct_match_beats_adjacency(resolver):
    jd = [mention("terraform", "Terraform", Importance.REQUIRED)]
    resume = [resume_mention("aws", "AWS"), resume_mention("terraform", "Terraform")]
    result, _ = score(jd, resume, resolver=resolver)
    assert result.rows[0].strength == 1.0


# ── counts ───────────────────────────────────────────────────────────────


def test_counts_partition_every_row(resolver):
    jd = [
        mention("python", "Python", Importance.REQUIRED),
        mention("go", "Go", Importance.REQUIRED),
        mention("terraform", "Terraform", Importance.REQUIRED),
    ]
    resume = [
        resume_mention("python", "Python"),
        resume_mention("aws", "AWS"),
    ]
    result, _ = score(jd, resume, resolver=resolver)
    counts = result.counts
    assert counts.matched + counts.partial + counts.missing == len(jd)
    assert (counts.matched, counts.partial, counts.missing) == (1, 1, 1)


# ── gaps ─────────────────────────────────────────────────────────────────


def test_required_and_absent_is_critical(resolver):
    jd = [mention("kubernetes", "Kubernetes", Importance.REQUIRED)]
    result, adjacency = score(jd, [], resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert gaps[0].priority is Priority.CRITICAL
    assert gaps[0].estimated_hours == 16
    assert gaps[0].sort_order == 1
    assert "not found on your resume" in gaps[0].gap_reason


def test_preferred_and_absent_is_high(resolver):
    jd = [mention("kafka", "Apache Kafka", Importance.PREFERRED)]
    result, adjacency = score(jd, [], resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert gaps[0].priority is Priority.HIGH


def test_adjacent_gap_mentions_the_source_skill(resolver):
    jd = [mention("terraform", "Terraform", Importance.REQUIRED)]
    resume = [resume_mention("aws", "AWS")]
    result, adjacency = score(jd, resume, resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert gaps[0].priority is Priority.HIGH
    assert "AWS" in gaps[0].gap_reason
    assert "partial credit" in gaps[0].gap_reason


def test_gap_sort_is_priority_then_weight(resolver):
    jd = [
        mention("kafka", "Apache Kafka", Importance.MENTIONED),
        mention("kubernetes", "Kubernetes", Importance.REQUIRED),
        mention("terraform", "Terraform", Importance.PREFERRED),
    ]
    result, adjacency = score(jd, [], resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert [gap.priority for gap in gaps] == [Priority.CRITICAL, Priority.HIGH, Priority.LOW]
    assert [gap.sort_order for gap in gaps] == [1, 2, 3]


def test_gap_sort_is_stable_across_runs(resolver):
    jd = [
        mention("redis", "Redis", Importance.PREFERRED),
        mention("kubernetes", "Kubernetes", Importance.REQUIRED),
        mention("go", "Go", Importance.REQUIRED),
    ]
    first, _ = score(jd, [], resolver=resolver)
    second, _ = score(list(reversed(jd)), [], resolver=resolver)
    gaps_a, _ = build_gaps(first.rows, resolver=resolver)
    gaps_b, _ = build_gaps(second.rows, resolver=resolver)
    assert [g.canonical_name for g in gaps_a] == [g.canonical_name for g in gaps_b]


def test_alias_list_is_attached_to_the_gap(resolver):
    jd = [mention("kubernetes", "Kubernetes", Importance.REQUIRED)]
    result, adjacency = score(jd, [], resolver=resolver)
    gaps, aliases = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert "k8s" in aliases["kubernetes"]
    assert "k8s" in gaps[0].gap_reason


def test_fully_matched_skill_is_not_a_gap(resolver):
    jd = [mention("python", "Python", Importance.REQUIRED)]
    resume = [resume_mention("python", "Python")]
    result, adjacency = score(jd, resume, resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert gaps == []


def test_impact_is_bounded(resolver):
    jd = [mention("kubernetes", "Kubernetes", Importance.REQUIRED)]
    result, adjacency = score(jd, [], resolver=resolver)
    gaps, _ = build_gaps(result.rows, adjacency=adjacency, resolver=resolver)
    assert 0.0 <= gaps[0].impact <= 1.0


def test_breakdown_stored_payload_is_json_serialisable(resolver):
    jd = [mention("python", "Python", Importance.REQUIRED)]
    result, _ = score(jd, [], resolver=resolver)
    payload = json.dumps(
        {
            "rows": [row.model_dump(mode="json") for row in result.rows],
            "counts": result.counts.model_dump(mode="json"),
            "coverage": result.coverage,
        },
        sort_keys=True,
    )
    assert json.loads(payload)["rows"][0]["canonical_name"] == "python"


def test_scoring_never_touches_the_network(monkeypatch):
    """The score must be a pure function (§16.5 "roof")."""

    def explode(*args, **kwargs):
        raise AssertionError("scoring must not call out")

    monkeypatch.setattr("httpx.AsyncClient.post", explode)
    rows = [
        BreakdownRow(
            canonical_name="python", display_name="Python", importance=Importance.REQUIRED,
            weight=3.0, strength=1.0, contribution=3.0, status="matched",
        )
    ]
    assert compute_score(rows)[0] == 100
