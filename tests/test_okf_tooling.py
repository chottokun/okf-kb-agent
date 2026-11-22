"""Tests for the stable JSON tool contracts and dispatcher."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from okf_kb_agent.wiki.cli import main as cli_main
from okf_kb_agent.wiki.tooling import (
    TOOL_SPECS,
    ToolError,
    dispatch_tool,
    wiki_stats,
)
from okf_kb_agent.wiki.validate import validate_wiki
from okf_kb_agent.wiki.verify import snapshot_key_for_url


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def node(meta: str, body: str = "# Note\n") -> str:
    return f"---\n{meta}---\n{body}"


class ToolingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.wiki = self.base / "wiki"
        write(self.wiki, "index.md", "# Index\n")
        write(self.wiki, "a.md", node(
            "type: Note\ntitle: Amorphous alloy\n",
            "# Amorphous alloy\nSee [b](b.md).\n"))
        write(self.wiki, "b.md", node(
            "type: Workflow\ntitle: Casting\n", "# Casting\n"))

    def test_specs_are_unique_and_have_required_schema_fields(self):
        names = [spec["name"] for spec in TOOL_SPECS]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("okf_context", names)
        for spec in TOOL_SPECS:
            with self.subTest(name=spec["name"]):
                self.assertTrue(spec["description"])
                schema = spec["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertIn("wiki", schema["required"])
                if spec["name"] in ("okf_search", "okf_context"):
                    self.assertIn("query", schema["required"])
                self.assertFalse(schema["additionalProperties"])

    def test_search_and_stats(self):
        hits = dispatch_tool(
            "okf_search", {"wiki": "wiki", "query": "amorphous"},
            root=self.base)
        self.assertEqual(hits[0]["node"], "a.md")
        stats = dispatch_tool("okf_stats", {"wiki": "wiki"}, root=self.base)
        self.assertEqual(stats["concept_count"], 2)
        self.assertEqual(stats["links"], 1)
        self.assertEqual(stats["pattern"], "A")
        self.assertEqual(stats["basis"], {"external": 0, "model": 0, "mixed": 0, "undeclared": 2})

    def test_wiki_stats_counts_all_four_basis_buckets(self):
        write(self.base / "wiki2", "index.md", "# Index\n")
        write(self.base / "wiki2", "ext.md", node("type: Patent\nbasis: external\n"))
        write(self.base / "wiki2", "mod.md", node("type: Concept\nbasis: model\n"))
        write(self.base / "wiki2", "mix.md", node("type: Concept\nbasis: mixed\n"))
        write(self.base / "wiki2", "und.md", node("type: Note\n"))
        stats = dispatch_tool("okf_stats", {"wiki": "wiki2"}, root=self.base)
        self.assertEqual(stats["basis"], {
            "external": 1,
            "model": 1,
            "mixed": 1,
            "undeclared": 1,
        })

    def test_context_traverse_and_validate(self):
        bundle = dispatch_tool(
            "okf_context",
            {"wiki": "wiki", "query": "amorphous", "max_nodes": 3},
            root=self.base,
        )
        self.assertIn("nodes", bundle)
        hits = dispatch_tool(
            "okf_traverse", {"wiki": "wiki", "seed": "a"},
            root=self.base,
        )
        self.assertEqual(hits[0]["node"], "b.md")
        report = dispatch_tool(
            "okf_validate", {"wiki": "wiki"}, root=self.base)
        self.assertTrue(report["ok"])

    def test_index_check_then_write(self):
        before = dispatch_tool(
            "okf_index", {"wiki": "wiki", "check": True}, root=self.base)
        self.assertFalse(before["ok"])
        self.assertIn("index.md", before["stale"])
        written = dispatch_tool(
            "okf_index", {"wiki": "wiki"}, root=self.base)
        self.assertTrue(written["ok"])
        after = dispatch_tool(
            "okf_index", {"wiki": "wiki", "check": True}, root=self.base)
        self.assertTrue(after["ok"])

    def test_root_escape_is_rejected(self):
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_stats", {"wiki": "../outside"}, root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_stats", {"wiki": "/"}, root=self.base)

    def test_auxiliary_path_escape_is_rejected(self):
        # db_path escapes root
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_search",
                {"wiki": "wiki", "query": "amorphous", "backend": "sqlite",
                 "db_path": "../outside.sqlite3"},
                root=self.base)
        self.assertIn("db_path escapes the allowed root", str(ctx.exception))
        self.assertFalse((self.base.parent / "outside.sqlite3").exists())

        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_context",
                {"wiki": "wiki", "query": "amorphous", "backend": "sqlite",
                 "db_path": "/tmp/escape.sqlite3"},
                root=self.base)
        self.assertIn("db_path escapes the allowed root", str(ctx.exception))

        # db_path is a directory
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_search",
                {"wiki": "wiki", "query": "amorphous", "backend": "sqlite",
                 "db_path": "wiki"},
                root=self.base)
        self.assertIn("db_path must not be a directory", str(ctx.exception))

        # cache_dir escapes root
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_ingest_epo",
                {"wiki": "wiki", "publication": "EP1000000A1",
                 "cache_dir": "../outside_cache"},
                root=self.base)
        self.assertIn("cache_dir escapes the allowed root", str(ctx.exception))

        # credentials escapes root
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_ingest_epo",
                {"wiki": "wiki", "publication": "EP1000000A1",
                 "credentials": "../outside_creds.json"},
                root=self.base)
        self.assertIn("credentials escapes the allowed root", str(ctx.exception))

        # credentials file does not exist
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_ingest_epo",
                {"wiki": "wiki", "publication": "EP1000000A1",
                 "credentials": "missing_creds.json"},
                root=self.base)
        self.assertIn("credentials file does not exist", str(ctx.exception))

        # cache_dir must be a directory
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_ingest_epo",
                {"wiki": "wiki", "publication": "EP1000000A1",
                 "cache_dir": "wiki/a.md"},
                root=self.base)
        self.assertIn("cache_dir must be a directory", str(ctx.exception))

        # empty or whitespace path strings
        for key in ("db_path",):
            with self.assertRaises(ToolError) as ctx:
                dispatch_tool(
                    "okf_search",
                    {"wiki": "wiki", "query": "amorphous", key: "  "},
                    root=self.base)
            self.assertIn(f"{key} must be a non-empty path", str(ctx.exception))

        # valid confined db_path works
        custom_db = "wiki/.okf/custom.sqlite3"
        hits = dispatch_tool(
            "okf_search",
            {"wiki": "wiki", "query": "amorphous", "backend": "sqlite",
             "db_path": custom_db},
            root=self.base)
        self.assertTrue(hits)
        self.assertTrue((self.base / custom_db).exists())

    def test_bad_arguments_are_rejected(self):
        with self.assertRaises(ToolError):
            dispatch_tool("okf_nope", {"wiki": "wiki"}, root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search", {"wiki": "wiki", "query": "x", "limit": 0},
                root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_traverse", {"wiki": "wiki", "seed": "missing"},
                root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_ingest_epo", {"wiki": "wiki"}, root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_ingest_epo",
                {"wiki": "wiki", "publication": "EP1", "query": "x"},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_index", {"wiki": "wiki", "check": "false"},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_traverse",
                {"wiki": "wiki", "seed": "a", "scopes": ["bogus"]},
                root=self.base,
            )


    def test_synonym_expansion_and_qdrant_argument_validation(self):
        write(self.wiki, "synonyms.json", json.dumps([
            ["amorphous alloy", "metallic glass"],
        ]))
        baseline = dispatch_tool(
            "okf_search",
            {"wiki": "wiki", "query": "metallic glass"},
            root=self.base,
        )
        self.assertEqual(baseline, [])
        expanded = dispatch_tool(
            "okf_search",
            {"wiki": "wiki", "query": "metallic glass",
             "expand": True},
            root=self.base,
        )
        self.assertEqual(expanded[0]["node"], "a.md")
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "wiki", "query": "x", "backend": "qdrant"},
                root=self.base,
            )
        schema = next(spec for spec in TOOL_SPECS
                      if spec["name"] == "okf_search")["inputSchema"]
        self.assertIn("qdrant", schema["properties"]["backend"]["enum"])
        self.assertIn("expand", schema["properties"])
        self.assertNotIn("expand_synonyms", schema["properties"])
        context_schema = next(spec for spec in TOOL_SPECS
                              if spec["name"] == "okf_context")["inputSchema"]
        self.assertIn("expand", context_schema["properties"])
        self.assertNotIn("expand_synonyms", context_schema["properties"])

    def test_wiki_stats_matches_dispatcher(self):
        direct = wiki_stats(self.wiki)
        via_tool = dispatch_tool(
            "okf_stats", {"wiki": "wiki"}, root=self.base)
        self.assertEqual(direct, via_tool)

    def _run_cli_json(self, *args: str):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main([str(arg) for arg in args])
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else None, err.getvalue()

    def _spec(self, name: str) -> dict:
        return next(spec for spec in TOOL_SPECS if spec["name"] == name)

    # -- U1: okf_candidate_check -------------------------------------------

    def test_candidate_check_schema_contract(self):
        spec = self._spec("okf_candidate_check")
        schema = spec["inputSchema"]
        self.assertEqual(schema["required"], ["wiki"])
        self.assertFalse(schema["additionalProperties"])
        props = schema["properties"]
        self.assertEqual(set(props), {"wiki", "candidates", "proposal"})
        self.assertEqual(props["candidates"]["type"], "array")
        self.assertEqual(props["candidates"]["items"]["type"], "string")
        self.assertEqual(props["proposal"]["type"], "string")
        self.assertNotIn("mutually exclusive", props["candidates"]["description"].lower())
        self.assertNotIn("mutually exclusive", props["proposal"]["description"].lower())
        self.assertNotIn("fail_on", props)

    def test_candidate_check_candidates_proposal_and_cli_parity(self):
        cand_wiki = self.base / "cand_wiki"
        write(cand_wiki, "index.md", "# Index\n")
        write(
            cand_wiki,
            "concepts/spray-cooling.md",
            node(
                "type: Concept\ntitle: 'Spray Cooling'\n"
                "tags: [spray-cooling, dielectric-fluid]\n",
                "# Spray Cooling\nUses dielectric fluid droplets.\n",
            ),
        )
        write(
            cand_wiki,
            "concepts/interposer.md",
            node("type: Concept\ntitle: 'Interposer'\ntags: [interposer]\n"),
        )
        write(
            cand_wiki,
            "synonyms.json",
            json.dumps({
                "groups": [
                    ["tim", "thermal-interface-materials"],
                    ["spray-cooling", "dielectric-fluid"],
                ],
                "manual_groups": [["tim", "thermal-interface-materials"]],
                "generated_groups": [["spray-cooling", "dielectric-fluid"]],
            }),
        )

        # Direct candidates: name_occupied, manual synonym, generated synonym + tag_on, clean
        res = dispatch_tool(
            "okf_candidate_check",
            {
                "wiki": "cand_wiki",
                "candidates": ["interposer", "tim", "dielectric-fluid", "novel-slug"],
            },
            root=self.base,
        )
        dumped = json.dumps(res)
        for forbidden in ('"status"', '"severity"', '"verdict"', '"weight"', '"hard_collision"'):
            self.assertNotIn(forbidden, dumped)

        by_slug = {c["slug"]: c for c in res["candidates"]}
        self.assertIsNotNone(by_slug["interposer"]["relations"]["name_occupied"])
        self.assertEqual(by_slug["tim"]["relations"]["synonyms"][0]["kind"], "manual")
        self.assertEqual(by_slug["dielectric-fluid"]["relations"]["synonyms"][0]["kind"], "generated")
        self.assertEqual(by_slug["dielectric-fluid"]["relations"]["tag_on"][0]["provenance"], "free")
        self.assertIsNone(by_slug["novel-slug"]["relations"]["name_occupied"])
        self.assertEqual(by_slug["novel-slug"]["relations"]["synonyms"], [])
        self.assertEqual(by_slug["novel-slug"]["relations"]["tag_on"], [])

        code, cli_res, _ = self._run_cli_json(
            "candidate-check", str(cand_wiki),
            "interposer", "tim", "dielectric-fluid", "novel-slug", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(res, cli_res)

        # Proposal check with verbatim evidence and taxonomy-gap
        proposal = write(
            cand_wiki,
            "proposal.md",
            """### Candidate Proposal Pool
1. **`dielectric-fluid`** — 絶縁性流体 [`established`]
   - **(a) Adjacency**: Extends spray cooling.
   - **(b) Primary-Source Emergence**: "dielectric fluid droplets" in concepts/spray-cooling.md
   - **(c) Deduplication**: distinct.
2. **`near-junction-cooling`** — 近接冷却 [`niche`]
   - **(a) Adjacency**: Extends cooling.
   - **(b) Primary-Source Emergence**: taxonomy-gap
   - **(c) Deduplication**: distinct.
""",
        )
        prop_res = dispatch_tool(
            "okf_candidate_check",
            {"wiki": "cand_wiki", "proposal": "cand_wiki/proposal.md"},
            root=self.base,
        )
        prop_by_slug = {c["slug"]: c for c in prop_res["candidates"]}
        self.assertTrue(prop_by_slug["dielectric-fluid"]["verbatim_check"]["verbatim_found"])
        self.assertEqual(prop_by_slug["near-junction-cooling"]["verbatim_check"]["parse_status"], "taxonomy-gap")
        self.assertIsNone(prop_by_slug["near-junction-cooling"]["verbatim_check"]["verbatim_found"])

        code_p, cli_prop_res, _ = self._run_cli_json(
            "candidate-check", str(cand_wiki), "--proposal", str(proposal), "--json",
        )
        self.assertEqual(code_p, 0)
        self.assertEqual(prop_res, cli_prop_res)

    def test_candidate_check_missing_and_corrupt_synonyms_reported(self):
        no_syn = self.base / "no_syn_wiki"
        write(no_syn, "index.md", "# Index\n")
        write(no_syn, "concepts/a.md", node("type: Concept\ntitle: A\ntags: [a]\n"))
        res_missing = dispatch_tool(
            "okf_candidate_check",
            {"wiki": "no_syn_wiki", "candidates": ["b"]},
            root=self.base,
        )
        self.assertFalse(res_missing["inputs_status"]["synonyms_json_present"])
        self.assertIn("synonyms.json", res_missing["inputs_status"]["inputs_missing"])

        write(no_syn, "synonyms.json", "{broken")
        res_corrupt = dispatch_tool(
            "okf_candidate_check",
            {"wiki": "no_syn_wiki", "candidates": ["b"]},
            root=self.base,
        )
        self.assertTrue(res_corrupt["inputs_status"]["synonyms_json_present"])
        self.assertIsNotNone(res_corrupt["inputs_status"]["synonyms_json_parse_error"])

    def test_candidate_check_rejects_bad_arguments_and_escapes(self):
        prop = write(self.wiki, "proposal.md", "# Empty proposal\n")
        # Neither candidates nor proposal
        with self.assertRaises(ToolError):
            dispatch_tool("okf_candidate_check", {"wiki": "wiki"}, root=self.base)
        # Empty candidates without proposal
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_candidate_check",
                {"wiki": "wiki", "candidates": []},
                root=self.base,
            )
        # Bad candidates types / traversal
        for bad in ("not-a-list", [""], ["  "], [123], ["../a"], ["a/b"], ["a\\b"]):
            with self.assertRaises(ToolError):
                dispatch_tool(
                    "okf_candidate_check",
                    {"wiki": "wiki", "candidates": bad},
                    root=self.base,
                )

        # Escaping / missing / invalid proposal path (confined root inside self.base)
        confined = self.base / "confined_cand"
        c_wiki = confined / "wiki"
        write(c_wiki, "index.md", "# Index\n")
        write(c_wiki, "proposal.md", "# Proposal\n")
        outside_prop = self.base / "outside_proposal.md"
        outside_prop.write_text("# Outside\n", encoding="utf-8")
        for bad_prop in (
            "../outside_proposal.md",
            str(outside_prop),
            "/etc/passwd",
            "wiki/missing.md",
            "wiki",
            "   ",
        ):
            with self.assertRaises(ToolError):
                dispatch_tool(
                    "okf_candidate_check",
                    {"wiki": "wiki", "proposal": bad_prop},
                    root=confined,
                )
        self.assertTrue(prop.exists())

    def test_candidate_check_candidates_with_proposal_context(self):
        from okf_kb_agent.wiki.candidate import CandidateChecker

        confined = self.base / "combined_cand"
        cand_wiki = confined / "wiki"
        write(cand_wiki, "index.md", "# Index\n")
        write(
            cand_wiki,
            "concepts/interposer.md",
            node("type: Concept\ntitle: 'Interposer'\ntags: [interposer]\n"),
        )
        write(
            cand_wiki,
            "synonyms.json",
            json.dumps({"groups": [], "manual_groups": [], "generated_groups": []}),
        )
        proposal = write(
            cand_wiki,
            "proposal.md",
            (
                "### Candidate Proposal Pool\n"
                "1. **`other-slug`** — 別候補 [`niche`]\n"
                "   - **(b) Primary-Source Emergence**: taxonomy-gap\n"
            ),
        )

        res = dispatch_tool(
            "okf_candidate_check",
            {
                "wiki": "wiki",
                "candidates": ["interposer"],
                "proposal": "wiki/proposal.md",
            },
            root=confined,
        )
        self.assertEqual([c["slug"] for c in res["candidates"]], ["interposer"])
        self.assertIsNone(res["candidates"][0]["verbatim_check"])
        self.assertTrue(res["inputs_status"]["proposal_file_present"])
        self.assertEqual(
            res,
            CandidateChecker(cand_wiki)
            .check_candidates(["interposer"], proposal_path=proposal)
            .to_dict(),
        )

        # Escaping proposal is still rejected even when candidates is given
        outside_prop = self.base / "outside_combined_proposal.md"
        outside_prop.write_text("# Outside\n", encoding="utf-8")
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_candidate_check",
                {
                    "wiki": "wiki",
                    "candidates": ["interposer"],
                    "proposal": "../outside_combined_proposal.md",
                },
                root=confined,
            )

    # -- U2: okf_links -----------------------------------------------------

    def test_links_schema_contract(self):
        spec = self._spec("okf_links")
        schema = spec["inputSchema"]
        self.assertEqual(schema["required"], ["wiki"])
        self.assertFalse(schema["additionalProperties"])
        props = schema["properties"]
        self.assertEqual(set(props), {"wiki", "from", "direction", "include_admin"})
        self.assertEqual(props["from"]["type"], "array")
        self.assertEqual(props["from"]["items"]["type"], "string")
        self.assertEqual(props["direction"]["enum"], ["out", "in", "both"])
        self.assertEqual(props["direction"]["default"], "out")
        self.assertEqual(props["include_admin"]["type"], "boolean")
        self.assertFalse(props["include_admin"]["default"])

    def test_links_dispatch_and_cli_parity(self):
        lw = self.base / "links_wiki"
        write(lw, "index.md", "# Index\n")
        write(lw, "concepts/hub.md", node(
            "type: Concept\ntitle: Hub\n",
            "# Hub\nSee [leaf](leaf.md).\n",
        ))
        write(lw, "concepts/leaf.md", node(
            "type: Concept\ntitle: Leaf\n",
            "# Leaf\nDetails.\n",
        ))
        write(lw, "concepts/orphan.md", node(
            "type: Concept\ntitle: Orphan\n",
            "# Orphan\nUnlinked.\n",
        ))
        write(lw, "BUILDLOG.md", node(
            "type: Note\ntitle: Build Log\n",
            "# Build Log\nMentions [orphan](concepts/orphan.md).\n",
        ))

        # Default (include_admin=False): BUILDLOG.md excluded
        res_default = dispatch_tool("okf_links", {"wiki": "links_wiki"}, root=self.base)
        self.assertEqual(res_default["node_count"], 3)
        self.assertEqual([x["rel"] for x in res_default["isolated"]], ["concepts/orphan.md"])
        self.assertNotIn("seed_reachability", res_default)

        code, cli_default, _ = self._run_cli_json("links", str(lw), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(res_default, cli_default)

        # include_admin=True: BUILDLOG.md included, orphan masked
        res_admin = dispatch_tool(
            "okf_links", {"wiki": "links_wiki", "include_admin": True}, root=self.base,
        )
        self.assertEqual(res_admin["node_count"], 4)
        self.assertEqual(res_admin["isolated"], [])
        code_a, cli_admin, _ = self._run_cli_json(
            "links", str(lw), "--include-admin", "--json",
        )
        self.assertEqual(code_a, 0)
        self.assertEqual(res_admin, cli_admin)

        # from seeds with direction out / in / both + multiple seeds
        for direction in ("out", "in", "both"):
            res_dir = dispatch_tool(
                "okf_links",
                {"wiki": "links_wiki", "from": ["leaf"], "direction": direction},
                root=self.base,
            )
            code_d, cli_dir, _ = self._run_cli_json(
                "links", str(lw), "--from", "leaf", "--direction", direction, "--json",
            )
            self.assertEqual(code_d, 0)
            self.assertEqual(res_dir, cli_dir)

        res_multi = dispatch_tool(
            "okf_links",
            {"wiki": "links_wiki", "from": ["hub", "BUILDLOG"]},
            root=self.base,
        )
        code_m, cli_multi, _ = self._run_cli_json(
            "links", str(lw), "--from", "hub", "--from", "BUILDLOG", "--json",
        )
        self.assertEqual(code_m, 0)
        self.assertEqual(res_multi, cli_multi)
        self.assertEqual(res_multi["node_count"], 4)  # explicit admin seed kept

        # Empty from: [] behaves like omitted from
        res_empty_from = dispatch_tool(
            "okf_links", {"wiki": "links_wiki", "from": []}, root=self.base,
        )
        self.assertNotIn("seed_reachability", res_empty_from)
        self.assertEqual(res_empty_from, res_default)

    def test_links_rejects_bad_arguments(self):
        with self.assertRaises(ToolError):
            dispatch_tool("okf_links", {"wiki": "wiki", "from": ["nonexistent"]}, root=self.base)
        for bad_from in ("a", [1], [""], ["   "]):
            with self.assertRaises(ToolError):
                dispatch_tool("okf_links", {"wiki": "wiki", "from": bad_from}, root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool("okf_links", {"wiki": "wiki", "direction": "sideways"}, root=self.base)
        with self.assertRaises(ToolError):
            dispatch_tool("okf_links", {"wiki": "wiki", "include_admin": "true"}, root=self.base)

    # -- U3: okf_validate extension ----------------------------------------

    def test_validate_schema_and_backwards_compatibility(self):
        spec = self._spec("okf_validate")
        schema = spec["inputSchema"]
        self.assertEqual(schema["required"], ["wiki"])
        self.assertFalse(schema["additionalProperties"])
        props = schema["properties"]
        self.assertEqual(
            set(props),
            {"wiki", "check_evidence", "evidence_dir", "strict_provenance"},
        )
        self.assertEqual(props["check_evidence"]["type"], "boolean")
        self.assertFalse(props["check_evidence"]["default"])
        self.assertEqual(props["evidence_dir"]["type"], "string")
        self.assertEqual(props["strict_provenance"]["type"], "boolean")
        self.assertFalse(props["strict_provenance"]["default"])

        # Backwards compatibility: wiki without evidence/ dir matches validate_wiki(wiki).as_dict()
        compat_wiki = self.base / "compat_wiki"
        write(compat_wiki, "index.md", "# Index\n")
        write(
            compat_wiki,
            "concepts/ext.md",
            node("type: Concept\nbasis: external\nverified_at: '2026-11-19'\n", "# Ext\n"),
        )
        via_tool = dispatch_tool("okf_validate", {"wiki": "compat_wiki"}, root=self.base)
        direct = validate_wiki(compat_wiki).as_dict()
        self.assertEqual(via_tool, direct)
        self.assertTrue(via_tool["ok"])
        self.assertNotIn("evidence", via_tool)

        # strict_provenance=True promotes [P2] to error
        strict_tool = dispatch_tool(
            "okf_validate",
            {"wiki": "compat_wiki", "strict_provenance": True},
            root=self.base,
        )
        code_s, cli_strict, _ = self._run_cli_json(
            "validate", str(compat_wiki), "--strict-provenance", "--json",
        )
        self.assertEqual(code_s, 1)
        self.assertFalse(strict_tool["ok"])
        self.assertEqual(strict_tool, cli_strict)

    def test_validate_check_evidence_default_explicit_and_errors(self):
        ev_wiki = self.base / "ev_wiki"
        write(ev_wiki, "index.md", "# Index\n")
        url = "https://example.com/aln.html"
        write(
            ev_wiki,
            "concepts/aln.md",
            node(
                "type: Concept\n"
                "title: 'AlN'\n"
                "basis: external\n"
                f"sources: ['web:{url} retrieved=2026-11-19']\n"
                "verified_at: '2026-11-19'\n",
                "# AlN\n",
            ),
        )
        default_ev = ev_wiki / "evidence"
        snaps = default_ev / "snapshots"
        snaps.mkdir(parents=True)
        key = snapshot_key_for_url(url)
        (snaps / f"{key}.html").write_bytes(b"content")
        (snaps / f"{key}.meta.json").write_text(
            json.dumps({"url": url, "sha256": "sha256:123"}), encoding="utf-8",
        )
        orphan_url = "https://example.com/orphan.html"
        o_key = snapshot_key_for_url(orphan_url)
        (snaps / f"{o_key}.html").write_bytes(b"orphan")
        (snaps / f"{o_key}.meta.json").write_text(
            json.dumps({"url": orphan_url, "sha256": "sha256:456", "orphan_reason": "no numbers"}),
            encoding="utf-8",
        )

        # Default <wiki>/evidence
        res_def = dispatch_tool(
            "okf_validate",
            {"wiki": "ev_wiki", "check_evidence": True},
            root=self.base,
        )
        code_def, cli_def, _ = self._run_cli_json(
            "validate", str(ev_wiki), "--check-evidence", "--evidence-dir", str(default_ev), "--json",
        )
        self.assertEqual(code_def, 0)
        self.assertTrue(res_def["ok"])
        self.assertIn("evidence", res_def)
        self.assertEqual(res_def, cli_def)

        # Explicit confined evidence_dir
        shared_ev = self.base / "shared_ev"
        (shared_ev / "snapshots").mkdir(parents=True)
        (shared_ev / "snapshots" / f"{key}.html").write_bytes(b"content")
        (shared_ev / "snapshots" / f"{key}.meta.json").write_text(
            json.dumps({"url": url, "sha256": "sha256:123"}), encoding="utf-8",
        )
        res_exp = dispatch_tool(
            "okf_validate",
            {"wiki": "ev_wiki", "check_evidence": True, "evidence_dir": "shared_ev"},
            root=self.base,
        )
        code_exp, cli_exp, _ = self._run_cli_json(
            "validate", str(ev_wiki), "--check-evidence", "--evidence-dir", str(shared_ev), "--json",
        )
        self.assertEqual(code_exp, 0)
        self.assertEqual(res_exp, cli_exp)

        # check_evidence + strict_provenance with missing snapshot -> [E1] error
        write(
            ev_wiki,
            "concepts/missing.md",
            node(
                "type: Concept\ntitle: Missing\nbasis: external\n"
                "sources: ['web:https://example.com/missing.html retrieved=2026-11-19']\n"
                "verified_at: '2026-11-19'\n",
                "# Missing\n",
            ),
        )
        res_fail = dispatch_tool(
            "okf_validate",
            {"wiki": "ev_wiki", "check_evidence": True, "strict_provenance": True},
            root=self.base,
        )
        code_f, cli_fail, _ = self._run_cli_json(
            "validate", str(ev_wiki), "--check-evidence",
            "--evidence-dir", str(default_ev), "--strict-provenance", "--json",
        )
        self.assertEqual(code_f, 1)
        self.assertFalse(res_fail["ok"])
        self.assertEqual(res_fail, cli_fail)

        # Error cases
        # 1. check_evidence=True when default <wiki>/evidence does not exist
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_validate", {"wiki": "wiki", "check_evidence": True}, root=self.base,
            )
        # 2. evidence_dir escaping root (both check_evidence=True and False)
        confined = self.base / "confined_ev"
        c_wiki = confined / "wiki"
        write(c_wiki, "index.md", "# Index\n")
        outside_ev = self.base / "outside_ev"
        outside_ev.mkdir()
        for ce in (False, True):
            with self.assertRaises(ToolError):
                dispatch_tool(
                    "okf_validate",
                    {"wiki": "wiki", "check_evidence": ce, "evidence_dir": "../outside_ev"},
                    root=confined,
                )
            with self.assertRaises(ToolError):
                dispatch_tool(
                    "okf_validate",
                    {"wiki": "wiki", "check_evidence": ce, "evidence_dir": str(outside_ev)},
                    root=confined,
                )
        # 3. symlink <wiki>/evidence escaping root
        sym_wiki = confined / "sym_wiki"
        write(sym_wiki, "index.md", "# Index\n")
        os.symlink(outside_ev, sym_wiki / "evidence")
        with self.assertRaises(ToolError) as ctx:
            dispatch_tool(
                "okf_validate",
                {"wiki": "sym_wiki", "check_evidence": True},
                root=confined,
            )
        self.assertIn("escapes", str(ctx.exception))

        # 4. nonexistent evidence_dir, file as evidence_dir, whitespace, bad bools
        for bad_ev in ("missing_ev", "wiki/a.md", "  "):
            with self.assertRaises(ToolError):
                dispatch_tool(
                    "okf_validate",
                    {"wiki": "wiki", "check_evidence": True, "evidence_dir": bad_ev},
                    root=self.base,
                )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_validate", {"wiki": "wiki", "check_evidence": "true"}, root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_validate", {"wiki": "wiki", "strict_provenance": 1}, root=self.base,
            )

    # -- U4: okf_search verification ---------------------------------------

    def test_search_type_scope_expand_cli_parity_and_errors(self):
        sw = self.base / "search_wiki"
        write(sw, "index.md", "# Index\n")
        write(
            sw,
            "concepts/c_tax.md",
            node("type: Concept\nscope: taxonomy\ntitle: Glass Tax\n", "# Glass Tax\nGlassy phase.\n"),
        )
        write(
            sw,
            "concepts/c_gotcha.md",
            node("type: Concept\nscope: gotchas\ntitle: Glass Gotcha\n", "# Glass Gotcha\nGlassy failure.\n"),
        )
        write(
            sw,
            "patents/p_gotcha.md",
            node("type: Patent\nscope: gotchas\ntitle: Glass Patent\n", "# Glass Patent\nGlassy patent.\n"),
        )
        write(sw, "synonyms.json", json.dumps({"groups": [["vitreous", "glassy"]]}))

        # Combined type + scope + expand=True
        hits = dispatch_tool(
            "okf_search",
            {
                "wiki": "search_wiki",
                "query": "vitreous",
                "type": "concept",
                "scope": "gotchas",
                "expand": True,
            },
            root=self.base,
        )
        self.assertEqual([h["node"] for h in hits], ["concepts/c_gotcha.md"])

        code, cli_hits, _ = self._run_cli_json(
            "search", str(sw), "vitreous", "--type", "concept", "--scope", "gotchas", "--expand", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(hits, cli_hits)

        # Comma-separated scope="taxonomy,gotchas" with type="concept"
        hits_multi = dispatch_tool(
            "okf_search",
            {
                "wiki": "search_wiki",
                "query": "vitreous",
                "type": "concept",
                "scope": "taxonomy,gotchas",
                "expand": True,
            },
            root=self.base,
        )
        self.assertEqual(
            {h["node"] for h in hits_multi},
            {"concepts/c_tax.md", "concepts/c_gotcha.md"},
        )
        code_m, cli_multi, _ = self._run_cli_json(
            "search", str(sw), "vitreous",
            "--type", "concept", "--scope", "taxonomy", "--scope", "gotchas", "--expand", "--json",
        )
        self.assertEqual(code_m, 0)
        self.assertEqual(hits_multi, cli_multi)

        # Error cases
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "search_wiki", "query": "glassy", "scope": "bogus"},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "wiki", "query": "amorphous", "expand": True},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "search_wiki", "query": "glassy", "expand": "true"},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "search_wiki", "query": "glassy", "type": ["concept"]},
                root=self.base,
            )
        with self.assertRaises(ToolError):
            dispatch_tool(
                "okf_search",
                {"wiki": "search_wiki", "query": "glassy", "scope": ["gotchas"]},
                root=self.base,
            )

    # -- Phase C: okf_claims -----------------------------------------------

    def test_claims_schema_contract(self):
        spec = self._spec("okf_claims")
        desc = spec["description"].lower()
        self.assertIn("supports", desc)
        self.assertIn("contradicts", desc)
        self.assertIn("no verdicts", desc)
        schema = spec["inputSchema"]
        self.assertEqual(schema["required"], ["wiki"])
        self.assertFalse(schema["additionalProperties"])
        props = schema["properties"]
        self.assertEqual(set(props), {"wiki", "sample", "seed", "notes"})
        self.assertEqual(props["sample"]["type"], "integer")
        self.assertEqual(props["sample"]["minimum"], 0)
        self.assertEqual(props["seed"]["type"], "integer")
        self.assertEqual(props["seed"]["default"], 0)
        self.assertEqual(props["notes"]["type"], "array")
        self.assertEqual(props["notes"]["items"]["type"], "string")

    def _make_claims_wiki(self) -> Path:
        cw = self.base / "claims_wiki"
        write(cw, "index.md", "# Index\n")
        write(cw, "concepts/alpha.md", node(
            "type: Concept\ntitle: Alpha\nsources: ['paper:doi:10.1/a']\n",
            "# Alpha\nStress reaches 120 MPa. Strain is 2.5%.\n",
        ))
        write(cw, "concepts/beta.md", node(
            "type: Concept\ntitle: Beta\n",
            "# Beta\nCycle count is 5000. Thickness is 12 um.\n",
        ))
        write(cw, "concepts/gamma.md", node(
            "type: Concept\ntitle: Gamma\n",
            "# Gamma\nTemperature is 450 K.\n",
        ))
        return cw

    def test_claims_dispatch_cli_parity_and_determinism(self):
        cw = self._make_claims_wiki()

        res_all = dispatch_tool("okf_claims", {"wiki": "claims_wiki"}, root=self.base)
        code, cli_all, _ = self._run_cli_json("claims", str(cw), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(res_all, cli_all)
        self.assertEqual(res_all["total_claims"], 5)
        self.assertEqual(res_all["returned"], 5)
        self.assertEqual(res_all["seed"], 0)

        # Deterministic sampling with seed matches CLI and repeats identically
        s1 = dispatch_tool(
            "okf_claims", {"wiki": "claims_wiki", "sample": 3, "seed": 42}, root=self.base,
        )
        s2 = dispatch_tool(
            "okf_claims", {"wiki": "claims_wiki", "sample": 3, "seed": 42}, root=self.base,
        )
        code_s, cli_s, _ = self._run_cli_json(
            "claims", str(cw), "--sample", "3", "--seed", "42", "--json",
        )
        self.assertEqual(code_s, 0)
        self.assertEqual(s1, s2)
        self.assertEqual(s1, cli_s)
        self.assertEqual(s1["total_claims"], 5)
        self.assertEqual(s1["returned"], 3)
        self.assertEqual(s1["seed"], 42)

        # sample=0 returns zero claims while reporting total_claims
        s0 = dispatch_tool(
            "okf_claims", {"wiki": "claims_wiki", "sample": 0}, root=self.base,
        )
        self.assertEqual(s0["total_claims"], 5)
        self.assertEqual(s0["returned"], 0)
        self.assertEqual(s0["claims"], [])

    def test_claims_notes_filter_and_errors(self):
        cw = self._make_claims_wiki()

        # slug, filename, and relative path all match
        res_notes = dispatch_tool(
            "okf_claims",
            {"wiki": "claims_wiki", "notes": ["alpha", "beta.md", "concepts/gamma.md"]},
            root=self.base,
        )
        self.assertEqual(res_notes["total_claims"], 5)

        res_single = dispatch_tool(
            "okf_claims",
            {"wiki": "claims_wiki", "notes": ["beta.md"]},
            root=self.base,
        )
        code_n, cli_n, _ = self._run_cli_json(
            "claims", str(cw), "--note", "beta.md", "--json",
        )
        self.assertEqual(code_n, 0)
        self.assertEqual(res_single, cli_n)
        self.assertEqual({c["note"] for c in res_single["claims"]}, {"concepts/beta.md"})

        # Error cases
        for bad_args in (
            {"wiki": "claims_wiki", "sample": -1},
            {"wiki": "claims_wiki", "sample": True},
            {"wiki": "claims_wiki", "sample": "2"},
            {"wiki": "claims_wiki", "seed": False},
            {"wiki": "claims_wiki", "seed": "0"},
            {"wiki": "claims_wiki", "notes": "alpha"},
            {"wiki": "claims_wiki", "notes": [""]},
            {"wiki": "../outside"},
        ):
            with self.subTest(bad_args=bad_args):
                with self.assertRaises(ToolError):
                    dispatch_tool("okf_claims", bad_args, root=self.base)

    # -- U7: okf_neighbors -------------------------------------------------

    def test_neighbors_schema_contract(self):
        spec = self._spec("okf_neighbors")
        schema = spec["inputSchema"]
        self.assertEqual(schema["required"], ["wiki", "anchor"])
        self.assertFalse(schema["additionalProperties"])
        props = schema["properties"]
        self.assertEqual(
            set(props),
            {"wiki", "anchor", "hops", "direction", "top_n", "include_admin"},
        )
        self.assertEqual(props["hops"]["default"], 1)
        self.assertEqual(props["direction"]["enum"], ["both", "out", "in"])
        self.assertEqual(props["direction"]["default"], "both")
        self.assertEqual(props["top_n"]["default"], 10)
        self.assertEqual(props["include_admin"]["default"], False)

    def _make_neighbors_wiki(self) -> Path:
        nw = self.base / "nbrs_wiki"
        write(nw, "index.md", "# Index\n")
        write(nw, "SUMMARY.md", node("type: Summary\ntitle: Summary\n", "# Summary\nSee [A](concepts/a.md).\n"))
        write(nw, "concepts/a.md", node(
            "type: Concept\ntitle: Concept A\n",
            "# Concept A\n\n## 関連\n- Orthogonal to [B](b.md).\n- Also mentions [C](c.md).\n",
        ))
        write(nw, "concepts/b.md", node(
            "type: Concept\ntitle: Concept B\n",
            "# Concept B\n\n## 関連\n- Extends [A](a.md) and [D](d.md).\n",
        ))
        write(nw, "concepts/c.md", node(
            "type: Concept\ntitle: Concept C\n",
            "# Concept C\n\n## 関連\n- Uses [E](e.md).\n",
        ))
        write(nw, "concepts/d.md", node("type: Concept\ntitle: Concept D\n", "# Concept D\n"))
        write(nw, "concepts/e.md", node(
            "type: Concept\ntitle: Concept E\n",
            "# Concept E\n\n## 関連\n- Inbound to [A](a.md).\n",
        ))
        return nw

    def test_neighbors_ranking_directions_clamping_and_cli_parity(self):
        nw = self._make_neighbors_wiki()

        # Default hops=1, direction=both: B (mutual: 2 paths), C (1 path), E (1 path), ordered by (-paths, id)
        res1 = dispatch_tool("okf_neighbors", {"wiki": "nbrs_wiki", "anchor": "a"}, root=self.base)
        code1, cli1, _ = self._run_cli_json("neighbors", str(nw), "a", "--json")
        self.assertEqual(code1, 0)
        self.assertEqual(res1, cli1)
        self.assertTrue(res1["found"])
        self.assertEqual(res1["anchor"], {"id": "concepts/a.md", "title": "Concept A"})
        self.assertEqual(
            [n["id"] for n in res1["neighbors"]],
            ["concepts/b.md", "concepts/c.md", "concepts/e.md"],
        )
        self.assertEqual(res1["neighbors"][0]["shortest_paths"], 2)
        self.assertEqual(res1["neighbors"][0]["path"], ["concepts/a.md", "concepts/b.md"])
        self.assertEqual(len(res1["neighbors"][0]["link_contexts"]), 2)
        self.assertIn("Orthogonal to", res1["neighbors"][0]["link_contexts"][0]["context"])

        # Exclude admin by default (SUMMARY.md is not in neighbors)
        self.assertNotIn("SUMMARY.md", [n["id"] for n in res1["neighbors"]])

        # hops=2 reaches D via B with path [a, b, d] and link_contexts along all steps
        res2 = dispatch_tool(
            "okf_neighbors",
            {"wiki": "nbrs_wiki", "anchor": "a", "hops": 2, "direction": "out"},
            root=self.base,
        )
        code2, cli2, _ = self._run_cli_json(
            "neighbors", str(nw), "a", "--hops", "2", "--direction", "out", "--json",
        )
        self.assertEqual(code2, 0)
        self.assertEqual(res2, cli2)
        self.assertEqual(
            [n["id"] for n in res2["neighbors"]],
            ["concepts/b.md", "concepts/c.md", "concepts/d.md", "concepts/e.md"],
        )
        d_entry = next(n for n in res2["neighbors"] if n["id"] == "concepts/d.md")
        self.assertEqual(d_entry["hop"], 2)
        self.assertEqual(d_entry["path"], ["concepts/a.md", "concepts/b.md", "concepts/d.md"])
        self.assertEqual([c["step"] for c in d_entry["link_contexts"]], [1, 2])

        # direction=in returns only inbound links (B and E)
        res_in = dispatch_tool(
            "okf_neighbors",
            {"wiki": "nbrs_wiki", "anchor": "a", "direction": "in"},
            root=self.base,
        )
        self.assertEqual([n["id"] for n in res_in["neighbors"]], ["concepts/b.md", "concepts/e.md"])

        # Clamping & determinism
        c1 = dispatch_tool(
            "okf_neighbors",
            {"wiki": "nbrs_wiki", "anchor": "a", "hops": 10, "top_n": 100},
            root=self.base,
        )
        c2 = dispatch_tool(
            "okf_neighbors",
            {"wiki": "nbrs_wiki", "anchor": "a", "hops": 10, "top_n": 100},
            root=self.base,
        )
        code_c, cli_c, _ = self._run_cli_json(
            "neighbors", str(nw), "a", "--hops", "10", "--top-n", "100", "--json",
        )
        self.assertEqual(code_c, 0)
        self.assertEqual(c1, c2)
        self.assertEqual(c1, cli_c)
        self.assertEqual(c1["effective"], {"hops": 3, "direction": "both", "top_n": 50})
        self.assertEqual(c1["truncated_params"], {"hops": True, "top_n": True})

    def test_neighbors_missing_anchor_and_errors(self):
        nw = self._make_neighbors_wiki()
        missing = dispatch_tool(
            "okf_neighbors", {"wiki": "nbrs_wiki", "anchor": "missing-concept"}, root=self.base,
        )
        code_m, cli_m, _ = self._run_cli_json(
            "neighbors", str(nw), "missing-concept", "--json",
        )
        self.assertEqual(code_m, 1)
        self.assertEqual(missing, cli_m)
        self.assertFalse(missing["found"])
        self.assertIn("anchor concept not found", missing["error"])
        self.assertEqual(missing["neighbors"], [])

        for bad_args in (
            {"wiki": "nbrs_wiki", "anchor": ""},
            {"wiki": "nbrs_wiki", "anchor": "a", "hops": 0},
            {"wiki": "nbrs_wiki", "anchor": "a", "hops": True},
            {"wiki": "nbrs_wiki", "anchor": "a", "top_n": 0},
            {"wiki": "nbrs_wiki", "anchor": "a", "direction": "sideways"},
            {"wiki": "nbrs_wiki", "anchor": "a", "include_admin": "yes"},
            {"wiki": "../outside", "anchor": "a"},
        ):
            with self.subTest(bad_args=bad_args):
                with self.assertRaises(ToolError):
                    dispatch_tool("okf_neighbors", bad_args, root=self.base)


if __name__ == "__main__":
    unittest.main()
