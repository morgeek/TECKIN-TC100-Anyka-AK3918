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

    def test_optimisation_briefs_build_with_their_measurements(self):
        # the measured summaries of 2026-11-11 ship with the repository: the brief sent is the one rebuilt here
        for key, must in (("rtsp", ("aud_pump", "adsp_sample", "snd_main", "rtp_out", "does not depend on the frame rate")),
                          ("background", ("wifi-quality.sh", "health-snapshot.sh", "collect_slow_health_metrics",
                                          "new processes per minute"))):
            data = ROOT / f"docs/linux-port/frontier/data/{key}-2026-11-11.md"
            self.assertLess(len(data.read_text(encoding="utf-8")), brief.MAX_DATA_CHARS, key)
            self.assertTrue(brief.SUBJECTS[key]["needs_data"], key)
            with self.assertRaises(SystemExit):
                brief.build(key)
            b = brief.build(key, str(data))
            for m in must:
                self.assertIn(m, b, key)


if __name__ == "__main__":
    unittest.main()
