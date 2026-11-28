"""Tests for OKF v0.3 §11.2 consumer tolerance (unit U5)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from okf_kb_agent.wiki.claims import extract_claims, extract_claims_from_note
from okf_kb_agent.wiki.export import export_kb
from okf_kb_agent.wiki.model import iter_concepts, load_concept
from okf_kb_agent.wiki.search import LocalSearchBackend
from okf_kb_agent.wiki.tooling import dispatch_tool, wiki_stats


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ConsumerToleranceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        # 1. Valid concept with one valid v0.3 source AND one resource-less entry
        write(
            self.root,
            "concepts/good.md",
            "---\n"
            "type: Concept\n"
            "title: Good Concept\n"
            "basis: external\n"
            "sources:\n"
            "  - id: missing-resource-entry\n"
            "    title: Should Be Ignored\n"
            "  - id: arxiv-2406.06484\n"
            "    resource: https://arxiv.org/abs/2406.06484\n"
            "    x-okfkb-kind: preprint\n"
            "---\n"
            "# Good Concept\n\n"
            "Thermal conductivity is 285 W/mK.\n",
        )
        # 2. Malformed frontmatter file
        write(
            self.root,
            "concepts/broken.md",
            "not valid yaml frontmatter at all\n# Broken\n",
        )

    def test_iter_concepts_skips_broken_and_records_errors(self):
        errors: list[tuple[str, str]] = []
        concepts = iter_concepts(self.root, errors=errors)
        self.assertEqual([c.rel for c in concepts], ["concepts/good.md"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], "concepts/broken.md")

    def test_resourceless_source_entry_ignored_by_model_and_claims(self):
        concept = load_concept(self.root / "concepts/good.md", self.root)
        self.assertEqual(len(concept.sources), 1)
        self.assertEqual(concept.sources[0]["id"], "arxiv-2406.06484")
        self.assertEqual(len(concept.source_records), 1)

        note_claims = extract_claims_from_note(
            self.root / "concepts/good.md", self.root
        )
        self.assertEqual(len(note_claims), 1)
        self.assertEqual(len(note_claims[0].sources), 1)
        self.assertEqual(note_claims[0].sources[0]["id"], "arxiv-2406.06484")

    def test_claims_extraction_survives_broken_frontmatter(self):
        broken_claims = extract_claims_from_note(
            self.root / "concepts/broken.md", self.root
        )
        self.assertEqual(broken_claims, [])

        result = extract_claims(self.root)
        self.assertEqual(result.total_claims, 1)
        self.assertEqual(result.skipped_files, 1)
        self.assertEqual(len(result.parse_errors), 1)
        self.assertEqual(result.parse_errors[0]["rel"], "concepts/broken.md")

    def test_search_and_stats_survive_broken_frontmatter_and_surface_skipped(self):
        backend = LocalSearchBackend(self.root)
        hits = backend.search("conductivity")
        self.assertEqual([h.node for h in hits], ["concepts/good.md"])
        self.assertEqual(backend.skipped_files, 1)

        # Also via MCP dispatcher
        mcp_hits = dispatch_tool("okf_search", {"query": "conductivity"}, root=self.root)
        self.assertEqual(len(mcp_hits), 1)

        stats = wiki_stats(self.root)
        self.assertEqual(stats["concept_count"], 1)
        self.assertEqual(stats["skipped_files"], 1)
        self.assertEqual(len(stats["parse_errors"]), 1)
        self.assertEqual(stats["parse_errors"][0]["rel"], "concepts/broken.md")

    def test_export_survives_broken_frontmatter_and_resourceless_source(self):
        res = export_kb(self.root, cache_dirs=[], format_version=2)
        by_slug = {c["slug"]: c for c in res["concepts"]}
        self.assertIn("good", by_slug)
        self.assertEqual(by_slug["good"]["paper_ids"], ["arXiv:2406.06484"])
        self.assertEqual(len(by_slug["good"]["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
