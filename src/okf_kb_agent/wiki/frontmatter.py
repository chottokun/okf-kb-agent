"""Minimal, dependency-free YAML frontmatter subset used by OKF documents.

Supports scalars, inline lists, flow/block mappings, and block lists
(including lists of mappings such as ``sources`` and ``verified``) while
keeping the parser small and free of third-party runtime dependencies.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .._common import OkfError

__all__ = [
    "FrontmatterError",
    "dump_document",
    "dump_frontmatter",
    "parse_frontmatter",
]

_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?:[ \t]*(.*))?$")
_MAPPING_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?:[ \t]+(.*)|[ \t]*)$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")

_KEY_ORDER = (
    "type", "okf_version", "title", "description", "license", "resource",
    "tags", "timestamp", "scope", "publication", "basis", "generated",
    "sources", "verified", "verified_at", "x-okfkb-verified-at",
)

_NESTED_KEY_ORDER = (
    "id", "resource", "title", "author", "usage_count", "last_modified",
    "by", "at",
)


class FrontmatterError(OkfError, ValueError):
    """Raised when a document has malformed or unsupported frontmatter."""


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into ``(metadata, body)``.

    The document must start with a ``---`` line and close it with ``---`` or
    ``...``. Supports scalars, inline lists, flow/block mappings, and block
    lists (including lists of mappings).
    """
    if not isinstance(text, str):
        raise FrontmatterError("document must be text")
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("missing YAML frontmatter (expected '---')")

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            end = index
            break
    if end is None:
        raise FrontmatterError("unclosed YAML frontmatter")

    entries: list[tuple[int, str]] = []
    for raw in lines[1:end]:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if line[indent:indent + 1] == "\t":
            raise FrontmatterError(
                "tabs are not supported for indentation in OKF frontmatter")
        entries.append((indent, line[indent:]))

    meta: dict[str, Any] = {}
    if entries:
        if entries[0][0] != 0:
            raise FrontmatterError(
                f"indented value without a key: {entries[0][1]!r}")
        meta, idx = _parse_block_mapping(entries, 0, 0)
        if idx < len(entries):
            raise FrontmatterError(
                f"unexpected frontmatter line: {entries[idx][1]!r}")

    body = "".join(lines[end + 1:])
    return meta, body


def dump_document(meta: Mapping[str, Any], body: str = "") -> str:
    """Render ``meta`` and ``body`` as an OKF Markdown document."""
    return dump_frontmatter(meta) + body


def dump_frontmatter(meta: Mapping[str, Any]) -> str:
    """Render deterministic YAML frontmatter (standard keys first)."""
    if not isinstance(meta, Mapping):
        raise FrontmatterError("metadata must be a mapping")
    lines = ["---"]
    lines.extend(_dump_mapping(meta, 0, _KEY_ORDER))
    lines.append("---")
    return "\n".join(lines) + "\n"


# -- parsing helpers --------------------------------------------------------

def _is_list_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _parse_indented_or_none(
    entries: list[tuple[int, str]],
    idx: int,
    parent_indent: int,
) -> tuple[Any, int]:
    if idx < len(entries) and entries[idx][0] > parent_indent:
        next_indent, next_content = entries[idx]
        if _is_list_item(next_content):
            return _parse_block_list(entries, idx, next_indent)
        return _parse_block_mapping(entries, idx, next_indent)
    return None, idx


def _parse_block_mapping(
    entries: list[tuple[int, str]],
    idx: int,
    expected_indent: int,
    initial: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = initial if initial is not None else {}
    while idx < len(entries):
        indent, content = entries[idx]
        if indent < expected_indent:
            break
        if indent > expected_indent:
            raise FrontmatterError(f"unexpected indentation: {content!r}")
        if _is_list_item(content):
            raise FrontmatterError(
                f"unexpected list item in mapping: {content!r}")
        match = _KEY_RE.match(content)
        if not match:
            raise FrontmatterError(f"invalid frontmatter line: {content!r}")
        key = match.group(1)
        if key in mapping:
            raise FrontmatterError(f"duplicate frontmatter key: {key}")
        raw_val = _strip_comment(match.group(2) or "").strip()
        if raw_val == "":
            mapping[key], idx = _parse_indented_or_none(
                entries, idx + 1, expected_indent)
        else:
            mapping[key] = _parse_value(raw_val)
            idx += 1
    return mapping, idx


def _parse_block_list(
    entries: list[tuple[int, str]],
    idx: int,
    expected_indent: int,
) -> tuple[list[Any], int]:
    items: list[Any] = []
    while idx < len(entries):
        indent, content = entries[idx]
        if indent < expected_indent:
            break
        if indent > expected_indent:
            raise FrontmatterError(f"unexpected indentation: {content!r}")
        if not _is_list_item(content):
            raise FrontmatterError(f"expected list item, got: {content!r}")

        after_dash = content[1:]
        rest = after_dash.lstrip(" ")
        if _strip_comment(rest).strip() == "":
            item, idx = _parse_indented_or_none(
                entries, idx + 1, expected_indent)
            items.append(item)
            continue

        match = _MAPPING_KEY_RE.match(rest)
        if match:
            key = match.group(1)
            raw_val = _strip_comment(match.group(2) or "").strip()
            item_indent = indent + 1 + (len(after_dash) - len(rest))
            item_map: dict[str, Any] = {}
            if raw_val == "":
                item_map[key], idx = _parse_indented_or_none(
                    entries, idx + 1, item_indent)
            else:
                item_map[key] = _parse_value(raw_val)
                idx += 1
            if (
                idx < len(entries)
                and entries[idx][0] == item_indent
                and not _is_list_item(entries[idx][1])
            ):
                _, idx = _parse_block_mapping(
                    entries, idx, item_indent, initial=item_map)
            items.append(item_map)
        else:
            items.append(_parse_value(rest))
            idx += 1
    return items, idx


def _parse_value(value: str) -> Any:
    value = _strip_comment(value).strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(part.strip()) for part in _split_inline(inner)]
    if value.startswith("{") and value.endswith("}"):
        return _parse_flow_mapping(value[1:-1].strip())
    return _parse_scalar(value)


def _parse_flow_mapping(inner: str) -> dict[str, Any]:
    if not inner:
        return {}
    result: dict[str, Any] = {}
    for part in _split_inline(inner):
        entry = part.strip()
        if not entry:
            raise FrontmatterError(f"empty flow mapping entry in {{{inner}}}")
        colon = _find_unquoted_colon(entry)
        if colon < 0:
            raise FrontmatterError(f"invalid flow mapping entry: {entry!r}")
        raw_key = entry[:colon].strip()
        raw_val = entry[colon + 1:].strip()
        key = str(_parse_scalar(raw_key)) if raw_key[:1] in ('"', "'") else raw_key
        if not _KEY_RE.match(f"{key}:"):
            raise FrontmatterError(f"invalid frontmatter key: {key!r}")
        if key in result:
            raise FrontmatterError(f"duplicate frontmatter key: {key}")
        result[key] = _parse_value(raw_val) if raw_val else None
    return result


def _find_unquoted_colon(text: str) -> int:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char == ":":
            return index
    return -1


def _strip_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def _split_inline(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in inner:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
            current.append(char)
            continue
        if char in ("[", "{"):
            depth += 1
        elif char in ("]", "}") and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(
                f"invalid double-quoted scalar: {value!r}") from exc
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    lowered = value.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    if _INT_RE.match(value):
        return int(value)
    if _FLOAT_RE.match(value):
        return float(value)
    return value


# -- dumping helpers --------------------------------------------------------

def _ordered_keys(
    mapping: Mapping[str, Any],
    order: tuple[str, ...],
) -> list[str]:
    keys = [key for key in order if key in mapping]
    keys += sorted(key for key in mapping if key not in order)
    for key in keys:
        if not isinstance(key, str) or not _KEY_RE.match(f"{key}:"):
            raise FrontmatterError(f"invalid frontmatter key: {key!r}")
    return keys


def _is_scalar_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(
        item is None or isinstance(item, (bool, int, float, str))
        for item in value
    )


def _dump_mapping(
    mapping: Mapping[str, Any],
    indent: int,
    order: tuple[str, ...],
) -> list[str]:
    prefix = " " * indent
    lines: list[str] = []
    for key in _ordered_keys(mapping, order):
        val = mapping[key]
        if isinstance(val, Mapping):
            if not val:
                lines.append(f"{prefix}{key}: {{}}")
            else:
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_mapping(val, indent + 2, _NESTED_KEY_ORDER))
        elif isinstance(val, (list, tuple)) and not _is_scalar_sequence(val):
            lines.append(f"{prefix}{key}:")
            lines.extend(_dump_block_list(val, indent + 2))
        else:
            lines.append(f"{prefix}{key}: {_format_value(val)}")
    return lines


def _dump_block_list(
    items: list[Any] | tuple[Any, ...],
    indent: int,
) -> list[str]:
    prefix = " " * indent
    lines: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            if not item:
                lines.append(f"{prefix}- {{}}")
            else:
                item_lines = _dump_mapping(item, indent + 2, _NESTED_KEY_ORDER)
                lines.append(f"{prefix}- {item_lines[0][indent + 2:]}")
                lines.extend(item_lines[1:])
        elif isinstance(item, (list, tuple)) and not _is_scalar_sequence(item):
            lines.append(f"{prefix}-")
            lines.extend(_dump_block_list(item, indent + 2))
        else:
            lines.append(f"{prefix}- {_format_value(item)}")
    return lines


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _format_scalar(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    raise FrontmatterError(
        f"unsupported frontmatter value type: {type(value).__name__}")


def _format_scalar(value: str) -> str:
    if value == "":
        return '""'
    unsafe = (
        "\n" in value or "\r" in value or "\t" in value
        or value != value.strip()
        or "#" in value or ": " in value or value.endswith(":")
        or value.casefold() in {"yes", "no", "on", "off", "y", "n"}
        or bool(re.match(r"^\d{4}-\d{2}-\d{2}([T ].*)?$", value))
        or value.startswith(("[", "]", "{", "}", "- ", "? ", "! ", "& ",
                            "* ", "|", ">", "'", '"', "%", "@", "`"))
        or value[0] in "!&*|>@`%"
    )
    if unsafe:
        return json.dumps(value, ensure_ascii=False)
    # Quote anything that would round-trip as a bool/number/null.
    if _parse_scalar(value) != value:
        return json.dumps(value, ensure_ascii=False)
    return value
