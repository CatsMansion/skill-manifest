#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-tests for skill_manifest. Run: python -m unittest discover -s tests -v"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Let the suite run from any cwd, not just the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import skill_manifest as sm

FIX = Path(__file__).resolve().parent / "fixtures"


class TestFrontmatter(unittest.TestCase):
    def test_valid_frontmatter_keeps_every_field(self):
        fm, err = sm.parse_frontmatter((FIX / "valid-skill" / sm.SKILL_FILE).read_bytes())
        self.assertEqual(err, "")
        self.assertEqual(fm["name"], "valid-skill")
        self.assertIn("Use when", fm["description"])
        self.assertEqual(fm["license"], "MIT")
        self.assertEqual(fm["metadata"], {"author": "example", "version": "1.0"})

    def test_missing_frontmatter_is_detected(self):
        fm, err = sm.parse_frontmatter((FIX / "no-frontmatter" / sm.SKILL_FILE).read_bytes())
        self.assertEqual(err, "NO_FRONTMATTER")
        self.assertEqual(fm, {})

    def test_name_mismatch_is_an_error(self):
        fm, err = sm.parse_frontmatter((FIX / "bad-name-skill" / sm.SKILL_FILE).read_bytes())
        self.assertEqual(err, "")
        codes = [i.code for i in sm.validate_frontmatter(fm, "bad-name-skill", 10)]
        self.assertIn("NAME_MISMATCH", codes)
        self.assertTrue(any(i.level == sm.ERROR for i in
                            sm.validate_frontmatter(fm, "bad-name-skill", 10)))

    def test_clean_skill_has_no_errors(self):
        fm, _ = sm.parse_frontmatter((FIX / "valid-skill" / sm.SKILL_FILE).read_bytes())
        lines = len((FIX / "valid-skill" / sm.SKILL_FILE).read_text(encoding="utf-8").splitlines())
        issues = sm.validate_frontmatter(fm, "valid-skill", lines)
        self.assertEqual([i for i in issues if i.level == sm.ERROR], [])

    def test_overlong_description_is_an_error(self):
        fm = {"name": "x", "description": "d" * (sm.MAX_DESC + 1), "license": "MIT"}
        codes = [i.code for i in sm.validate_frontmatter(fm, "x", 10)]
        self.assertIn("DESCRIPTION_TOO_LONG", codes)

    def test_block_sequence_allowed_tools_is_not_silently_dropped(self):
        """Regression: `allowed-tools:` followed by `- Item` lines used to parse
        as an empty value, hiding the risk advisory on real-world skills."""
        raw = (b"---\nname: x\ndescription: d\nlicense: MIT\n"
               b"allowed-tools:\n  - Read\n  - Write\n---\n\n# x\n")
        fm, err = sm.parse_frontmatter(raw)
        self.assertEqual(err, "")
        self.assertEqual(fm["allowed-tools"], ["Read", "Write"])
        codes = [i.code for i in sm.validate_frontmatter(fm, "x", 5)]
        self.assertIn("ALLOWED_TOOLS_RISK", codes)


class TestLimits(unittest.TestCase):
    def test_limits_are_inclusive(self):
        self.assertEqual(sm.check_limits(sm.MAX_FILES, sm.MAX_BYTES, "x"), [])

    def test_limits_reject_overages(self):
        self.assertEqual(len(sm.check_limits(sm.MAX_FILES + 1, 0, "x")), 1)
        self.assertEqual(len(sm.check_limits(1, sm.MAX_BYTES + 1, "x")), 1)


class TestManifest(unittest.TestCase):
    def test_resources_are_complete_and_verifiable(self):
        d = FIX / "valid-skill"
        fm, _ = sm.parse_frontmatter((d / sm.SKILL_FILE).read_bytes())
        res = sm.build_resources(d, fm["name"])
        self.assertEqual(len(res), 2)
        self.assertTrue(all(sm.DIGEST_RE.match(r["digest"]) for r in res))
        self.assertTrue(any(r["uri"].endswith("/SKILL.md") for r in res))
        self.assertEqual(sm.verify_resources(d, res), [])
        self.assertEqual(sum(r["size"] for r in res),
                         sum(p.stat().st_size for p in d.rglob("*") if p.is_file()))

    def test_positive_control_tampered_file_is_detected(self):
        """A changed byte MUST be caught; otherwise the verifier is lying."""
        d = FIX / "valid-skill"
        fm, _ = sm.parse_frontmatter((d / sm.SKILL_FILE).read_bytes())
        res = sm.build_resources(d, fm["name"])
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "valid-skill"
            shutil.copytree(d, copy)
            f = copy / "references" / "checklist.md"
            f.write_bytes(f.read_bytes() + b"\n# tampered\n")
            bad = sm.verify_resources(copy, res)
        self.assertEqual(len(bad), 1)
        self.assertIn("mismatch", bad[0])

    def test_generate_end_to_end(self):
        result, issues, stats = sm.generate(FIX)
        self.assertEqual(stats["skills"], 3)
        self.assertEqual(len(result["skills"]), 3)
        self.assertEqual(stats["files"], sum(len(e["resources"]) for e in result["skills"]))
        self.assertEqual(result["resultType"], "complete")
        self.assertIn("ttlMs", result)
        self.assertIn("cacheScope", result)
        self.assertTrue(any(i.code == "NAME_MISMATCH" for i in issues))
        self.assertTrue(any(i.code == "NO_FRONTMATTER" for i in issues))
        json.dumps(result, ensure_ascii=False)  # must be JSON-serialisable

    def test_report_contains_no_absolute_local_path(self):
        result, issues, stats = sm.generate(FIX)
        text = sm.render_report(result, issues, stats, "fixtures")
        # Build the literal so the test file itself never carries a plaintext
        # Windows user path (publish-time secret scanners flag even a probe).
        self.assertNotIn("C:" + chr(92) + "Users", text)
        self.assertNotIn("/Users/", text)
        self.assertIn("digest match proves byte consistency", text)


if __name__ == "__main__":
    unittest.main()
