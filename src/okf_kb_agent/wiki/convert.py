"""Deterministic converter from OKF v0.2 provenance to OKF v0.3 entries."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .frontmatter import FrontmatterError, parse_frontmatter
from .model import WEB_SOURCE_KINDS, is_special, write_concept

__all__ = [
    "ConversionReport",
    "convert_source_string",
    "convert_wiki_v03",
    "verify_entry_lossless",
]

_ATTR_TOKEN_RE = re.compile(r"^([a-z_][a-z0-9_]*)=(.+)$")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_ARXIV_MODERN_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
_ARXIV_OLD_RE = re.compile(r"^[a-z-]+(?:\.[a-z-]+)?/\d{7}(?:v\d+)?$", re.IGNORECASE)
_SANITIZE_RE = re.compile(r"[^a-z0-9._-]+")

_ORDERED_STD_ATTRS: tuple[str, ...] = (
    "issued",
    "retrieved",
    "via",
    "genre",
)


@dataclass
class ConversionReport:
    """Summary of an ``okf convert-v03`` run."""

    root: str
    written: bool
    files_scanned: int = 0
    files_changed: int = 0
    converted_sources: int = 0
    verified_injected: int = 0
    verified_fallback: int = 0
    raw_preserved: list[dict[str, str]] = field(default_factory=list)
    id_collisions: list[dict[str, str]] = field(default_factory=list)
    lossless_errors: list[dict[str, str]] = field(default_factory=list)
    changed_files: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "written": self.written,
            "files_scanned": self.files_scanned,
            "files_changed": self.files_changed,
            "converted_sources": self.converted_sources,
            "verified_injected": self.verified_injected,
            "verified_fallback": self.verified_fallback,
            "raw_preserved": list(self.raw_preserved),
            "id_collisions": list(self.id_collisions),
            "lossless_errors": list(self.lossless_errors),
            "changed_files": list(self.changed_files),
        }

    def format_text(self) -> str:
        mode = "APPLIED" if self.written else "DRY-RUN"
        lines = [
            f"okf convert-v03 ({mode}): {self.root}",
            f"  files scanned: {self.files_scanned}, changed: {self.files_changed}",
            f"  sources converted: {self.converted_sources}",
            f"  verified injected: {self.verified_injected}, "
            f"x-okfkb-verified-at fallback: {self.verified_fallback}",
            f"  raw preserved: {len(self.raw_preserved)}, "
            f"id collisions resolved: {len(self.id_collisions)}, "
            f"lossless errors: {len(self.lossless_errors)}",
        ]
        for item in self.changed_files:
            lines.append(
                f"  - {item['rel']}: sources={item['sources_converted']}, "
                f"verified_action={item['verified_action']}"
            )
        for item in self.raw_preserved:
            lines.append(f"  RAW_PRESERVED: {item['rel']}: {item['raw']!r}")
        for item in self.id_collisions:
            lines.append(
                f"  ID_COLLISION: {item['rel']}: "
                f"{item['original_id']} -> {item['resolved_id']}"
            )
        for item in self.lossless_errors:
            lines.append(
                f"  LOSSLESS_ERROR: {item['rel']}: {item['raw']!r} ({item['reason']})"
            )
        return "\n".join(lines)


def _sanitize_id(text: str) -> str:
    return _SANITIZE_RE.sub("-", text.lower()).strip("-")


def _parse_legacy_grammar(raw: str) -> tuple[str, str, list[tuple[str, str]]] | None:
    """Parse ``<kind>:<identifier> [k=v ...]`` per the alignment design doc."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    tokens = raw.strip().split()
    trailing: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    idx = len(tokens)
    while idx > 1:
        match = _ATTR_TOKEN_RE.match(tokens[idx - 1])
        if not match:
            break
        key, val = match.group(1), match.group(2)
        if key in seen_keys:
            return None
        seen_keys.add(key)
        trailing.append((key, val))
        idx -= 1
    trailing.reverse()

    head = " ".join(tokens[:idx])
    if ":" not in head:
        return None
    kind, identifier = head.split(":", 1)
    kind = kind.strip()
    identifier = identifier.strip()
    if not kind or not identifier:
        return None
    return kind, identifier, trailing


def _resolve_source_resource(kind: str, identifier: str) -> str:
    if kind == "preprint":
        bare = re.sub(r"^arxiv:", "", identifier, flags=re.IGNORECASE)
        if _ARXIV_MODERN_RE.match(bare) or _ARXIV_OLD_RE.match(bare):
            return f"https://arxiv.org/abs/{bare}"
        return identifier
    if kind == "paper":
        bare = re.sub(r"^doi:", "", identifier, flags=re.IGNORECASE)
        if _DOI_RE.match(bare):
            return f"https://doi.org/{bare}"
        return identifier
    if kind.startswith("patent-"):
        if identifier.startswith(("http://", "https://")):
            return identifier
        return f"https://patents.google.com/patent/{identifier}"
    if kind in WEB_SOURCE_KINDS or kind in ("ops-record", "local-file"):
        return identifier
    return identifier


def _derive_source_id(
    kind: str,
    identifier: str,
    attrs: Mapping[str, str],
) -> str:
    if kind == "preprint":
        bare = re.sub(r"^arxiv:", "", identifier, flags=re.IGNORECASE)
        slug = _sanitize_id(bare)
        return f"arxiv-{slug}" if slug else "arxiv-source"
    if kind == "paper":
        bare = re.sub(r"^doi:", "", identifier, flags=re.IGNORECASE)
        slug = _sanitize_id(bare)
        if _DOI_RE.match(bare):
            return f"doi-{slug}" if slug else "doi-source"
        return f"paper-{slug}" if slug else "paper-source"
    if kind.startswith("patent-"):
        slug = _sanitize_id(identifier)
        return f"{_sanitize_id(kind)}-{slug}" if slug else _sanitize_id(kind)
    if kind in WEB_SOURCE_KINDS:
        parts = urlsplit(identifier)
        host_path = f"{parts.netloc}{parts.path}".rstrip("/") if parts.netloc else identifier
        slug = _sanitize_id(host_path)
        if parts.query or len(slug) > 48:
            digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8]
            prefix = slug[:48].rstrip("-")
            slug = f"{prefix}-{digest}" if prefix else digest
        return f"web-{slug}" if slug else "web-source"
    if kind in ("ops-record", "local-file"):
        snap = attrs.get("snapshot", "").strip()
        if snap:
            return _sanitize_id(snap) or f"{kind}-source"
        slug = _sanitize_id(identifier)
        return f"{kind}-{slug}" if slug else f"{kind}-source"
    kind_slug = _sanitize_id(kind) or "source"
    id_slug = _sanitize_id(identifier)
    return f"{kind_slug}-{id_slug}" if id_slug else kind_slug


def convert_source_string(
    raw: str,
    *,
    used_ids: set[str] | None = None,
    title: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Convert one legacy ``sources`` string into a v0.3 entry dict.

    Returns ``(entry_dict, is_raw_fallback)``.
    """
    parsed = _parse_legacy_grammar(raw)
    if parsed is None:
        return {"resource": raw, "x-okfkb-raw": raw}, True

    kind, identifier, attr_pairs = parsed
    attrs_dict = dict(attr_pairs)
    resource = _resolve_source_resource(kind, identifier)
    base_id = _derive_source_id(kind, identifier, attrs_dict)

    resolved_id = base_id
    if used_ids is not None:
        suffix = 2
        while resolved_id in used_ids:
            resolved_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(resolved_id)

    entry: dict[str, Any] = {
        "id": resolved_id,
        "resource": resource,
    }
    if title is not None:
        entry["title"] = title
    entry["x-okfkb-kind"] = kind

    for key in _ORDERED_STD_ATTRS:
        if key in attrs_dict:
            entry[f"x-okfkb-{key}"] = attrs_dict[key]
    for key, val in attr_pairs:
        if key not in _ORDERED_STD_ATTRS:
            entry[f"x-okfkb-{key}"] = val

    return entry, False


def verify_entry_lossless(raw: str, entry: Mapping[str, Any]) -> bool:
    """Verify every attribute and identifier of ``raw`` is recoverable from ``entry``."""
    if "x-okfkb-raw" in entry:
        return entry.get("x-okfkb-raw") == raw and entry.get("resource") == raw

    parsed = _parse_legacy_grammar(raw)
    if parsed is None:
        return False
    kind, identifier, attr_pairs = parsed
    if entry.get("x-okfkb-kind") != kind:
        return False
    if entry.get("resource") != _resolve_source_resource(kind, identifier):
        return False
    for key, val in attr_pairs:
        if entry.get(f"x-okfkb-{key}") != val:
            return False
    return True


def _convert_sources_stage(
    meta: dict[str, Any],
    rel: str,
    report: ConversionReport,
) -> bool:
    """Stage 1: convert legacy string items in ``meta['sources']``."""
    raw_sources = meta.get("sources")
    if not isinstance(raw_sources, list):
        return False

    used_ids: set[str] = set()
    for item in raw_sources:
        if isinstance(item, Mapping):
            existing_id = item.get("id")
            if isinstance(existing_id, str) and existing_id:
                used_ids.add(existing_id)

    new_sources: list[Any] = []
    changed = False
    for item in raw_sources:
        if isinstance(item, Mapping):
            new_sources.append(dict(item))
            continue
        if not isinstance(item, str):
            new_sources.append(item)
            continue

        pre_ids = set(used_ids)
        entry, is_raw = convert_source_string(item, used_ids=used_ids)
        new_sources.append(entry)
        changed = True
        report.converted_sources += 1

        if is_raw:
            report.raw_preserved.append({"rel": rel, "raw": item})
        else:
            parsed = _parse_legacy_grammar(item)
            if parsed is not None:
                expected_base = _derive_source_id(
                    parsed[0], parsed[1], dict(parsed[2])
                )
                if entry["id"] != expected_base and expected_base in pre_ids:
                    report.id_collisions.append({
                        "rel": rel,
                        "original_id": expected_base,
                        "resolved_id": entry["id"],
                    })

        if not verify_entry_lossless(item, entry):
            report.lossless_errors.append({
                "rel": rel,
                "raw": item,
                "reason": "attribute_or_resource_mismatch",
            })

    if changed:
        meta["sources"] = new_sources
    return changed


def _convert_verified_stage(
    meta: dict[str, Any],
    rel: str,
    verified_map: Mapping[str, list[dict[str, Any]]] | None,
    report: ConversionReport,
) -> str:
    """Stage 2: migrate ``verified_at`` via ``verified_map`` or fallback key."""
    if verified_map is not None and rel in verified_map:
        events = [dict(ev) for ev in verified_map[rel]]
        changed = False
        if meta.get("verified") != events:
            meta["verified"] = events
            changed = True
        if "verified_at" in meta:
            meta.pop("verified_at")
            changed = True
        if "x-okfkb-verified-at" in meta:
            meta.pop("x-okfkb-verified-at")
            changed = True
        if changed:
            report.verified_injected += 1
            return "injected_verified"
        return "none"

    if "verified_at" in meta:
        legacy_val = meta.pop("verified_at")
        if "x-okfkb-verified-at" not in meta:
            meta["x-okfkb-verified-at"] = legacy_val
        report.verified_fallback += 1
        return "fallback_x_okfkb_verified_at"

    return "none"


def _load_verified_map(
    path: str | Path | None,
) -> dict[str, list[dict[str, Any]]] | None:
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("--verified-map JSON must be an object mapping rel -> events")
    out: dict[str, list[dict[str, Any]]] = {}
    for rel, events in data.items():
        if not isinstance(rel, str) or not isinstance(events, list):
            raise ValueError(f"invalid verified-map entry for {rel!r}")
        out[rel] = [dict(ev) for ev in events]
    return out


def convert_wiki_v03(
    root: str | Path,
    *,
    write: bool = False,
    verified_map_path: str | Path | None = None,
) -> ConversionReport:
    """Convert a wiki directory from v0.2 provenance to v0.3 entries."""
    wiki = Path(root)
    verified_map = _load_verified_map(verified_map_path)
    report = ConversionReport(root=str(wiki), written=write)

    if not wiki.exists():
        raise FileNotFoundError(f"wiki root does not exist: {wiki}")

    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki).as_posix()
        if is_special(rel):
            continue
        report.files_scanned += 1
        raw_text = path.read_text(encoding="utf-8")
        try:
            meta, body = parse_frontmatter(raw_text)
        except FrontmatterError:
            continue

        new_meta = copy.deepcopy(meta)
        before_sources = report.converted_sources
        sources_changed = _convert_sources_stage(new_meta, rel, report)
        verified_action = _convert_verified_stage(
            new_meta, rel, verified_map, report
        )
        file_changed = sources_changed or (verified_action != "none")
        if not file_changed:
            continue

        report.files_changed += 1
        report.changed_files.append({
            "rel": rel,
            "sources_converted": report.converted_sources - before_sources,
            "verified_action": verified_action,
        })
        if write:
            write_concept(path, new_meta, body)

    return report
