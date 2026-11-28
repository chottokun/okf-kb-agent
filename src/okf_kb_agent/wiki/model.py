"""OKF concept nodes: frontmatter, Markdown body and relative links."""
from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .._common import _atomic_write
from .frontmatter import FrontmatterError, dump_document, parse_frontmatter

__all__ = [
    "BASIS_VALUES",
    "EXPORT_FORMAT_VERSIONS",
    "EXPORT_SCOPES",
    "GENRE_VALUES",
    "KNOWN_SOURCE_KINDS",
    "NEWS_SOURCE_KINDS",
    "OKF_FORMAT_VERSION",
    "SCOPE_WEIGHTS",
    "SOURCE_ATTR_KEYS",
    "SUPPORTED_OKF_VERSIONS",
    "ProvenanceEvent",
    "SourceEntry",
    "SourceRecord",
    "TRANSPARENT_HEADINGS",
    "WEB_SOURCE_KINDS",
    "Concept",
    "Link",
    "Section",
    "extract_links",
    "extract_sections",
    "find_wikilinks",
    "is_special",
    "is_transparent_heading",
    "iter_concepts",
    "load_concept",
    "parse_source_entry",
    "relevance",
    "resolve_source_genre",
    "scope_from_heading",
    "scope_of",
    "tokenize",
    "validate_meta",
    "write_concept",
]

OKF_FORMAT_VERSION = "0.2"
SUPPORTED_OKF_VERSIONS: tuple[str, ...] = ("0.2", "0.3")

SCOPE_WEIGHTS: dict[str, float] = {
    "taxonomy": 1.0,
    "workflow": 1.2,
    "synergistic": 1.5,
    "gotchas": 2.0,
}

BASIS_VALUES: tuple[str, ...] = ("external", "model", "mixed", "ops-record")

KNOWN_SOURCE_KINDS: tuple[str, ...] = (
    "patent-biblio",
    "patent-claims",
    "patent-legal",
    "patent-family",
    "paper",
    "preprint",
    "datasheet",
    "product-page",
    "press-release",
    "standard",
    "news",
    "web",
    "manual",
    "ops-record",
    "local-file",
)

WEB_SOURCE_KINDS: tuple[str, ...] = (
    "datasheet",
    "product-page",
    "press-release",
    "standard",
    "news",
    "web",
    "manual",
)

NEWS_SOURCE_KINDS: tuple[str, ...] = (
    "press-release",
    "news",
)

GENRE_VALUES: tuple[str, ...] = ("paper", "patent", "web", "other")

EXPORT_FORMAT_VERSIONS: tuple[int, ...] = (1, 2)
EXPORT_SCOPES: tuple[str, ...] = ("all", "concepts", "patents")

SOURCE_ATTR_KEYS: tuple[str, ...] = (
    "issued",
    "retrieved",
    "via",
    "snapshot",
    "genre",
)

TRANSPARENT_HEADINGS: tuple[str, ...] = (
    "一般知識（未検証）",
    "general knowledge (unverified)",
    "出典に基づく整理",
    "based on sources",
)

_ISO_DATE_STRICT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_transparent_heading(heading: str) -> bool:
    """Return True when ``heading`` is an epistemic modifier heading."""
    cleaned = heading.strip().casefold()
    return cleaned in TRANSPARENT_HEADINGS


@dataclass(frozen=True)
class SourceEntry:
    kind: str
    id: str
    attrs: dict[str, str]
    raw: str


@dataclass(frozen=True)
class SourceRecord:
    """Structured OKF v0.3 ``sources`` entry preserving all keys verbatim."""

    resource: str
    id: str | None = None
    title: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SourceRecord:
        """Build a :class:`SourceRecord` from a frontmatter mapping."""
        if not isinstance(data, Mapping):
            raise ValueError("source entry mapping must be a mapping")
        raw = dict(data)
        resource = raw.get("resource")
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError(
                "structured source entry missing required 'resource' string")
        entry_id = raw.get("id")
        if entry_id is not None and not isinstance(entry_id, str):
            raise ValueError("source entry 'id' must be a string")
        title = raw.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("source entry 'title' must be a string")
        known = {"resource", "id", "title"}
        extensions = {k: v for k, v in raw.items() if k not in known}
        return cls(
            resource=resource,
            id=entry_id,
            title=title,
            extensions=extensions,
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a dict preserving all keys of this entry verbatim."""
        if self.raw:
            return dict(self.raw)
        out: dict[str, Any] = {}
        if self.id is not None:
            out["id"] = self.id
        out["resource"] = self.resource
        if self.title is not None:
            out["title"] = self.title
        out.update(self.extensions)
        return out


@dataclass(frozen=True)
class ProvenanceEvent:
    """OKF v0.3 ``generated`` or ``verified`` event (``{by, at}``)."""

    by: str
    at: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ProvenanceEvent:
        """Build a :class:`ProvenanceEvent` from a ``{by, at}`` mapping."""
        if not isinstance(data, Mapping):
            raise ValueError("provenance event must be a mapping")
        by = data.get("by")
        at = data.get("at")
        if not isinstance(by, str) or not by.strip():
            raise ValueError("provenance event missing required 'by' string")
        if not isinstance(at, str) or not at.strip():
            raise ValueError("provenance event missing required 'at' string")
        extra = {k: v for k, v in data.items() if k not in ("by", "at")}
        return cls(by=by, at=at, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation preserving any extra keys."""
        out: dict[str, Any] = {"by": self.by, "at": self.at}
        out.update(self.extra)
        return out


def _is_valid_iso_date(value: str) -> bool:
    if not isinstance(value, str) or not _ISO_DATE_STRICT_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_source_entry(entry: str) -> SourceEntry:
    """Parse and syntax-check one ``sources`` item (raises ValueError)."""
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError("source entry must be a non-empty string")
    tokens = entry.strip().split()
    head = tokens[0]
    if ":" not in head:
        raise ValueError(f"source entry missing '<kind>:<id>': {entry!r}")
    kind, source_id = head.split(":", 1)
    if not kind or not source_id:
        raise ValueError(
            f"source entry must have non-empty kind and id: {entry!r}")
    attrs: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise ValueError(
                f"invalid source attribute (expected key=value): {token!r}")
        key, val = token.split("=", 1)
        if key not in SOURCE_ATTR_KEYS:
            raise ValueError(f"unknown source attribute key: {key!r}")
        if key in attrs:
            raise ValueError(f"duplicate source attribute key: {key!r}")
        if not val:
            raise ValueError(
                f"empty value for source attribute {key!r}: {entry!r}")
        if key in ("issued", "retrieved") and not _is_valid_iso_date(val):
            raise ValueError(
                f"invalid ISO date for {key}={val!r} in {entry!r}")
        if key == "genre" and val not in GENRE_VALUES:
            raise ValueError(
                f"invalid source genre {val!r} (expected one of {GENRE_VALUES}) in {entry!r}")
        attrs[key] = val
    return SourceEntry(kind=kind, id=source_id, attrs=attrs,
                       raw=entry.strip())


def resolve_source_genre(entry: SourceEntry) -> str:
    """Resolve effective source genre: explicit ``genre=`` wins over ``kind`` default."""
    explicit = entry.attrs.get("genre")
    if explicit in GENRE_VALUES:
        return explicit
    if entry.kind in ("paper", "preprint"):
        return "paper"
    if entry.kind.startswith("patent-"):
        return "patent"
    if entry.kind in WEB_SOURCE_KINDS:
        return "web"
    return "other"

SPECIAL_FILES = {"index.md", "log.md"}
_INDEX_RE = re.compile(r"^index(?:-\d+)?\.md$")

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_ANY_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TOKEN_RE = re.compile(r"[0-9A-Za-z_]+|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")
_LINK_RE = re.compile(
    r"(?<!!)\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+)"
    r"(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
_WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n]+)\]\]")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


# Heading -> relationship scope.  The edge weight belongs to the section in
# which the link appears (not merely to the target node type).
_SCOPE_HEADING_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gotchas", ("gotcha", "anti-pitfall", "antipattern", "pitfall",
                 "落とし穴", "失敗", "アンチパターン")),
    ("synergistic", ("synerg", "combination", "相乗", "組み合わせ")),
    ("workflow", ("workflow", "implementation", "procedure", "手順", "実装")),
    ("taxonomy", ("taxonomy", "classification", "definition", "分類", "定義")),
)


@dataclass
class Link:
    """A Markdown link with its resolved, wiki-root-relative target."""

    text: str
    target: str
    line: int
    resolved: str | None = None
    external: bool = False
    heading: str = ""
    section_scope: str | None = None
    context: str = ""


@dataclass
class Section:
    """One Markdown heading section (text excludes the heading line)."""

    heading: str
    level: int
    text: str
    scope: str | None = None


@dataclass
class Concept:
    """One OKF topic (one file)."""

    path: Path
    rel: str
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    links: list[Link] = field(default_factory=list)

    @property
    def type(self) -> str:
        value = self.meta.get("type")
        return value if isinstance(value, str) else ""

    @property
    def title(self) -> str:
        value = self.meta.get("title")
        if isinstance(value, str) and value.strip():
            return value.strip()
        heading = _HEADING_RE.search(self.body)
        if heading:
            return heading.group(1).strip()
        return self.path.stem

    @property
    def description(self) -> str:
        value = self.meta.get("description")
        return value.strip() if isinstance(value, str) else ""

    @property
    def tags(self) -> list[str]:
        value = self.meta.get("tags")
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    @property
    def timestamp(self) -> str | None:
        value = self.meta.get("timestamp")
        return value if isinstance(value, str) else None

    @property
    def resource(self) -> str | None:
        value = self.meta.get("resource")
        return value if isinstance(value, str) else None

    @property
    def scope(self) -> str:
        return scope_of(self.meta)

    @property
    def basis(self) -> str | None:
        value = self.meta.get("basis")
        return value if isinstance(value, str) and value else None

    @property
    def sources(self) -> list[str | dict[str, Any]]:
        value = self.meta.get("sources")
        if not isinstance(value, list):
            return []
        result: list[str | dict[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                res = item.get("resource")
                if isinstance(res, str) and res.strip():
                    result.append(dict(item))
            else:
                result.append(str(item))
        return result

    @property
    def source_records(self) -> list[SourceRecord]:
        """Return structured v0.3 ``sources`` entries as :class:`SourceRecord` objects."""
        value = self.meta.get("sources")
        if not isinstance(value, list):
            return []
        records: list[SourceRecord] = []
        for item in value:
            if isinstance(item, Mapping):
                try:
                    records.append(SourceRecord.from_mapping(item))
                except ValueError:
                    continue
        return records

    @property
    def generated(self) -> ProvenanceEvent | None:
        """Return the ``generated`` event if present and valid."""
        value = self.meta.get("generated")
        if not isinstance(value, Mapping):
            return None
        try:
            return ProvenanceEvent.from_mapping(value)
        except ValueError:
            return None

    @property
    def verified(self) -> list[ProvenanceEvent]:
        """Return ``verified`` events (accepting a single bare mapping per §5.2)."""
        value = self.meta.get("verified")
        if isinstance(value, Mapping):
            items: list[Any] = [value]
        elif isinstance(value, list):
            items = value
        else:
            return []
        events: list[ProvenanceEvent] = []
        for item in items:
            if isinstance(item, Mapping):
                try:
                    events.append(ProvenanceEvent.from_mapping(item))
                except ValueError:
                    continue
        return events

    @property
    def verified_at(self) -> str | None:
        value = self.meta.get("verified_at")
        return value if isinstance(value, str) and value else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": self.rel,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "scope": self.scope,
            "timestamp": self.timestamp,
            "resource": self.resource,
            "basis": self.basis,
            "generated": self.generated.to_dict() if self.generated else None,
            "sources": self.sources,
            "verified": [event.to_dict() for event in self.verified],
            "verified_at": self.verified_at,
        }


def scope_from_heading(heading: str) -> str | None:
    """Map a section heading such as ``## Gotchas / Anti-Pitfalls`` to a scope."""
    value = heading.casefold()
    if not value:
        return None
    for scope, needles in _SCOPE_HEADING_PATTERNS:
        if any(needle in value for needle in needles):
            return scope
    return None


def tokenize(text: str) -> list[str]:
    """Deterministic, dependency-free tokenizer for relevance scoring."""
    return _TOKEN_RE.findall(text.casefold())


def relevance(query_tokens: set[str] | list[str] | tuple[str, ...],
              text: str) -> float:
    """``|Q ∩ Tokens(text)| / |Q|``; 1.0 for an empty query."""
    wanted = set(query_tokens)
    if not wanted:
        return 1.0
    return len(wanted & set(tokenize(text))) / len(wanted)


def scope_of(meta: dict[str, Any]) -> str:
    """Classify a node into one of the traversal scope weights."""
    explicit = meta.get("scope")
    if isinstance(explicit, str) and explicit.casefold() in SCOPE_WEIGHTS:
        return explicit.casefold()

    type_name = str(meta.get("type") or "").casefold()
    tags = {str(tag).casefold() for tag in (meta.get("tags") or [])
            if isinstance(meta.get("tags"), list)}
    haystack = type_name + " " + " ".join(tags)

    if "gotcha" in haystack:
        return "gotchas"
    if "synerg" in haystack:
        return "synergistic"
    if "workflow" in haystack or "procedure" in haystack:
        return "workflow"
    return "taxonomy"


def validate_meta(meta: dict[str, Any]) -> list[str]:
    """Return human-readable OKF metadata errors (empty when valid)."""
    errors: list[str] = []
    if not isinstance(meta, dict):
        return ["frontmatter must be a mapping"]

    type_value = meta.get("type")
    if not isinstance(type_value, str) or not type_value.strip():
        errors.append("missing required field: type")

    for key in ("title", "description", "resource", "timestamp"):
        value = meta.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{key} must be a string")

    tags = meta.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(
                isinstance(tag, str) for tag in tags):
            errors.append("tags must be a list of strings")

    timestamp = meta.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"invalid timestamp: {timestamp}")

    scope = meta.get("scope")
    if scope is not None:
        if not isinstance(scope, str) or scope.casefold() not in SCOPE_WEIGHTS:
            errors.append(f"unknown scope: {scope}")

    basis = meta.get("basis")
    if basis is not None:
        if not isinstance(basis, str):
            errors.append(f"invalid basis: {basis}")

    sources = meta.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            errors.append("sources must be a list of strings or mappings")
        else:
            for item in sources:
                if isinstance(item, str):
                    try:
                        parse_source_entry(item)
                    except ValueError as exc:
                        errors.append(f"invalid source entry: {exc}")
                elif isinstance(item, Mapping):
                    try:
                        SourceRecord.from_mapping(item)
                    except ValueError as exc:
                        errors.append(f"invalid source entry: {exc}")
                    else:
                        for ext_key in ("x-okfkb-issued", "x-okfkb-retrieved"):
                            if ext_key in item and item[ext_key] is not None:
                                ext_val = item[ext_key]
                                if (
                                    not isinstance(ext_val, str)
                                    or not _is_valid_iso_date(ext_val)
                                ):
                                    errors.append(f"invalid {ext_key}: {ext_val}")
                        if "x-okfkb-genre" in item and item["x-okfkb-genre"] is not None:
                            genre_val = item["x-okfkb-genre"]
                            if (
                                not isinstance(genre_val, str)
                                or genre_val not in GENRE_VALUES
                            ):
                                errors.append(
                                    f"invalid x-okfkb-genre: {genre_val} "
                                    f"(expected one of {GENRE_VALUES})"
                                )
                else:
                    errors.append("sources items must be strings or mappings")

    generated = meta.get("generated")
    if generated is not None:
        try:
            ProvenanceEvent.from_mapping(generated)
        except ValueError as exc:
            errors.append(f"invalid generated event: {exc}")

    verified = meta.get("verified")
    if verified is not None:
        if isinstance(verified, Mapping):
            verified_items: list[Any] = [verified]
        elif isinstance(verified, list):
            verified_items = verified
        else:
            errors.append("verified must be a mapping or list of mappings")
            verified_items = []
        for item in verified_items:
            try:
                ProvenanceEvent.from_mapping(item)
            except ValueError as exc:
                errors.append(f"invalid verified event: {exc}")

    verified_at = meta.get("verified_at")
    if verified_at is not None:
        if (not isinstance(verified_at, str)
                or not _is_valid_iso_date(verified_at)):
            errors.append(f"invalid verified_at: {verified_at}")

    x_verified_at = meta.get("x-okfkb-verified-at")
    if x_verified_at is not None:
        if (not isinstance(x_verified_at, str)
                or not _is_valid_iso_date(x_verified_at)):
            errors.append(f"invalid x-okfkb-verified-at: {x_verified_at}")
    return errors


def extract_links(body: str, source_rel: str) -> list[Link]:
    """Extract non-image Markdown links, ignoring fenced blocks and code.

    Each link remembers its nearest heading and the nearest recognised
    standard section scope (e.g. ``Gotchas / Anti-Pitfalls``).  Deeper
    subheadings inherit an outer recognised scope.
    """
    links: list[Link] = []
    fence: str | None = None
    stack: list[tuple[int, str, str | None]] = []
    for number, line in enumerate(body.splitlines(), start=1):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            continue

        heading = _ANY_HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text, scope_from_heading(text)))

        current_heading = next(
            (text for _, text, _ in reversed(stack)
             if not is_transparent_heading(text)),
            "",
        )
        section_scope = next(
            (scope for _, _, scope in reversed(stack) if scope), None)

        for match in _LINK_RE.finditer(_INLINE_CODE_RE.sub("", line)):
            target = match.group(2).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1].strip()
            if not target or target.startswith("#"):
                continue
            external = bool(_SCHEME_RE.match(target)) or target.startswith("//")
            if external:
                continue  # relative links only: they are the graph edges
            anchor = match.group(1)
            context = " ".join(part for part in
                               (anchor, current_heading, line.strip()) if part)
            links.append(Link(
                text=anchor, target=target, line=number,
                resolved=resolve_link(source_rel, target), external=False,
                heading=current_heading, section_scope=section_scope,
                context=context,
            ))
    return links


def find_wikilinks(body: str) -> list[tuple[int, str]]:
    """Find unsupported ``[[WikiLink]]`` / ``![[embed]]`` syntax.

    The canonical OKF link form is a relative Markdown link.  This helper lets
    validation warn instead of silently ignoring links written in Obsidian's
    vault-wide syntax (also inside fenced code blocks, which are skipped).
    """
    found: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.splitlines(), start=1):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            continue
        for match in _WIKILINK_RE.finditer(_INLINE_CODE_RE.sub("", line)):
            found.append((number, match.group(0)))
    return found


def extract_sections(body: str) -> list[Section]:
    """Split Markdown into heading sections, ignoring fenced code blocks."""
    sections: list[Section] = []
    stack: list[tuple[int, str, str | None]] = []
    heading, level, scope = "", 0, None
    buffer: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if heading or buffer:
            sections.append(Section(heading=heading, level=level,
                                    text="\n".join(buffer).strip("\n"),
                                    scope=scope))

    for line in body.splitlines():
        stripped = line.lstrip()
        if fence:
            buffer.append(line)
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            buffer.append(line)
            continue
        match = _ANY_HEADING_RE.match(stripped)
        if match:
            flush()
            buffer = []
            level = len(match.group(1))
            heading = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading, scope_from_heading(heading)))
            scope = next((item[2] for item in reversed(stack) if item[2]), None)
        else:
            buffer.append(line)
    flush()
    return sections


def resolve_link(source_rel: str, target: str) -> str | None:
    """Resolve ``target`` relative to ``source_rel`` inside the wiki root.

    Returns a POSIX relative path, or ``None`` when the link escapes the root
    (or is absolute). The target file does not have to exist.
    """
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0]).strip()
    if not clean:
        return None
    if clean.startswith("/"):
        candidate = posixpath.normpath(clean.lstrip("/"))
    else:
        candidate = posixpath.normpath(
            posixpath.join(posixpath.dirname(source_rel), clean))
    if candidate in ("", ".", "..") or candidate.startswith("../"):
        return None
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        return None
    return candidate


def load_concept(path: str | Path, root: str | Path) -> Concept:
    """Load and parse one Markdown file as an OKF concept."""
    path = Path(path)
    root = Path(root)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise FrontmatterError(f"{path} is outside the wiki root") from exc
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return Concept(path=path, rel=rel, meta=meta, body=body,
                   links=extract_links(body, rel))


def iter_concepts(
    root: str | Path,
    *,
    errors: list[tuple[str, str]] | None = None,
) -> list[Concept]:
    """Return all concept nodes under ``root``, sorted by relative path.

    Files with malformed frontmatter are skipped; if ``errors`` is provided,
    ``(rel, message)`` pairs are appended to it.
    """
    root = Path(root)
    concepts: list[Concept] = []
    if not root.exists():
        return concepts
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if is_special(rel):
            continue
        try:
            concepts.append(load_concept(path, root))
        except FrontmatterError as exc:
            if errors is not None:
                errors.append((rel, str(exc)))
    return concepts


def write_concept(path: str | Path, meta: dict[str, Any],
                  body: str = "") -> Path:
    """Atomically write a concept document (PID-scoped ``.tmp`` + ``os.replace``)."""
    target = Path(path)
    _atomic_write(target, dump_document(meta, body))
    return target


def is_special(rel: str) -> bool:
    parts = rel.split("/")
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return True
    return parts[-1] in SPECIAL_FILES or bool(_INDEX_RE.match(parts[-1]))
