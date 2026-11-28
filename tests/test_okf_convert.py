"""Tests for OKF v0.3 deterministic converter (unit U3)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from okf_kb_agent.wiki.cli import main
from okf_kb_agent.wiki.convert import (
    convert_source_string,
    convert_wiki_v03,
    verify_entry_lossless,
)
from okf_kb_agent.wiki.frontmatter import parse_frontmatter


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ConvertSourceUnitTests(unittest.TestCase):
    def test_arxiv_preprint_with_all_attributes(self):
        raw = (
            "preprint:arXiv:2406.06484 "
            "issued=2024-06-10 retrieved=2026-11-26 via=arxiv genre=paper"
        )
        entry, is_raw = convert_source_string(raw)
        self.assertFalse(is_raw)
        self.assertEqual(
            entry,
            {
                "id": "arxiv-2406.06484",
                "resource": "https://arxiv.org/abs/2406.06484",
                "x-okfkb-kind": "preprint",
                "x-okfkb-issued": "2024-06-10",
                "x-okfkb-retrieved": "2026-11-26",
                "x-okfkb-via": "arxiv",
                "x-okfkb-genre": "paper",
            },
        )
        self.assertEqual(
            list(entry.keys()),
            [
                "id",
                "resource",
                "x-okfkb-kind",
                "x-okfkb-issued",
                "x-okfkb-retrieved",
                "x-okfkb-via",
                "x-okfkb-genre",
            ],
        )
        self.assertTrue(verify_entry_lossless(raw, entry))

    def test_doi_with_parentheses_and_semicolons(self):
        raw = "paper:10.1016/s1002-0071(12)60029-x;1 via=crossref"
        entry, is_raw = convert_source_string(raw)
        self.assertFalse(is_raw)
        self.assertEqual(entry["id"], "doi-10.1016-s1002-0071-12-60029-x-1")
        self.assertEqual(
            entry["resource"],
            "https://doi.org/10.1016/s1002-0071(12)60029-x;1",
        )
        self.assertEqual(entry["x-okfkb-kind"], "paper")
        self.assertEqual(entry["x-okfkb-via"], "crossref")
        self.assertTrue(verify_entry_lossless(raw, entry))

    def test_web_url_with_query_string_uses_sha256_suffix(self):
        raw1 = "web:https://www.shinetsusilicones.com/tim.aspx?ID=G-776 retrieved=2026-11-21 via=web"
        raw2 = "web:https://www.shinetsusilicones.com/tim.aspx?ID=G-777 retrieved=2026-11-21 via=web"
        e1, _ = convert_source_string(raw1)
        e2, _ = convert_source_string(raw2)
        self.assertTrue(e1["id"].startswith("web-"))
        self.assertNotEqual(e1["id"], e2["id"])
        self.assertEqual(
            e1["resource"],
            "https://www.shinetsusilicones.com/tim.aspx?ID=G-776",
        )
        self.assertTrue(verify_entry_lossless(raw1, e1))

    def test_ops_record_and_local_file(self):
        ops_raw = "ops-record:~/TOOLS.md#Antigravity-CLI snapshot=tools-md-antigravity-cli"
        ops_entry, is_raw = convert_source_string(ops_raw)
        self.assertFalse(is_raw)
        self.assertEqual(ops_entry["id"], "tools-md-antigravity-cli")
        self.assertEqual(ops_entry["resource"], "~/TOOLS.md#Antigravity-CLI")
        self.assertEqual(ops_entry["x-okfkb-kind"], "ops-record")
        self.assertEqual(ops_entry["x-okfkb-snapshot"], "tools-md-antigravity-cli")
        self.assertTrue(verify_entry_lossless(ops_raw, ops_entry))

        local_raw = (
            "local-file:notes.txt retrieved=2026-11-14 "
            "via=local-file snapshot=local_0123456789abcdef"
        )
        local_entry, is_raw = convert_source_string(local_raw)
        self.assertFalse(is_raw)
        self.assertEqual(local_entry["id"], "local_0123456789abcdef")
        self.assertEqual(local_entry["resource"], "notes.txt")
        self.assertEqual(local_entry["x-okfkb-kind"], "local-file")
        self.assertTrue(verify_entry_lossless(local_raw, local_entry))

    def test_unknown_extension_attrs_preserved_in_first_seen_order(self):
        raw = "web:https://example.com via=web custom_b=2 custom_a=1"
        entry, _ = convert_source_string(raw)
        self.assertEqual(entry["x-okfkb-custom_b"], "2")
        self.assertEqual(entry["x-okfkb-custom_a"], "1")
        keys = list(entry.keys())
        self.assertLess(keys.index("x-okfkb-custom_b"), keys.index("x-okfkb-custom_a"))
        self.assertTrue(verify_entry_lossless(raw, entry))

    def test_unparseable_string_falls_back_to_raw(self):
        raw = "unparseable-source-without-colon"
        entry, is_raw = convert_source_string(raw)
        self.assertTrue(is_raw)
        self.assertEqual(entry, {"resource": raw, "x-okfkb-raw": raw})
        self.assertTrue(verify_entry_lossless(raw, entry))


class ConvertWikiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "kb"
        self.root.mkdir()

    def test_dry_run_default_and_write_patent_collision_and_generated_untouched(self):
        body = "# AlN\n\nBody text must not change.\n"
        note_text = (
            "---\n"
            "type: Concept\n"
            "title: AlN\n"
            "basis: external\n"
            'generated: {by: "okf-glm-runner/1", at: "2026-11-20T00:00:00Z"}\n'
            "sources:\n"
            '  - "patent-biblio:EP4668330A1 via=epo-ops"\n'
            '  - "patent-claims:EP4668330A1 via=epo-ops"\n'
            '  - "web:https://example.com/a via=web"\n'
            '  - "web:https://example.com/a via=mirror"\n'
            '  - "broken-raw-source"\n'
            'verified_at: "2026-11-26"\n'
            "---\n"
            + body
        )
        note_path = write(self.root, "concepts/aln.md", note_text)

        # Default is dry-run: writes nothing
        dry_report = convert_wiki_v03(self.root)
        self.assertFalse(dry_report.written)
        self.assertEqual(note_path.read_text(encoding="utf-8"), note_text)
        self.assertEqual(dry_report.converted_sources, 5)
        self.assertEqual(len(dry_report.raw_preserved), 1)
        self.assertEqual(len(dry_report.id_collisions), 1)
        self.assertEqual(dry_report.id_collisions[0]["resolved_id"], "web-example.com-a-2")
        self.assertEqual(dry_report.lossless_errors, [])

        # Explicit write=True applies changes
        write_report = convert_wiki_v03(self.root, write=True)
        self.assertTrue(write_report.written)
        self.assertEqual(write_report.files_changed, 1)

        meta, out_body = parse_frontmatter(note_path.read_text(encoding="utf-8"))
        self.assertEqual(out_body, body)
        self.assertEqual(
            meta["generated"],
            {"by": "okf-glm-runner/1", "at": "2026-11-20T00:00:00Z"},
        )
        self.assertNotIn("verified_at", meta)
        self.assertEqual(meta["x-okfkb-verified-at"], "2026-11-26")

        ids = [item.get("id") for item in meta["sources"]]
        self.assertEqual(
            ids,
            [
                "patent-biblio-ep4668330a1",
                "patent-claims-ep4668330a1",
                "web-example.com-a",
                "web-example.com-a-2",
                None,
            ],
        )
        self.assertEqual(meta["sources"][4]["x-okfkb-raw"], "broken-raw-source")

        # Idempotent: second run produces zero diff
        second_report = convert_wiki_v03(self.root, write=True)
        self.assertEqual(second_report.files_changed, 0)
        self.assertEqual(second_report.converted_sources, 0)

    def test_verified_map_injects_verified_and_drops_verified_at(self):
        write(
            self.root,
            "concepts/mapped.md",
            "---\n"
            "type: Concept\n"
            "basis: external\n"
            'sources: ["preprint:arXiv:2406.06484 via=arxiv"]\n'
            'verified_at: "2026-11-26"\n'
            "---\n"
            "# Mapped\n",
        )
        write(
            self.root,
            "concepts/unmapped.md",
            "---\n"
            "type: Concept\n"
            "basis: external\n"
            'sources: ["preprint:arXiv:2401.12345 via=arxiv"]\n'
            'verified_at: "2026-11-25"\n'
            "---\n"
            "# Unmapped\n",
        )
        vmap_path = Path(self.tmp.name) / "verified_map.json"
        vmap_path.write_text(
            json.dumps(
                {
                    "concepts/mapped.md": [
                        {"by": "process:okf-morning-audit", "at": "2026-11-26"}
                    ]
                }
            ),
            encoding="utf-8",
        )

        report = convert_wiki_v03(
            self.root, write=True, verified_map_path=vmap_path
        )
        self.assertEqual(report.verified_injected, 1)
        self.assertEqual(report.verified_fallback, 1)

        mapped_meta, _ = parse_frontmatter(
            (self.root / "concepts/mapped.md").read_text(encoding="utf-8")
        )
        self.assertNotIn("verified_at", mapped_meta)
        self.assertNotIn("x-okfkb-verified-at", mapped_meta)
        self.assertEqual(
            mapped_meta["verified"],
            [{"by": "process:okf-morning-audit", "at": "2026-11-26"}],
        )

        unmapped_meta, _ = parse_frontmatter(
            (self.root / "concepts/unmapped.md").read_text(encoding="utf-8")
        )
        self.assertNotIn("verified_at", unmapped_meta)
        self.assertNotIn("verified", unmapped_meta)
        self.assertEqual(unmapped_meta["x-okfkb-verified-at"], "2026-11-25")

    def test_cli_convert_v03_dry_run_and_write_json(self):
        write(
            self.root,
            "concepts/a.md",
            "---\n"
            "type: Concept\n"
            "basis: external\n"
            'sources: ["paper:10.1109/icept.2005.1564720 via=crossref"]\n'
            'verified_at: "2026-11-26"\n'
            "---\n"
            "# A\n",
        )
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["convert-v03", str(self.root), "--check-lossless", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["written"])
        self.assertEqual(payload["converted_sources"], 1)
        self.assertEqual(payload["lossless_errors"], [])

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = main(["convert-v03", str(self.root), "--write", "--json"])
        self.assertEqual(code2, 0)
        payload2 = json.loads(buf2.getvalue())
        self.assertTrue(payload2["written"])
        self.assertEqual(payload2["files_changed"], 1)

    def test_malformed_frontmatter_recorded_in_skipped_files_and_parse_errors(self):
        write(
            self.root,
            "concepts/broken.md",
            "not frontmatter at all\n# Broken\n",
        )
        report = convert_wiki_v03(self.root)
        self.assertEqual(report.skipped_files, 1)
        self.assertEqual(len(report.parse_errors), 1)
        self.assertEqual(report.parse_errors[0]["rel"], "concepts/broken.md")
        self.assertIn("skipped: 1", report.format_text())
        self.assertIn("PARSE_ERROR: concepts/broken.md", report.format_text())
        self.assertEqual(report.as_dict()["skipped_files"], 1)

    def test_invalid_verified_map_event_raises_value_error(self):
        write(
            self.root,
            "concepts/a.md",
            "---\ntype: Concept\n---\n# A\n",
        )
        vmap_path = Path(self.tmp.name) / "bad_vmap.json"
        vmap_path.write_text(
            json.dumps({"concepts/a.md": [{"by": "only-by"}]}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            convert_wiki_v03(self.root, verified_map_path=vmap_path)

    def test_verified_map_merges_with_existing_verified_and_is_idempotent(self):
        write(
            self.root,
            "concepts/existing.md",
            "---\n"
            "type: Concept\n"
            "basis: external\n"
            "sources:\n"
            "  - id: arxiv-2406.06484\n"
            "    resource: https://arxiv.org/abs/2406.06484\n"
            "    x-okfkb-kind: preprint\n"
            "verified:\n"
            "  - by: human:chottokun\n"
            '    at: "2026-11-27"\n'
            'verified_at: "2026-11-26"\n'
            "---\n"
            "# Existing\n",
        )
        vmap_path = Path(self.tmp.name) / "merge_vmap.json"
        vmap_path.write_text(
            json.dumps({
                "concepts/existing.md": [
                    {"by": "process:okf-morning-audit", "at": "2026-11-26"},
                ]
            }),
            encoding="utf-8",
        )
        first = convert_wiki_v03(self.root, write=True, verified_map_path=vmap_path)
        self.assertEqual(first.verified_injected, 1)
        meta, _ = parse_frontmatter(
            (self.root / "concepts/existing.md").read_text(encoding="utf-8")
        )
        self.assertEqual(
            meta["verified"],
            [
                {"by": "human:chottokun", "at": "2026-11-27"},
                {"by": "process:okf-morning-audit", "at": "2026-11-26"},
            ],
        )
        self.assertNotIn("verified_at", meta)

        second = convert_wiki_v03(self.root, write=True, verified_map_path=vmap_path)
        self.assertEqual(second.files_changed, 0)
        self.assertEqual(second.verified_injected, 0)


class ConvertTagNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "wiki"
        self.root.mkdir()
        write(self.root, "index.md", "# Index\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_opt_in_default_leaves_tags_untouched(self):
        write(
            self.root,
            "concepts/a.md",
            (
                "---\n"
                "type: Concept\n"
                "tags: [strand:agents, DeepSeek-V3.2, plain]\n"
                "basis: external\n"
                "---\n"
                "# A\n"
            ),
        )
        rep = convert_wiki_v03(self.root, write=True)
        self.assertEqual(rep.tags_normalized, 0)
        self.assertEqual(rep.files_changed, 0)
        meta, _ = parse_frontmatter(
            (self.root / "concepts/a.md").read_text(encoding="utf-8")
        )
        self.assertEqual(meta["tags"], ["strand:agents", "DeepSeek-V3.2", "plain"])

    def test_normalize_tags_rules_collision_and_idempotency(self):
        body_a = "# DeepSeek-V3.2\n\nUses DeepSeek-V3.2 and 2.5D packaging.\n"
        write(
            self.root,
            "concepts/a.md",
            (
                "---\n"
                "type: Concept\n"
                "tags: [strand:agents, DeepSeek-V3.2, 2.5D, foo.bar, untouched]\n"
                "basis: external\n"
                "---\n"
                + body_a
            ),
        )
        write(
            self.root,
            "concepts/b.md",
            (
                "---\n"
                "type: Concept\n"
                "tags: [foo-bar, strand:inference]\n"
                "basis: external\n"
                "---\n"
                "# B\n"
            ),
        )

        # Dry-run reports changes and collisions without modifying files
        dry = convert_wiki_v03(self.root, write=False, normalize_tags=True)
        self.assertFalse(dry.written)
        self.assertEqual(dry.tags_normalized, 4)
        self.assertEqual(
            dry.tag_collisions,
            [{"normalized": "foo-bar", "originals": ["foo-bar", "foo.bar"]}],
        )
        meta_a_dry, _ = parse_frontmatter(
            (self.root / "concepts/a.md").read_text(encoding="utf-8")
        )
        self.assertIn("strand:agents", meta_a_dry["tags"])

        # Apply via CLI --normalize-tags --write --json
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["convert-v03", str(self.root), "--normalize-tags", "--write", "--json"])
        self.assertEqual(rc, 0)
        applied = json.loads(buf.getvalue())
        self.assertTrue(applied["written"])
        self.assertEqual(applied["tags_normalized"], 4)
        self.assertEqual(
            applied["tag_collisions"],
            [{"normalized": "foo-bar", "originals": ["foo-bar", "foo.bar"]}],
        )

        meta_a, parsed_body_a = parse_frontmatter(
            (self.root / "concepts/a.md").read_text(encoding="utf-8")
        )
        self.assertEqual(
            meta_a["tags"],
            ["strand/agents", "DeepSeek-V3-2", "2-5D", "foo.bar", "untouched"],
        )
        self.assertEqual(parsed_body_a, body_a)

        meta_b, _ = parse_frontmatter(
            (self.root / "concepts/b.md").read_text(encoding="utf-8")
        )
        self.assertEqual(meta_b["tags"], ["foo-bar", "strand/inference"])

        # Idempotent second --write run
        second = convert_wiki_v03(self.root, write=True, normalize_tags=True)
        self.assertEqual(second.files_changed, 0)
        self.assertEqual(second.tags_normalized, 0)
        self.assertEqual(
            second.tag_collisions,
            [{"normalized": "foo-bar", "originals": ["foo-bar", "foo.bar"]}],
        )


if __name__ == "__main__":
    unittest.main()
