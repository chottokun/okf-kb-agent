"""Tests for OKF v0.3 U9 (stamp-generated / stamp-verified) and U11 (trust_tier)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from okf_kb_agent.wiki.cli import main as cli_main
from okf_kb_agent.wiki.export import export_kb
from okf_kb_agent.wiki.frontmatter import FrontmatterError, parse_frontmatter
from okf_kb_agent.wiki.model import Concept, trust_tier
from okf_kb_agent.wiki.stamp import stamp_generated, stamp_verified
from okf_kb_agent.wiki.tooling import dispatch_tool


def _write_note(root: Path, rel: str, content: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestU9Stamping(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.wiki = Path(self.tmp.name) / "kb"
        self.wiki.mkdir()
        _write_note(self.wiki, "index.md", "# Index\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_stamp_generated_preserves_other_fields_and_body_and_is_idempotent(self) -> None:
        body = "# Flash Attention\n\nIO-aware exact attention.\n"
        original = (
            "---\n"
            "type: Concept\n"
            "title: Flash Attention\n"
            "tags:\n"
            "  - attention\n"
            "basis: external\n"
            "x-okfkb-custom: keep-me\n"
            "---\n"
            + body
        )
        note = _write_note(self.wiki, "concepts/flash-attention.md", original)

        rep1 = stamp_generated(
            self.wiki, ["concepts/flash-attention.md"], by="okf-glm-runner/1", at="2026-11-28"
        )
        self.assertEqual(rep1.changed, ["concepts/flash-attention.md"])
        self.assertEqual(rep1.unchanged, [])

        stamped_text = note.read_text(encoding="utf-8")
        meta, parsed_body = parse_frontmatter(stamped_text)
        self.assertEqual(parsed_body, body)
        self.assertEqual(meta["title"], "Flash Attention")
        self.assertEqual(meta["tags"], ["attention"])
        self.assertEqual(meta["basis"], "external")
        self.assertEqual(meta["x-okfkb-custom"], "keep-me")
        self.assertEqual(meta["generated"], {"by": "okf-glm-runner/1", "at": "2026-11-28"})

        # Idempotent re-run
        rep2 = stamp_generated(
            self.wiki, ["concepts/flash-attention.md"], by="okf-glm-runner/1", at="2026-11-28"
        )
        self.assertEqual(rep2.changed, [])
        self.assertEqual(rep2.unchanged, ["concepts/flash-attention.md"])
        self.assertEqual(note.read_text(encoding="utf-8"), stamped_text)

    def test_stamp_generated_defaults_at_to_today_utc_and_requires_by(self) -> None:
        note = _write_note(
            self.wiki,
            "concepts/a.md",
            "---\ntype: Concept\ntitle: A\n---\n# A\n",
        )
        with self.assertRaises(ValueError):
            stamp_generated(self.wiki, ["concepts/a.md"], by=None)
        with self.assertRaises(ValueError):
            stamp_generated(self.wiki, ["concepts/a.md"], by="   ")

        today_utc = datetime.now(timezone.utc).date().isoformat()
        rep = stamp_generated(self.wiki, ["concepts/a.md"], by="okf-opencode-runner/1")
        self.assertEqual(rep.at, today_utc)
        meta, _ = parse_frontmatter(note.read_text(encoding="utf-8"))
        self.assertEqual(meta["generated"], {"by": "okf-opencode-runner/1", "at": today_utc})

    def test_stamp_verified_appends_and_is_idempotent_without_dropping_existing(self) -> None:
        body = "# Paged Attention\n\nBody text.\n"
        note = _write_note(
            self.wiki,
            "concepts/paged-attention.md",
            (
                "---\n"
                "type: Concept\n"
                "title: Paged Attention\n"
                "verified:\n"
                "  by: shana/1\n"
                "  at: 2026-11-13\n"
                "---\n"
                + body
            ),
        )

        # Appending a new event preserves the existing bare-mapping event
        rep1 = stamp_verified(
            self.wiki,
            ["concepts/paged-attention.md"],
            by="process:okf-morning-audit",
            at="2026-11-28",
        )
        self.assertEqual(rep1.changed, ["concepts/paged-attention.md"])
        meta, parsed_body = parse_frontmatter(note.read_text(encoding="utf-8"))
        self.assertEqual(parsed_body, body)
        self.assertEqual(
            meta["verified"],
            [
                {"by": "shana/1", "at": "2026-11-13"},
                {"by": "process:okf-morning-audit", "at": "2026-11-28"},
            ],
        )

        # Re-stamping an identical by+at pair is a no-op
        rep2 = stamp_verified(
            self.wiki,
            ["concepts/paged-attention.md"],
            by="process:okf-morning-audit",
            at="2026-11-28",
        )
        self.assertEqual(rep2.changed, [])
        self.assertEqual(rep2.unchanged, ["concepts/paged-attention.md"])

        # Same actor on a different date appends
        rep3 = stamp_verified(
            self.wiki,
            ["concepts/paged-attention.md"],
            by="human:chottokun",
            at="2026-11-28",
        )
        self.assertEqual(rep3.changed, ["concepts/paged-attention.md"])
        meta3, _ = parse_frontmatter(note.read_text(encoding="utf-8"))
        self.assertEqual(len(meta3["verified"]), 3)

    def test_stamp_refuses_parse_failure_without_partial_writes(self) -> None:
        good_raw = "---\ntype: Concept\ntitle: Good\n---\n# Good\n"
        bad_raw = "---\ntype: Concept\nnot a valid yaml line\n---\n# Bad\n"
        good = _write_note(self.wiki, "concepts/good.md", good_raw)
        bad = _write_note(self.wiki, "concepts/bad.md", bad_raw)

        with self.assertRaises(FrontmatterError):
            stamp_generated(
                self.wiki,
                ["concepts/good.md", "concepts/bad.md"],
                by="okf-glm-runner/1",
                at="2026-11-28",
            )
        self.assertEqual(good.read_text(encoding="utf-8"), good_raw)
        self.assertEqual(bad.read_text(encoding="utf-8"), bad_raw)

        # CLI also exits non-zero and leaves files untouched
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            rc = cli_main([
                "stamp-verified",
                str(self.wiki),
                "--by",
                "process:okf-morning-audit",
                "concepts/good.md",
                "concepts/bad.md",
            ])
        self.assertEqual(rc, 1)
        self.assertEqual(good.read_text(encoding="utf-8"), good_raw)

    def test_cli_stamp_commands_json_output(self) -> None:
        _write_note(self.wiki, "concepts/x.md", "---\ntype: Concept\ntitle: X\n---\n# X\n")
        out1 = io.StringIO()
        with redirect_stdout(out1):
            rc1 = cli_main([
                "stamp-generated",
                str(self.wiki),
                "--by",
                "okf-glm-runner/1",
                "--at",
                "2026-11-28",
                "concepts/x.md",
                "--json",
            ])
        self.assertEqual(rc1, 0)
        data1 = json.loads(out1.getvalue())
        self.assertEqual(data1["changed"], ["concepts/x.md"])

        out2 = io.StringIO()
        with redirect_stdout(out2):
            rc2 = cli_main([
                "stamp-verified",
                str(self.wiki),
                "--by",
                "human:chottokun",
                "--at",
                "2026-11-28",
                "concepts/x.md",
                "--json",
            ])
        self.assertEqual(rc2, 0)
        data2 = json.loads(out2.getvalue())
        self.assertEqual(data2["changed"], ["concepts/x.md"])


class TestU11TrustTier(unittest.TestCase):
    def test_trust_tier_matrix(self) -> None:
        # 1. No generated + human event -> human-reviewed
        self.assertEqual(
            trust_tier({"verified": [{"by": "human:chottokun", "at": "2026-11-14"}]}),
            "human-reviewed",
        )
        # 2. No generated + machine event -> machine-confirmed
        self.assertEqual(
            trust_tier({"verified": [{"by": "process:okf-morning-audit", "at": "2026-11-20"}]}),
            "machine-confirmed",
        )
        # 3. Generated after last verified event -> unverified
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28"},
                "verified": [{"by": "human:chottokun", "at": "2026-11-27"}],
            }),
            "unverified",
        )
        # 4. Date-only equality counts as current
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28"},
                "verified": [{"by": "process:okf-morning-audit", "at": "2026-11-28"}],
            }),
            "machine-confirmed",
        )
        # Date-only verified vs UTC 00:00:00Z generated counts as equal
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28T00:00:00Z"},
                "verified": [{"by": "human:chottokun", "at": "2026-11-28"}],
            }),
            "human-reviewed",
        )
        # Date-only verified (00:00:00Z) vs later same-day generated timestamp -> stale -> unverified
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28T12:00:00Z"},
                "verified": [{"by": "human:chottokun", "at": "2026-11-28"}],
            }),
            "unverified",
        )
        # 5. Human among machine events (current) -> human-reviewed
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28"},
                "verified": [
                    {"by": "shana/1", "at": "2026-11-28"},
                    {"by": "human:chottokun", "at": "2026-11-28"},
                    {"by": "process:okf-morning-audit", "at": "2026-11-28"},
                ],
            }),
            "human-reviewed",
        )
        # 6. Stale human event + current machine event -> machine-confirmed
        self.assertEqual(
            trust_tier({
                "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28"},
                "verified": [
                    {"by": "human:chottokun", "at": "2026-11-20"},
                    {"by": "process:okf-morning-audit", "at": "2026-11-28"},
                ],
            }),
            "machine-confirmed",
        )
        # 7. Legacy verified_at alone without verified events -> unverified
        self.assertEqual(
            trust_tier({"verified_at": "2026-11-10", "x-okfkb-verified-at": "2026-11-10"}),
            "unverified",
        )

    def test_surface_in_concept_export_and_mcp_tooling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "kb"
            wiki.mkdir()
            _write_note(wiki, "index.md", "# Index\n")
            _write_note(
                wiki,
                "concepts/alpha.md",
                (
                    "---\n"
                    "type: Concept\n"
                    "title: Alpha Material\n"
                    "basis: external\n"
                    "generated:\n"
                    "  by: okf-glm-runner/1\n"
                    "  at: 2026-11-28\n"
                    "verified:\n"
                    "  - by: human:chottokun\n"
                    "    at: 2026-11-28\n"
                    "---\n"
                    "# Alpha Material\n\nThermal conductivity 500 W/mK.\n"
                ),
            )
            _write_note(
                wiki,
                "concepts/beta.md",
                (
                    "---\n"
                    "type: Concept\n"
                    "title: Beta Material\n"
                    "basis: external\n"
                    "x-okfkb-verified-at: 2026-11-08\n"
                    "---\n"
                    "# Beta Material\n\nThermal conductivity 200 W/mK.\n"
                ),
            )

            # Concept.as_dict()
            c = Concept(
                path=wiki / "concepts/alpha.md",
                rel="concepts/alpha.md",
                meta={
                    "generated": {"by": "okf-glm-runner/1", "at": "2026-11-28"},
                    "verified": [{"by": "human:chottokun", "at": "2026-11-28"}],
                },
            )
            self.assertEqual(c.as_dict()["trust_tier"], "human-reviewed")

            # export.py
            exported = export_kb(wiki)
            tiers = {item["slug"]: item["trust_tier"] for item in exported["concepts"]}
            self.assertEqual(tiers, {"alpha": "human-reviewed", "beta": "unverified"})

            # MCP tooling: okf_search and okf_context
            search_hits = dispatch_tool(
                "okf_search",
                {"wiki": "kb", "query": "thermal conductivity"},
                root=root,
            )
            search_tiers = {h["node"]: h["trust_tier"] for h in search_hits}
            self.assertEqual(
                search_tiers,
                {
                    "concepts/alpha.md": "human-reviewed",
                    "concepts/beta.md": "unverified",
                },
            )

            ctx = dispatch_tool(
                "okf_context",
                {"wiki": "kb", "query": "Alpha Material"},
                root=root,
            )
            ctx_tiers = {n["node"]: n["trust_tier"] for n in ctx["nodes"]}
            self.assertEqual(ctx_tiers.get("concepts/alpha.md"), "human-reviewed")
