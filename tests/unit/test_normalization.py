"""Alias resolution, fuzzy guards, adjacency, merge policy (§11.3–§11.4, §16.5)."""

from __future__ import annotations

import pytest

from app.schemas.common import ExtractionSource, Importance, Proficiency, Side
from app.schemas.skills import SkillMention
from app.services.normalization import (
    canonical_key,
    merge_mentions,
    resolve_mention,
)


def test_canonical_key_is_case_and_whitespace_insensitive(resolver):
    assert canonical_key("  Python  ") == canonical_key("python")
    assert canonical_key("Node.js") == "node.js"


def test_canonical_key_preserves_punctuation():
    assert canonical_key("C++") == "c++"
    assert canonical_key("C#") != canonical_key("C++")
    assert canonical_key(".NET") == ".net"


def test_exact_canonical_match_is_seed_sourced(resolver):
    entry, source = resolver.resolve("Kubernetes")
    assert entry.canonical_name == "kubernetes"
    assert source is ExtractionSource.SEED


def test_alias_resolves_to_the_canonical_entry(resolver):
    entry, source = resolver.resolve("k8s")
    assert entry.canonical_name == "kubernetes"
    assert source is ExtractionSource.ALIAS


def test_postgres_alias_maps_to_postgresql(resolver):
    entry, _ = resolver.resolve("postgres")
    assert entry.canonical_name == "postgresql"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("React", "react"),
        ("reactjs", "react"),
        ("React Native", "react native"),
        ("Golang", "go"),
        ("amazon web services", "aws"),
    ],
)
def test_common_aliases(resolver, label, expected):
    entry, _ = resolver.resolve(label)
    assert entry.canonical_name == expected


def test_fuzzy_accepts_a_small_typo(resolver):
    entry, source = resolver.resolve("kubernetess")
    assert entry is not None
    assert entry.canonical_name == "kubernetes"
    assert source is ExtractionSource.FUZZY


@pytest.mark.parametrize("label", ["java", "c", "c++", "c#", "r", "go", "ml", "ai"])
def test_fuzzy_min_length_guard(resolver, label):
    """Labels under 5 chars never fuzzy-match (§11.4 guard 1)."""
    result = resolver.resolve(label)
    if result is not None:
        assert result[1] is not ExtractionSource.FUZZY


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("java", "javascript"),
        ("c", "c++"),
        ("c", "c#"),
        ("c++", "c#"),
        ("sql", "mysql"),
        ("react", "react native"),
    ],
)
def test_confusables_never_cross_match(resolver, left, right):
    """``java`` must never resolve to JavaScript, and so on (§16.5)."""
    entry, _ = resolver.resolve(left)
    if entry is not None:
        assert entry.canonical_name != canonical_key(right)


def test_javascript_does_not_resolve_to_java(resolver):
    entry, _ = resolver.resolve("javascript")
    assert entry.canonical_name == "javascript"


def test_unknown_label_is_accepted_not_dropped(resolver):
    mention = resolve_mention(resolver, side=Side.RESUME, raw_label="Fortran 77 Compiler Internals")
    assert mention is not None
    assert mention.extraction_source is ExtractionSource.LLM
    assert mention.verified is False
    assert mention.canonical_name == canonical_key("Fortran 77 Compiler Internals")


def test_blank_label_returns_none(resolver):
    assert resolve_mention(resolver, side=Side.JD, raw_label="   ") is None


def test_llm_hint_never_becomes_a_canonical_name(resolver):
    """The hint is a search key only (§11.4 "LLM hints")."""
    mention = resolve_mention(
        resolver,
        side=Side.JD,
        raw_label="K8s orchestration",
        canonical_hint="kubernetes",
        importance=Importance.REQUIRED,
    )
    assert mention.canonical_name == "kubernetes"


def test_adjacency_is_directional(resolver):
    """Kubernetes implies containers, not the other way round (§11.4)."""
    assert "docker" not in resolver.related_of("kubernetes")
    assert "kubernetes" in resolver.related_of("docker")


def test_merge_keeps_the_strongest_importance(resolver):
    mentions = [
        resolve_mention(resolver, side=Side.JD, raw_label="Python", importance=Importance.MENTIONED),
        resolve_mention(resolver, side=Side.JD, raw_label="python", importance=Importance.REQUIRED),
    ]
    merged = merge_mentions(mentions)
    assert len(merged) == 1
    assert merged[0].importance is Importance.REQUIRED


def test_merge_keeps_the_highest_proficiency(resolver):
    mentions = [
        resolve_mention(resolver, side=Side.RESUME, raw_label="Python", proficiency=Proficiency.BASIC),
        resolve_mention(
            resolver, side=Side.RESUME, raw_label="Python", proficiency=Proficiency.EXPERT
        ),
    ]
    merged = merge_mentions(mentions)
    assert merged[0].proficiency is Proficiency.EXPERT


def test_merge_preserves_first_seen_order(resolver):
    mentions = [
        resolve_mention(resolver, side=Side.JD, raw_label="Kubernetes"),
        resolve_mention(resolver, side=Side.JD, raw_label="Python"),
        resolve_mention(resolver, side=Side.JD, raw_label="k8s"),
    ]
    merged = merge_mentions(mentions)
    assert [m.canonical_name for m in merged] == ["kubernetes", "python"]


def test_merge_fills_missing_evidence(resolver):
    bare = SkillMention(
        side=Side.RESUME,
        raw_label="Python",
        canonical_name="python",
        display_name="Python",
        category="language",
        evidence=None,
        confidence=0.7,
        extraction_source=ExtractionSource.SEED,
        verified=False,
    )
    with_evidence = bare.model_copy(update={"evidence": "Python, FastAPI", "verified": True})
    merged = merge_mentions([bare, with_evidence])
    assert merged[0].evidence == "Python, FastAPI"
    assert merged[0].verified is True
