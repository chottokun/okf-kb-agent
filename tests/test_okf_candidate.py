"""Tests for okf candidate-check core engine and parsing."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from okf_kb_agent.wiki.candidate import (
    CandidateChecker,
    CandidateCheckItem,
    CandidateCheckResult,
    CandidateRelations,
    check_verbatim_evidence,
    parse_proposal_candidates,
)
from okf_kb_agent.wiki.cli import main


def write_doc(root: Path, rel: str, meta: str, body: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{meta}---\n{body}", encoding="utf-8")
    return path


class CandidateCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "concepts").mkdir(parents=True, exist_ok=True)

    def run_cli(self, *args):
        out, err = StringIO(), StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = main([str(arg) for arg in args])
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_regression_seed_a_dielectric_fluid_spray_cooling(self):
        """Regression Seed (a): dielectric-fluid x spray-cooling.

        Existing concept spray-cooling has tags [spray-cooling, dielectric-fluid].
        Generated synonym group has [spray-cooling, dielectric-fluid].
        Candidate dielectric-fluid has no name_occupied, tag_on with provenance=free,
        and synonyms with kind=generated, owner=spray-cooling.
        No status, severity, or hard_collision tokens appear in result JSON.
        """
        write_doc(
            self.root,
            "concepts/spray-cooling.md",
            "type: Concept\ntitle: 'Spray Cooling'\ntags: [spray-cooling, dielectric-fluid]\n",
            "# Spray Cooling\n",
        )
        (self.root / "synonyms.json").write_text(
            json.dumps({
                "groups": [["spray-cooling", "dielectric-fluid"]],
                "generated_groups": [["spray-cooling", "dielectric-fluid"]],
                "manual_groups": [],
            }),
            encoding="utf-8",
        )

        checker = CandidateChecker(self.root)
        result = checker.check_candidates(["dielectric-fluid"])

        self.assertEqual(len(result.candidates), 1)
        item = result.candidates[0]
        self.assertEqual(item.slug, "dielectric-fluid")
        self.assertIsNone(item.relations.name_occupied)
        self.assertEqual(len(item.relations.tag_on), 1)
        self.assertEqual(
            item.relations.tag_on[0],
            {
                "tag": "dielectric-fluid",
                "concept": "spray-cooling",
                "file": "concepts/spray-cooling.md",
                "provenance": "free",
            },
        )
        self.assertEqual(len(item.relations.synonyms), 1)
        self.assertEqual(
            item.relations.synonyms[0],
            {
                "kind": "generated",
                "matched_term": "dielectric-fluid",
                "group": ["spray-cooling", "dielectric-fluid"],
                "owner": "spray-cooling",
                "owner_resolved": True,
            },
        )

        res_dict = result.to_dict()
        self.assertEqual(res_dict["version"], "0.2")
        dumped_json = json.dumps(res_dict)
        self.assertNotIn('"status"', dumped_json)
        self.assertNotIn('"severity"', dumped_json)
        self.assertNotIn('"hard_collision"', dumped_json)
        self.assertNotIn('"hard_collisions"', dumped_json)

        self.assertEqual(result.summary["total_candidates"], 1)
        self.assertEqual(result.summary["name_occupied_count"], 0)
        self.assertEqual(result.summary["synonym_manual_count"], 0)
        self.assertEqual(result.summary["synonym_generated_count"], 1)
        self.assertEqual(result.summary["tag_relation_count"], 1)
        self.assertEqual(result.summary["verbatim_miss_count"], 0)

    def test_regression_seed_b_missing_synonyms_json(self):
        """Regression Seed (b): missing synonyms.json fixture.

        Checker reports missing input in inputs_status, tier_a_tags_key_present=False,
        and scan_completeness tag counts close (fixed + free + excluded == total).
        """
        write_doc(
            self.root,
            "concepts/spray-cooling.md",
            "type: Concept\ntitle: 'Spray Cooling'\ntags: [spray-cooling, cooling, dielectric-fluid]\n",
            "# Spray Cooling\n",
        )
        checker = CandidateChecker(self.root)
        status = checker.check_inputs_status()

        self.assertFalse(status["synonyms_json_present"])
        self.assertIn("synonyms.json", status["inputs_missing"])
        self.assertFalse(status["tier_a_tags_key_present"])
        self.assertEqual(status["tier_a_tags_count"], 0)
        self.assertIsNone(status.get("synonyms_json_parse_error"))

        result = checker.check_candidates(["interposer"])
        self.assertFalse(result.inputs_status["synonyms_json_present"])
        self.assertIn("synonyms.json", result.inputs_status["inputs_missing"])
        self.assertFalse(result.inputs_status["tier_a_tags_key_present"])

        sc = result.scan_completeness
        self.assertIn("scanned_excluded_tags", sc)
        self.assertEqual(
            sc["scanned_fixed_vocabulary_tags"] + sc["scanned_free_tags"] + sc["scanned_excluded_tags"],
            sc["scanned_concept_tags_total"],
        )
        self.assertEqual(sc["scanned_excluded_tags"], 1)  # 'cooling' is excluded

    def test_filename_and_synonym_relations(self):
        """Test name_occupied relation and manual synonym relation."""
        write_doc(
            self.root,
            "concepts/interposer.md",
            "type: Concept\ntitle: 'Interposer'\ntags: [interposer, silicon-interposer]\n",
            "# Interposer\n",
        )
        (self.root / "synonyms.json").write_text(
            json.dumps({
                "groups": [["tim", "thermal-interface-materials"]],
                "generated_groups": [],
                "manual_groups": [["tim", "thermal-interface-materials"]],
            }),
            encoding="utf-8",
        )

        checker = CandidateChecker(self.root)
        # 1. Filename occupation
        res1 = checker.check_candidates(["interposer"])
        item1 = res1.candidates[0]
        self.assertIsNotNone(item1.relations.name_occupied)
        self.assertEqual(
            item1.relations.name_occupied,
            {"matched_name": "interposer", "file": "concepts/interposer.md"},
        )
        self.assertEqual(res1.summary["name_occupied_count"], 1)

        # 2. Synonym relation (manual)
        res2 = checker.check_candidates(["tim"])
        item2 = res2.candidates[0]
        self.assertIsNone(item2.relations.name_occupied)
        self.assertEqual(len(item2.relations.synonyms), 1)
        self.assertEqual(
            item2.relations.synonyms[0],
            {
                "kind": "manual",
                "matched_term": "tim",
                "group": ["tim", "thermal-interface-materials"],
                "owner": None,
            },
        )
        self.assertEqual(res2.summary["synonym_manual_count"], 1)

    def test_regression_seed_c_run3_verbatim_six_candidates(self):
        """Regression Seed (c): Run 3's 6 candidates pass verbatim 6/6, taxonomy-gap skipped."""
        # Setup artifacts
        write_doc(
            self.root,
            "concepts/silicon-carrier.md",
            "type: Concept\ntitle: 'Silicon Carrier'\n",
            "Silicon interposer technology provides high-density interconnect.\n",
        )
        write_doc(
            self.root,
            "patents/EP3000000A1.md",
            "type: Patent\ntitle: 'Solder joint'\n",
            "Using a pre-formed solder preform sheet between substrate and die.\n",
        )
        sv_dir = self.root / "data" / "external" / "source_verify"
        sv_dir.mkdir(parents=True, exist_ok=True)
        # Crossref json for htcc
        (sv_dir / "crossref_10.1007_s10854-020-001.json").write_text(
            json.dumps({"title": "Properties of HTCC substrates in power packaging"}),
            encoding="utf-8",
        )
        # Crossref json for dielectric fluid
        (sv_dir / "crossref_10.1016_j.applthermaleng.2024.124403.json").write_text(
            json.dumps({
                "message": {
                    "abstract": "Enhancement of dielectric fluid spray cooling for high-heat-flux electronics."
                }
            }),
            encoding="utf-8",
        )
        # Snapshot txt for thermal-spray-coating
        (sv_dir / "vendor_snapshot.extracted.txt").write_text(
            "Advanced thermal spray coating processes for ceramic substrates.\n",
            encoding="utf-8",
        )

        proposal_text = """### Candidate Proposal Pool (Target: 3 concepts; Pool: 6 candidates)
1. **`interposer`** — インターポーザ（Interposer） [`established`]
   - **(a) Adjacency**: Extends `concepts/silicon-carrier.md`.
   - **(b) Primary-Source Emergence**: "interposer" in concepts/silicon-carrier.md (dense packaging)
   - **(c) Deduplication**: distinct.
2. **`htcc-substrates`** — 高温同時焼成セラミックス基板（HTCC Substrates） [`established`]
   - **(a) Adjacency**: Extends ceramic substrates.
   - **(b) Primary-Source Emergence**: "HTCC substrates" in 10.1007/s10854-020-001 (substrate comparison)
   - **(c) Deduplication**: distinct.
3. **`dielectric-fluid`** — 絶縁性流体（Dielectric Fluid） [`established`]
   - **(a) Adjacency**: Extends cooling.
   - **(b) Primary-Source Emergence**: "dielectric fluid spray cooling" in 10.1016/j.applthermaleng.2024.124403 (spray cooling study)
   - **(c) Deduplication**: distinct.
4. **`solder-preform`** — はんだプリフォーム（Solder Preform） [`established`]
   - **(a) Adjacency**: Extends die attach.
   - **(b) Primary-Source Emergence**: "solder preform" in patents/EP3000000A1.md (die attachment)
   - **(c) Deduplication**: distinct.
5. **`thermal-spray-coating`** — 溶射コーティング（Thermal Spray Coating） [`niche`]
   - **(a) Adjacency**: Extends coatings.
   - **(b) Primary-Source Emergence**: "thermal spray coating" in data/external/source_verify/vendor_snapshot.extracted.txt (surface coating)
   - **(c) Deduplication**: distinct.
6. **`near-junction-cooling`** — ジャンクション近接冷却（Near-Junction Cooling） [`niche`]
   - **(a) Adjacency**: Extends advanced heat sink architectures.
   - **(b) Primary-Source Emergence**: taxonomy-gap
   - **(c) Deduplication**: distinct.
"""
        proposal_file = self.root / "proposal.md"
        proposal_file.write_text(proposal_text, encoding="utf-8")

        candidates_parsed = parse_proposal_candidates(proposal_text)
        self.assertEqual(len(candidates_parsed), 6)
        self.assertEqual(candidates_parsed[5]["slug"], "near-junction-cooling")
        self.assertEqual(candidates_parsed[5]["cited_target"], "taxonomy-gap")

        (self.root / "synonyms.json").write_text(
            json.dumps({"groups": [], "generated_groups": [], "manual_groups": []}),
            encoding="utf-8",
        )

        checker = CandidateChecker(self.root)
        result = checker.check_proposal(proposal_file)

        self.assertEqual(result.summary["total_candidates"], 6)
        self.assertEqual(result.summary["name_occupied_count"], 0)
        self.assertEqual(result.summary["verbatim_miss_count"], 0)

        for c in result.candidates:
            self.assertIsNotNone(c.verbatim_check)
            if c.slug == "near-junction-cooling":
                self.assertFalse(c.verbatim_check["claimed_emergence"])
                self.assertIsNone(c.verbatim_check["verbatim_found"])
                self.assertIsNone(c.verbatim_check["artifact_exists"])
                self.assertEqual(c.verbatim_check["parse_status"], "taxonomy-gap")
            else:
                self.assertTrue(c.verbatim_check["claimed_emergence"])
                self.assertTrue(c.verbatim_check["verbatim_found"])
                self.assertTrue(c.verbatim_check["artifact_exists"])
                self.assertEqual(c.verbatim_check["parse_status"], "ok")
                self.assertGreaterEqual(c.verbatim_check["match_count"], 1)

    def test_verbatim_missing_file_or_term(self):
        """Test verbatim check when cited file is missing or term is not found."""
        # 1. Missing target artifact
        res_missing_art = check_verbatim_evidence(
            self.root, "10.9999/nonexistent.doi", "some term"
        )
        self.assertFalse(res_missing_art["artifact_exists"])
        self.assertFalse(res_missing_art["verbatim_found"])
        self.assertEqual(res_missing_art["match_count"], 0)

        # 2. Artifact exists, but term is missing
        write_doc(
            self.root,
            "concepts/sample.md",
            "type: Concept\ntitle: 'Sample'\n",
            "Only unrelated keywords here.\n",
        )
        res_missing_term = check_verbatim_evidence(
            self.root, "concepts/sample.md", "totally missing term"
        )
        self.assertTrue(res_missing_term["artifact_exists"])
        self.assertFalse(res_missing_term["verbatim_found"])
        self.assertEqual(res_missing_term["match_count"], 0)

    def test_skill_document_candidate_check_integration(self):
        """Unit U4 test: verify SKILL.md integrates candidate-check and stays <= 200 lines."""
        skill_path = Path(".agents/skills/kb-batch-discipline/SKILL.md")
        self.assertTrue(skill_path.exists())
        lines = skill_path.read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(lines), 200)

        content = "\n".join(lines)
        self.assertIn("candidate-check", content)
        self.assertIn("Relations:", content)
        self.assertNotIn("Tag collisions", content)

    def test_seed2_graphite_sheet_on_graphene_film_concept_slug_other(self):
        """Seed 2: Tag matching another existing concept slug is classified as concept_slug_other."""
        write_doc(
            self.root,
            "concepts/graphite-sheet.md",
            "type: Concept\ntitle: 'Graphite Sheet'\ntags: [graphite-sheet]\n",
            "# Graphite Sheet\n",
        )
        write_doc(
            self.root,
            "concepts/graphene-film.md",
            "type: Concept\ntitle: 'Graphene Film'\ntags: [graphene-film, graphite-sheet]\n",
            "# Graphene Film\n",
        )
        (self.root / "synonyms.json").write_text(
            json.dumps({"groups": [], "generated_groups": [], "manual_groups": []}),
            encoding="utf-8",
        )

        checker = CandidateChecker(self.root)
        result = checker.check_candidates(["graphite-sheet"])
        self.assertEqual(len(result.candidates), 1)
        item = result.candidates[0]

        # Tag on graphene-film should have provenance "concept_slug_other"
        # Tag on graphite-sheet should have provenance "concept_slug"
        tag_prov_by_concept = {
            t["concept"]: t["provenance"] for t in item.relations.tag_on
        }
        self.assertEqual(tag_prov_by_concept.get("graphite-sheet"), "concept_slug")
        self.assertEqual(tag_prov_by_concept.get("graphene-film"), "concept_slug_other")

    def test_seed_corrupt_synonyms_json_reported_in_inputs_status(self):
        """Seed: corrupt synonyms.json is reported in inputs_status.synonyms_json_parse_error."""
        (self.root / "synonyms.json").write_text("{invalid json", encoding="utf-8")
        checker = CandidateChecker(self.root)
        status = checker.check_inputs_status()

        self.assertTrue(status["synonyms_json_present"])
        self.assertIsNotNone(status.get("synonyms_json_parse_error"))
        self.assertIn("Expecting property name", status["synonyms_json_parse_error"])
        # default exit is 0
        code, _, _ = self.run_cli("candidate-check", self.root, "interposer")
        self.assertEqual(code, 0)
        # --fail-on input-missing exits 1
        code_fail, _, _ = self.run_cli(
            "candidate-check", self.root, "interposer", "--fail-on", "input-missing"
        )
        self.assertEqual(code_fail, 1)

    def test_seed_taxonomy_gap_fail_on_verbatim_cli_exits_zero(self):
        """Seed: proposal with taxonomy-gap candidate exits 0 under --fail-on verbatim."""
        (self.root / "synonyms.json").write_text("{}", encoding="utf-8")
        proposal_text = """### Candidate Proposal Pool
1. **`near-junction-cooling`** — ジャンクション近接冷却 [`niche`]
   - **(a) Adjacency**: Extends heat sinks.
   - **(b) Primary-Source Emergence**: taxonomy-gap
   - **(c) Deduplication**: distinct.
"""
        prop_file = self.root / "proposal.md"
        prop_file.write_text(proposal_text, encoding="utf-8")

        code, out, _ = self.run_cli(
            "candidate-check", self.root, "--proposal", str(prop_file), "--fail-on", "verbatim"
        )
        self.assertEqual(code, 0)

        # Contrast: missing verbatim evidence fails with exit 1
        bad_prop = """### Candidate Proposal Pool
1. **`bad-candidate`** — 不正候補 [`niche`]
   - **(a) Adjacency**: Extends heat sinks.
   - **(b) Primary-Source Emergence**: "missing term" in nonexistent.txt
   - **(c) Deduplication**: distinct.
"""
        bad_file = self.root / "bad_proposal.md"
        bad_file.write_text(bad_prop, encoding="utf-8")
        code_bad, _, _ = self.run_cli(
            "candidate-check", self.root, "--proposal", str(bad_file), "--fail-on", "verbatim"
        )
        self.assertEqual(code_bad, 1)

    def test_seed_die_attach_excluded_tag_on(self):
        """Seed: candidate matching an excluded tag returns provenance='excluded' in tag_on."""
        write_doc(
            self.root,
            "concepts/power-module.md",
            "type: Concept\ntitle: 'Power Module'\ntags: [power-module, die-attach]\n",
            "# Power Module\n",
        )
        (self.root / "synonyms.json").write_text("{}", encoding="utf-8")

        checker = CandidateChecker(self.root)
        result = checker.check_candidates(["die-attach"])
        self.assertEqual(len(result.candidates), 1)
        item = result.candidates[0]

        self.assertEqual(len(item.relations.tag_on), 1)
        tag_info = item.relations.tag_on[0]
        self.assertEqual(tag_info["tag"], "die-attach")
        self.assertEqual(tag_info["concept"], "power-module")
        self.assertEqual(tag_info["provenance"], "excluded")

        # --fail-on tag should trigger for excluded tags as well
        code, _, _ = self.run_cli(
            "candidate-check", self.root, "die-attach", "--fail-on", "tag"
        )
        self.assertEqual(code, 1)

    def test_seed_unresolved_generated_owner_null_and_false(self):
        """Seed: unresolved generated synonym group returns owner: null and owner_resolved: false."""
        (self.root / "synonyms.json").write_text(
            json.dumps({
                "groups": [["unresolved-foo", "unresolved-bar"]],
                "generated_groups": [["unresolved-foo", "unresolved-bar"]],
                "manual_groups": [],
            }),
            encoding="utf-8",
        )
        checker = CandidateChecker(self.root)
        result = checker.check_candidates(["unresolved-foo"])
        item = result.candidates[0]
        self.assertEqual(len(item.relations.synonyms), 1)
        syn = item.relations.synonyms[0]
        self.assertEqual(syn["kind"], "generated")
        self.assertIsNone(syn["owner"])
        self.assertFalse(syn["owner_resolved"])

    def test_unparsed_concept_files_reported_in_inputs_status(self):
        """Corrupt concept notes are reported in unparsed_concept_files."""
        bad_note = self.root / "concepts" / "bad.md"
        bad_note.parent.mkdir(parents=True, exist_ok=True)
        bad_note.write_text("not yaml frontmatter at all and invalid format", encoding="utf-8")

        checker = CandidateChecker(self.root)
        status = checker.check_inputs_status()
        self.assertIn("unparsed_concept_files", status)
        self.assertIn("concepts/bad.md", status["unparsed_concept_files"])

    def test_japanese_quotes_emergence_parsing(self):
        """Japanese corner quotes 「」 are parsed for quoted_term."""
        sv_dir = self.root / "data" / "external" / "source_verify"
        sv_dir.mkdir(parents=True, exist_ok=True)
        (sv_dir / "doc.txt").write_text("電子冷却技術の進展について述べる。\n", encoding="utf-8")

        proposal_text = """### Candidate Proposal Pool
1. **`cooling-tech`** — 冷却技術 [`established`]
   - **(a) Adjacency**: Extends cooling.
   - **(b) Primary-Source Emergence**: 「電子冷却技術」 in doc.txt
   - **(c) Deduplication**: distinct.
"""
        parsed = parse_proposal_candidates(proposal_text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["quoted_term"], "電子冷却技術")
        self.assertEqual(parsed[0]["cited_target"], "doc.txt")

        v_check = check_verbatim_evidence(self.root, parsed[0]["cited_target"], parsed[0]["quoted_term"])
        self.assertTrue(v_check["verbatim_found"])
        self.assertEqual(v_check["parse_status"], "ok")

    def test_human_output_shows_excluded_count_and_parse_failed(self):
        """Human report shows excluded tag count and distinguishes parse_status=failed from taxonomy-gap."""
        write_doc(
            self.root,
            "concepts/spray-cooling.md",
            "type: Concept\ntitle: 'Spray Cooling'\ntags: [spray-cooling, cooling, dielectric-fluid]\n",
            "# Spray Cooling\n",
        )
        (self.root / "synonyms.json").write_text("{}", encoding="utf-8")
        prop_file = self.root / "proposal.md"
        prop_file.write_text(
            """### Candidate Proposal Pool
1. **`unquoted-cand`** — 引用失敗候補 [`niche`]
   - **(a) Adjacency**: Extends cooling.
   - **(b) Primary-Source Emergence**: unquoted mention without citation target
   - **(c) Deduplication**: distinct.
2. **`gap-cand`** — ギャップ候補 [`niche`]
   - **(a) Adjacency**: Extends cooling.
   - **(b) Primary-Source Emergence**: taxonomy-gap
   - **(c) Deduplication**: distinct.
""",
            encoding="utf-8",
        )
        code, out, _ = self.run_cli("candidate-check", self.root, "--proposal", str(prop_file))
        self.assertEqual(code, 0)
        self.assertIn("1 fixed vocabulary, 1 free, 1 excluded", out)
        self.assertIn("verbatim: parse-failed", out)
        self.assertIn("verbatim: taxonomy-gap", out)

    def test_candidate_check_works_unchanged_with_v03_entry_sources(self):
        """load_concept and candidate-check succeed on notes using v0.3 entry-form sources."""
        c_path = self.root / "concepts" / "spray-cooling.md"
        c_path.parent.mkdir(parents=True, exist_ok=True)
        c_path.write_text(
            "---\n"
            "type: Concept\n"
            "title: Spray Cooling\n"
            "tags: [spray-cooling, cooling]\n"
            "sources:\n"
            "  - id: arxiv-2406.06484\n"
            "    resource: https://arxiv.org/abs/2406.06484\n"
            "    x-okfkb-kind: preprint\n"
            "---\n"
            "# Spray Cooling\n",
            encoding="utf-8",
        )
        (self.root / "synonyms.json").write_text("{}", encoding="utf-8")
        from okf_kb_agent.wiki.model import load_concept
        concept = load_concept(c_path, self.root)
        self.assertEqual(concept.sources[0]["id"], "arxiv-2406.06484")

        checker = CandidateChecker(self.root)
        result = checker.check_candidates(["spray-cooling", "new-candidate"])
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(result.candidates[0].slug, "spray-cooling")
        self.assertEqual(
            result.candidates[0].relations.name_occupied,
            {"matched_name": "spray-cooling", "file": "concepts/spray-cooling.md"},
        )
        self.assertEqual(checker.check_inputs_status()["unparsed_concept_files"], [])


if __name__ == "__main__":
    unittest.main()
