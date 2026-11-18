# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

## [Unreleased]

### Added

- Informational `outgoing_links` and `backlinks` fields on search hits in
  `okf search --json` and MCP `okf_search`, reporting the number of distinct
  internal notes linked to and from in the same KB without affecting scoring,
  ranking, or breakdown totals.

### Changed

- Deferred heavy top-level imports in `wiki/cli.py`, `wiki/tooling.py`,
  `wiki/validate.py`, and `wiki/export.py` using PEP 562 (`__getattr__` /
  `__dir__`), moving shared export constants to `wiki/model.py` and unifying
  package error handling under `_common.OkfError`. Initial `okf_kb_agent.*`
  module loads dropped from 21 to 6 for `okf_kb_agent.wiki.cli` and from 14 to
  5 for `okf_kb_agent.wiki.mcp_server`.
- Extended `_common._atomic_write` to accept `str | bytes`, use PID-scoped
  temporary filenames (`.{name}.{pid}.tmp`), and clean up failed writes in a
  `finally` block; removed duplicate atomic-write helpers in
  `wiki/evolution.py` and `wiki/verify.py` (keeping `_atomic_write_bytes` as a
  compatibility alias).
- Unified the remaining inline `.tmp` atomic-write implementations in
  `wiki/index.py`, `wiki/model.py`, `wiki/onnx_backend.py`, and
  `wiki/synonyms.py` onto `_common._atomic_write`, and made `UsptoError` and
  `BulkError` inherit from `_common.OkfError`.
- Extended `SQLiteSearchBackend.search()` (Pattern B) to honour explicit
  `AND`/`OR` boolean operators (without treating standalone operator tokens as
  search terms) and `include_admin`/`doc_type`/`scope` filters aligned with
  Pattern A, and documented backend capabilities in `okf search`/`context`
  `--backend` help.

### Fixed

- Fixed variable shadowing in `_common._safe_name` where non-ASCII-only inputs
  hashed the emptied string (`da39a3ee5e6b`) instead of the original input,
  preventing cache-key collisions across non-ASCII queries.
- Made `tests/test_run_batch.py` resilient on systems with `noexec`-mounted
  `/tmp` by probing tempdir executability in `_executable_tempdir()` and
  falling back to `.pytest_cache/`.

## [0.2.0] - 2026-11-02

### Added

- OKF v0.2 Markdown knowledge base with progressive-disclosure indexes,
  heading-weighted traversal, Gotchas-filtered context resolution and relative
  Markdown links as the canonical relationship format.
- Pattern B SQLite FTS5 search backend with incremental sync and an
  adjacency-list edge table.
- Opt-in Pattern C adapters for ONNX Runtime, Qdrant and HTTP/Gemma embeddings;
  unavailable optional infrastructure fails closed with `BackendUnavailable`.
- EPO OPS client with cache-first access, cross-process fair-use spacing,
  bounded search results and token caching.
- USPTO Open Data Portal client and bulk-download helpers.
- MCP stdio and HTTP transports with a minimal stateless single-event SSE
  endpoint, bearer authentication, loopback defaults and `/health`.
- Bounded synonym expansion and offline synonym evaluation.
- Deterministic EvolutionLoop clustering, skill drafts, non-destructive
  `--propose` review files and explicit `--force` refresh.
- Release gates: offline smoke test, wheel/sdist content inspection, secret
  boundary checks, a public-release guard and a Python 3.12/3.13/3.14 CI
  matrix.
- Synthetic `examples/wiki` data with no real EPO patent content, plus a
  documented public-release audit.

### Changed

- Minimum supported Python is now **3.12**; Python 3.14 is the recommended
  development and runtime version.
- CI treats `ResourceWarning` as an error and verifies cleanup of SQLite
  connections and HTTP responses.
- The private reuse bundle is explicitly separated from public wheel/sdist
  artifacts; `.secrets/` and `data/external/` are never included in builds.

### Known limitations

- USPTO-to-OKF automatic ingestion is not connected.
- Real Qdrant, Gemma/HTTP embedding and ONNX model deployments are not bundled
  or exercised by CI.
- MCP HTTP does not implement multi-session SSE, OAuth, audit logging or rate
  limiting.
- EvolutionLoop does not perform automatic LLM mutation or skill merging.
