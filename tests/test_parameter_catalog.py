"""Keep the RTSP VBR/Smart pilot catalog aligned with its runtime wiring."""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_ini_section(path, wanted):
    section = None
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == wanted and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


class RtspParameterCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "config/parameter-catalog.json").read_text(encoding="utf-8"))
        cls.entries = {entry["id"]: entry for entry in cls.catalog["parameters"]}

    def test_runtime_defaults_and_allowed_values_match_catalog(self):
        dist = read_ini_section(ROOT / "config/rtspserver.conf.dist", "0")
        self.assertEqual(dist["vbr"], str(self.entries["rtsp.vbr"]["default"]))
        self.assertEqual(dist["smart"], str(self.entries["rtsp.smart"]["default"]))
        self.assertEqual(self.entries["rtsp.vbr"]["allowed_values"], [0, 1])
        self.assertEqual(self.entries["rtsp.smart"]["allowed_values"], [0, 1, 2])
        self.assertFalse(self.entries["rtsp.vbr"]["secret"])
        self.assertFalse(self.entries["rtsp.smart"]["secret"])

    def test_source_and_validator_wiring_match_catalog(self):
        launch = (ROOT / "v3/linux66-sd/rtsp-launch.sh").read_text(encoding="utf-8")
        validation = (ROOT / "scripts/config-transaction.sh").read_text(encoding="utf-8")
        for key, kind in (("vbr", "bool"), ("smart", "smart_mode")):
            self.assertEqual(self.entries[f"rtsp.{key}"]["source"]["section"], "0")
            self.assertIn(f"r 0 vbr 0 smart", launch)
            self.assertRegex(validation, rf"tc_check_ini .* {key} {kind} .*\|\| return 1")
        self.assertIn('export RTSP_VBR="$RTSP_VBR_CONFIG" RTSP_SMART="$RTSP_SMART_CONFIG"', launch)

    def test_ui_state_and_json_use_canonical_keys(self):
        html = (ROOT / "www/settings.html").read_text(encoding="utf-8")
        state = (ROOT / "www/cgi-bin/state.cgi").read_text(encoding="utf-8")
        exchange = (ROOT / "www/cgi-bin/config_exchange.cgi").read_text(encoding="utf-8")
        self.assertIn('name="vbr0"', html)
        self.assertIn('"vbr":%s,"smart":%s', state)
        self.assertIn('.video.main.vbr', exchange)
        self.assertIn('.video.main.smart', exchange)

    def test_substream_overrides_and_legacy_policy_are_documented(self):
        source = (ROOT / "src/tc100rtsp/tc100_rtsp.c").read_text(encoding="utf-8")
        for key in ("RTSP_VBR_SUB", "RTSP_SMART_SUB"):
            self.assertIn(key, source)
        self.assertIn('sub && *sub ? "RTSP_SMART_SUB" : "RTSP_SMART"', source)
        self.assertIn("ignored-by-free-rtsp-encoder", self.catalog["legacy_metadata"]["runtime_effect"])


if __name__ == "__main__":
    unittest.main()
