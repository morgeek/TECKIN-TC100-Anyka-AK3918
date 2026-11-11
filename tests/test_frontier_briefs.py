"""The frontier-model briefs (docs/linux-port/frontier/brief.py) still build: functions found, under the size cap.

A renamed function or a moved block would otherwise only show up when the owner prepares a brief.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("frontier_brief", ROOT / "docs/linux-port/frontier/brief.py")
brief = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brief)


class FrontierBriefs(unittest.TestCase):
    def test_every_brief_builds_under_the_cap(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("| measure | value |\n|---|---|\n| night luma under IR | 100-102 |\n")
        for key, s in brief.SUBJECTS.items():
            b = brief.build(key, f.name if s["needs_data"] else None)
            self.assertLess(len(b), brief.MAX_CHARS, key)
            self.assertIn("## Rules for this task (read first)", b)
            self.assertEqual(b.count("```") % 2, 0, key)
            self.assertGreaterEqual(b.count("\n### "), len(s["parts"]), key)

    def test_data_is_required_and_capped(self):
        with self.assertRaises(SystemExit):
            brief.build("daynight")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("x" * (brief.MAX_DATA_CHARS + 1))
        with self.assertRaises(SystemExit):
            brief.build("daynight", f.name)


if __name__ == "__main__":
    unittest.main()
