"""Idempotent dictionary loader with validation (spec §9.7)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.db.repositories import skills_repo
from app.schemas.skills import DictionaryEntry
from app.services.normalization import canonical_key

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent.parent.parent / "seeds" / "skills_seed.json"
SEED_VERSION_KEY = "seed_version"


class SeedError(RuntimeError):
    """A malformed dictionary must stop startup, not silently degrade matching (§9.7)."""


@dataclass(frozen=True)
class SeedResult:
    loaded: int
    skipped: bool
    version: str


def validate(entries: list[DictionaryEntry], version: str) -> None:
    seen_names: dict[str, str] = {}
    seen_aliases: dict[str, str] = {}
    problems: list[str] = []

    for entry in entries:
        key = canonical_key(entry.canonical_name)
        if not key:
            problems.append(f"{version}: an entry has an empty canonical_name")
            continue
        if key in seen_names:
            problems.append(f"duplicate canonical_name {entry.canonical_name!r}")
        seen_names[key] = entry.canonical_name

    for entry in entries:
        for alias in entry.aliases:
            key = canonical_key(alias)
            if not key:
                problems.append(f"{entry.canonical_name}: empty alias")
                continue
            owner = seen_aliases.get(key)
            if owner and owner != entry.canonical_name:
                problems.append(
                    f"alias {alias!r} is claimed by both {owner!r} and "
                    f"{entry.canonical_name!r}"
                )
            seen_aliases[key] = entry.canonical_name
            if key in seen_names and seen_names[key] != entry.canonical_name:
                problems.append(
                    f"alias {alias!r} on {entry.canonical_name!r} collides with the "
                    f"canonical name of {seen_names[key]!r}"
                )

    by_name = {canonical_key(e.canonical_name): e for e in entries}
    declared: set[frozenset[str]] = set()
    for entry in entries:
        for other in entry.confusables:
            pair = frozenset({canonical_key(entry.canonical_name), canonical_key(other)})
            declared.add(pair)

    for pair in declared:
        if len(pair) != 2:
            problems.append(f"confusable pair {sorted(pair)} is not symmetric or is self-referential")
            continue
        a, b = sorted(pair)
        for left, right in ((a, b), (b, a)):
            entry = by_name.get(left)
            if entry is None:
                problems.append(f"confusables mention unknown skill {left!r}")
                continue
            if right not in {canonical_key(c) for c in entry.confusables}:
                problems.append(
                    f"confusables must be declared on both sides: {left!r} does not list {right!r}"
                )

    if problems:
        detail = "\n  - ".join(problems[:20])
        raise SeedError(f"seeds/skills_seed.json is invalid:\n  - {detail}")


def read_seed(path: Path | None = None) -> tuple[list[DictionaryEntry], str]:
    seed_path = path or SEED_PATH
    try:
        document = json.loads(seed_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SeedError(f"Skill dictionary not found at {seed_path}") from exc
    except json.JSONDecodeError as exc:
        raise SeedError(f"Skill dictionary is not valid JSON: {exc}") from exc

    version = str(document.get("seed_version") or "")
    if not version:
        raise SeedError("Skill dictionary has no seed_version")

    entries = [DictionaryEntry(**item) for item in document.get("skills", [])]
    validate(entries, version)
    return entries, version


def load(
    conn,
    *,
    path: Path | None = None,
    force: bool = False,
) -> SeedResult:
    """Load the dictionary when ``seed_version`` changed, or when forced."""
    entries, version = read_seed(path)
    stored = skills_repo.get_meta(conn, SEED_VERSION_KEY)

    if stored == version and not force and skills_repo.count(conn) >= len(entries):
        return SeedResult(loaded=0, skipped=True, version=version)

    skills_repo.upsert_many(conn, entries)
    skills_repo.set_meta(conn, SEED_VERSION_KEY, version)
    logger.info("Seed dictionary %s loaded (%d entries)", version, len(entries))
    return SeedResult(loaded=len(entries), skipped=False, version=version)
