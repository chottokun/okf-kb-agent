"""Deterministic provenance stamping helpers (OKF v0.3 U9)."""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, parse_frontmatter
from .model import write_concept

__all__ = [
    "StampReport",
    "stamp_generated",
    "stamp_verified",
]


@dataclass
class StampReport:
    """Summary of a ``stamp-generated`` or ``stamp-verified`` run."""

    command: str
    root: str
    by: str
    at: str
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "root": self.root,
            "by": self.by,
            "at": self.at,
            "changed": list(self.changed),
            "unchanged": list(self.unchanged),
        }

    def format_text(self) -> str:
        lines = [
            f"{self.command}: root={self.root} by={self.by} at={self.at} "
            f"changed={len(self.changed)} unchanged={len(self.unchanged)}"
        ]
        for rel in self.changed:
            lines.append(f"  changed: {rel}")
        for rel in self.unchanged:
            lines.append(f"  unchanged: {rel}")
        return "\n".join(lines)


def _resolve_at(at: str | None) -> str:
    if at is None:
        return datetime.now(timezone.utc).date().isoformat()
    value = at.strip()
    if not value:
        raise ValueError("--at must not be empty")
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        pass
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError as exc:
        raise ValueError(f"invalid ISO date/timestamp for --at: {at!r}") from exc


def _resolve_by(by: str | None) -> str:
    if not isinstance(by, str) or not by.strip():
        raise ValueError("--by <actor> is required")
    return by.strip()


def _load_and_validate_targets(
    wiki_dir: str | Path,
    note_rels: Sequence[str],
) -> tuple[Path, list[tuple[str, Path, dict[str, Any], str]]]:
    wiki = Path(wiki_dir).resolve()
    if not wiki.exists() or not wiki.is_dir():
        raise FileNotFoundError(f"wiki root directory not found: {wiki_dir}")
    if not note_rels:
        raise ValueError("at least one note relative path is required")

    loaded: list[tuple[str, Path, dict[str, Any], str]] = []
    for raw_rel in note_rels:
        rel_path = Path(raw_rel)
        if rel_path.is_absolute():
            raise ValueError(f"note path must be relative to wiki root: {raw_rel}")
        target = (wiki / rel_path).resolve()
        try:
            rel = target.relative_to(wiki).as_posix()
        except ValueError as exc:
            raise ValueError(f"note path escapes wiki root: {raw_rel}") from exc
        if not target.is_file():
            raise FileNotFoundError(f"note not found: {raw_rel}")
        raw_text = target.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw_text)
        loaded.append((rel, target, meta, body))
    return wiki, loaded


def stamp_generated(
    wiki_dir: str | Path,
    note_rels: Sequence[str],
    *,
    by: str | None,
    at: str | None = None,
) -> StampReport:
    """Set ``generated: {by, at}`` on each named note, preserving other content."""
    actor = _resolve_by(by)
    stamp_at = _resolve_at(at)
    wiki, targets = _load_and_validate_targets(wiki_dir, note_rels)
    report = StampReport(
        command="stamp-generated",
        root=str(wiki),
        by=actor,
        at=stamp_at,
    )
    event = {"by": actor, "at": stamp_at}
    for rel, target, meta, body in targets:
        existing = meta.get("generated")
        if isinstance(existing, Mapping) and dict(existing) == event:
            report.unchanged.append(rel)
            continue
        new_meta = copy.deepcopy(meta)
        new_meta["generated"] = dict(event)
        write_concept(target, new_meta, body)
        report.changed.append(rel)
    return report


def stamp_verified(
    wiki_dir: str | Path,
    note_rels: Sequence[str],
    *,
    by: str | None,
    at: str | None = None,
) -> StampReport:
    """Append ``{by, at}`` to ``verified`` on each named note (idempotent)."""
    actor = _resolve_by(by)
    stamp_at = _resolve_at(at)
    wiki, targets = _load_and_validate_targets(wiki_dir, note_rels)
    report = StampReport(
        command="stamp-verified",
        root=str(wiki),
        by=actor,
        at=stamp_at,
    )
    event = {"by": actor, "at": stamp_at}
    for rel, target, meta, body in targets:
        existing_raw = meta.get("verified")
        events: list[dict[str, Any]] = []
        if isinstance(existing_raw, Mapping):
            events.append(dict(existing_raw))
        elif isinstance(existing_raw, list):
            for item in existing_raw:
                if isinstance(item, Mapping):
                    events.append(dict(item))
        if any(ev.get("by") == actor and ev.get("at") == stamp_at for ev in events):
            report.unchanged.append(rel)
            continue
        events.append(dict(event))
        new_meta = copy.deepcopy(meta)
        new_meta["verified"] = events
        write_concept(target, new_meta, body)
        report.changed.append(rel)
    return report
