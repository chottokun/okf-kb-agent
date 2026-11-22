# okf-kb-agent

Python 3.12+ (stdlib-first) toolkit for building, validating, searching, auditing, and serving **evidence-grounded OKF v0.2 Markdown knowledge bases**, combining deterministic **source verification** (`arXiv`, Crossref `DOI`, Web/datasheets, local files, operational records), weighted **graph traversal**, a token-bounded **context compiler**, an **MCP server** (`okf-mcp`), and cache-first **EPO OPS / EPS** and **USPTO Open Data Portal (ODP)** patent clients.

> [!NOTE]
> Detailed Japanese documentation is available in [`docs/`](docs/):
> - [docs/kb_building_guide.md](docs/kb_building_guide.md) — Step-by-step practical guide to building an OKF knowledge base from scratch (JP)
> - [docs/okf_wiki.md](docs/okf_wiki.md) — OKF v0.2 specification, provenance rules, and CLI / MCP reference (JP)
> - [docs/design_rationales.md](docs/design_rationales.md) — Design rationales, classical keyword search completion, and operational gotchas (JP)

## Supported Knowledge Base Profiles

OKF v0.2 stores knowledge as plain Markdown + YAML frontmatter (`1 topic = 1 file`) with explicit provenance (`basis`, `sources`, `verified_at`) and relative-link edges:

| Profile | Typical `sources:` Kinds | Evidence Grounding | Best Suited For |
| --- | --- | --- | --- |
| **Academic Papers & Preprints** | `paper`, `preprint` (`arXiv`, Crossref `DOI`) | `<kb>/evidence/` snapshots + fulltext `.txt` | AI/CS research, scientific literature surveys |
| **Web, Datasheets & Local Materials** | `datasheet`, `product-page`, `standard`, `web`, `local-file` | `<kb>/evidence/` or `data/external/source_verify/` (`okf verify-source --file` for offline inputs) | Vendor specs, technical documentation, internal PDFs/memos |
| **Operational Records & Procedures** | `ops-record` | SHA-256 `.txt` + `.meta.json` snapshots in `<kb>/evidence/` | Engineering runbooks, experiment logs, system operations |
| **Patents & Technical Surveys** | `patent-biblio`, `patent-claims`, `patent-family` | EPO OPS/EPS cache + `okf ingest-epo` / `uspto` | Patent landscaping, claim analysis, industrial technology |

## Features & Repository Layout

### OKF Knowledge Base (`src/okf_kb_agent/wiki/`)

- `src/okf_kb_agent/wiki/` — OKF v0.2 Markdown knowledge base (Pattern A in-memory; Pattern B SQLite-FTS5; optional Pattern C)
- `src/okf_kb_agent/wiki/verify.py` — deterministic source verifier & snapshot grounding for `arXiv`, `DOI`, Web URLs, and local files (`okf verify-source`)
- `src/okf_kb_agent/wiki/validate.py` — structure, link, provenance (`--strict-provenance`), and evidence snapshot (`--check-evidence`) gates
- `src/okf_kb_agent/wiki/candidate.py` — pre-flight duplicate, synonym, and tag-collision checker (`okf candidate-check`)
- `src/okf_kb_agent/wiki/search.py` & `src/okf_kb_agent/wiki/graph.py` — classical keyword search (`AND`/`OR`/`*`, typo/inflection fallback, score breakdown), weighted traversal, unweighted BFS neighbor & link-context lookup (`okf neighbors`), and link reachability diagnostics (`okf links`)
- `src/okf_kb_agent/wiki/claims.py` — deterministic numeric-claim extraction and seeded audit sampling (`okf claims`)
- `src/okf_kb_agent/wiki/export.py` — offline multi-KB viewer JSON bundle exporter (`okf export`, format v2 with first-class `papers`, `concepts`, `patents`, `synonyms`)
- `src/okf_kb_agent/wiki/tooling.py` — deterministic JSON tool contracts + path-bounded dispatcher
- `src/okf_kb_agent/wiki/mcp_server.py` & `src/okf_kb_agent/wiki/mcp_http.py` — MCP server (`okf-mcp`; stdio and loopback/Bearer-guarded HTTP/SSE transports)
- `src/okf_kb_agent/wiki/embeddings.py` & `src/okf_kb_agent/wiki/qdrant_backend.py` — optional Pattern C HTTP / Gemma embedding and Qdrant REST adapters
- `src/okf_kb_agent/wiki/synonyms.py` — bounded query expansion + synonym evaluation (`sync-synonyms`, `eval-synonyms`)
- `src/okf_kb_agent/wiki/evolution.py` — deterministic `EvolutionLoop` + non-destructive skill proposals (`okf evolve`)

### Patent Clients (`src/okf_kb_agent/`)

- `src/okf_kb_agent/epo.py` — EPO OPS v3.2 + EPS client and CLI (`epo`; stdlib-only)
- `src/okf_kb_agent/uspto.py` — USPTO Open Data Portal client and CLI (`uspto`; stdlib-only)
- `src/okf_kb_agent/uspto_bulk.py` — USPTO bulk product / grant XML downloader & parser

### Skills, Examples, Scripts & Docs

- `.agents/skills/` — project skills (`okf-wiki`, `okf-design-conventions`, `source-verify`, `kb-search`, `kb-batch-discipline`, `kb-audit`, `kb-intake`, `kb-create`, `patent-to-wiki`, `create-skill`, `modify-skill`)
- `examples/wiki/` — synthetic demo wiki (concepts, workflows, gotchas, synergistic notes, and synthetic patents)
- `scripts/release_smoke.py` — offline CLI/MCP release smoke test
- `scripts/check_dist.py` — wheel/sdist secret and CLI-content guard
- `scripts/check_public_repo.py` — tracked-tree secret/path guard
- `scripts/export_kb_viewer_all.py` — prototype multi-KB viewer JSON bundle exporter (`--base`, `--out`, `--scope`)
- `docs/kb_building_guide.md` — 第三者向け OKF ナレッジベース構築実践ガイド (JP)
- `docs/okf_wiki.md` — OKF knowledge base design and CLI/MCP reference (JP)
- `docs/design_rationales.md` — 設計判断の理由・古典的検索の完成・運用の落とし穴・開発メモ (JP)
- `docs/epo_api.md` — EPO OPS/EPS usage notes (JP)
- `docs/uspto_api.md` — USPTO ODP usage notes (JP)
- `docs/release_checklist.md` — release gates, smoke tests and known limitations
- `docs/public_release_audit.md` — public-push audit and owner checklist

## Quick Start with `uv` (Recommended)

Building and operating an OKF knowledge base with papers, web pages, local files, or operational records requires **no API credentials**:

```bash
# 1. Setup & offline verification
uv sync                                          # creates .venv from pyproject.toml
uv run python -m unittest discover -s tests -v   # offline unit test suite
uv run python scripts/release_smoke.py           # offline CLI & MCP release smoke

# 2. Initialize an OKF knowledge base and verify bound skills / contracts
uv run okf init mywiki \
  --skills-dir .agents/skills \
  --skills-dir .opencode/skills
uv run okf skills mywiki --check --json
uv run okf schema --json

# 3. Pre-flight duplicate & tag-collision check before authoring new concepts
uv run okf candidate-check --json mywiki concept-a concept-b

# 4. Verify & snapshot primary sources into <kb>/evidence/
export OKF_VERIFY_RATE_STATE=/tmp/okf_verify_rate_state.json
uv run okf verify-source "arXiv:2309.06180" --cache-dir mywiki/evidence --json
uv run okf verify-source --file ./local.pdf --cache-dir mywiki/evidence --genre other --json

# 5. Search, traverse the Markdown link graph, and compile bounded context
uv run okf search mywiki "attention AND kv-cache*"
uv run okf traverse mywiki concepts/my-concept --depth 2
uv run okf neighbors mywiki concepts/my-concept --hops 1 --json
uv run okf context mywiki "your query" --max-nodes 5
uv run okf sync-synonyms mywiki
uv run okf search mywiki "alias query" --expand --json
uv run okf eval-synonyms mywiki --check

# 6. Index, validate provenance & evidence, diagnose links, and sample numeric claims
uv run okf index mywiki
uv run okf index mywiki --check
uv run okf validate mywiki \
  --strict-provenance \
  --check-evidence \
  --evidence-dir mywiki/evidence
uv run okf links mywiki --json                   # diagnose zero-inbound / isolated concepts & components
uv run okf claims mywiki --sample 5 --seed 42 --json

# 7. Export viewer bundle, sync Pattern B SQLite, evolve skills, or serve via MCP
uv run okf export mywiki --out /tmp/okf-export.json --json
uv run okf sqlite mywiki                         # Pattern B (SQLite-FTS5)
uv run okf evolve mywiki --history .agents/flow_history.jsonl
uv run okf evolve mywiki --history .agents/flow_history.jsonl --propose
uv run okf-mcp --root .                          # stdio MCP server for LLM clients

# Optional Pattern C (requires a Qdrant server + embedding endpoint)
# export QDRANT_URL=http://localhost:6333
# export OKF_EMBEDDING_URL=http://localhost:8080/v1/embeddings
# export OKF_EMBEDDING_MODEL=gemma-embedding-2
uv run okf qdrant mywiki
uv run okf search mywiki "semantic query" --backend qdrant

# HTTP MCP transport (loopback default; token required off-loopback)
OKF_MCP_TOKEN=change-me uv run okf-mcp --root . --transport http --port 8765
```

Pattern C is opt-in: `auto` uses Pattern B above 500 nodes. Qdrant, ONNX Runtime and remote embedding servers are optional infrastructure; if they are absent the CLI/library raises `BackendUnavailable` and Markdown stays authoritative.

## Patent Data Clients & Ingestion (`epo` / `uspto`)

When building patent-oriented or mixed technical knowledge bases, you can use the standalone `epo` / `uspto` CLIs or ingest EPO publications directly into an OKF wiki.

### EPO OPS / EPS

Set EPO OPS credentials in `.secrets/ops_credentials.json` (or `EPO_OPS_CONSUMER_KEY` / `EPO_OPS_CONSUMER_SECRET`), then:

```bash
uv run epo check                                 # OPS credential resolution (no network)
uv run epo token                                 # acquire/refresh bearer token once
uv run epo search 'pa="EXAMPLE CORP"' --end 25
uv run epo biblio WO9999999A1
uv run epo eps-info EP9999999B1
uv run okf ingest-epo EP9999999B1 --wiki mywiki
```

See [docs/epo_api.md](docs/epo_api.md) for details.

### USPTO (US Patents)

USPTO uses the Open Data Portal API and requires a free API key (<https://data.uspto.gov/apikey>). Set `USPTO_API_KEY` or `.secrets/uspto_credentials.json`, then:

```bash
uv run uspto check                               # ODP API key resolution (no network)
uv run uspto search 'graphene' --limit 10
uv run uspto metadata 18999999

# download + parse (ODP files need the key; public URLs do not)
uv run uspto download "<ODP file URL>" -o data/external/uspto_raw/
uv run uspto parse data/external/uspto_raw/<file>.xml --claims
uv run uspto parse <weekly>.xml --stream   # iterate multi-doc files
uv run uspto parse <weekly>.zip            # parse a downloaded zip (no key)
uv run uspto extract <weekly>.zip -o <dir> # safe unzip (traversal rejected)

# year-level bulk (weekly products => all files whose data range is that year)
uv run uspto product PTGRXML --year 2024
uv run uspto year PTGRXML 2024 -o data/external/uspto/2024 --dry-run
uv run uspto year PTGRXML 2024 -o data/external/uspto/2024
```

See [docs/uspto_api.md](docs/uspto_api.md) for details.

## Fair Use, Provenance & Security Notes

1. **No credentials needed for core KB workflows.** Knowledge bases grounded in academic papers (`arXiv`, Crossref `DOI`), Web URLs, local files (`okf verify-source --file`), or operational records (`ops-record`) work without API keys. `okf verify-source` uses polite request spacing (`OKF_VERIFY_RATE_STATE`, or `--sleep` / `--no-rate-state`) and caches verified snapshots under `<kb>/evidence/` (or `data/external/source_verify` by default).
2. **Credentials stay out of Git.** Place EPO OPS credentials in `.secrets/ops_credentials.json` (or `EPO_OPS_CONSUMER_KEY` / `EPO_OPS_CONSUMER_SECRET`) and USPTO ODP keys in `.secrets/uspto_credentials.json` (or `USPTO_API_KEY`). Both `.secrets/` and `data/external/` are gitignored and blocked by CI guards.
3. **Cache-first & rate-limited by default.** Minimum 3 s spacing between EPO OPS requests is shared across processes (`data/external/ops_rate_state.json`, override with `EPO_OPS_RATE_STATE`), search windows are capped at 25 results (`MAX_SEARCH_RESULTS`), and responses are served from the local disk cache before any network call.
4. **Requirements.** Python **3.12 or newer** (tested on 3.12, 3.13, and 3.14). Optional features (e.g. PDF text extraction) are available via extras (`--extra pdf`).

## Quick Start without `uv` (Standard Library `python`)

```bash
export PYTHONPATH=src
python3 -m okf_kb_agent.wiki.cli validate examples/wiki
python3 -m okf_kb_agent.wiki.cli search examples/wiki "progressive disclosure"
python3 -m okf_kb_agent.epo check
python3 -m okf_kb_agent.epo token

python3 - <<'PY'
from okf_kb_agent.epo import OpsClient, EpsClient
ops = OpsClient()
print(ops.search('pa="EXAMPLE CORP" and ti="atomiz"').total_count)
eps = EpsClient()
print(eps.info("EP9999999B1")["date_publ"])
PY
```
