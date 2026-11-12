"""Keep every copy of the day / night settings aligned with config/parameter-catalog.json (family daynight, item 64).

The same keys of /mnt/config/daynight.conf are read, written, shown, exported and checked in many places: the C
supervisor and the shell daemon (defaults), the Day/night page (state.cgi and the form handler), the configuration
export / import and its validation. A default or a bound changed in one of them, or a key one of them forgets, fails here.
"""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class DaynightCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat = json.loads(read("config/parameter-catalog.json"))
        cls.cat = cat
        cls.p = {e["source"]["key"]: e for e in cat["parameters"] if e.get("family") == "daynight"}
        cls.c = read("src/supervisord/supervisord.c")
        cls.sh = read("scripts/auto-night-daemon.sh")
        cls.state = read("www/cgi-bin/state.cgi")
        cls.video = read("scripts/action.d/video.sh")
        cls.exch = read("www/cgi-bin/config_exchange.cgi")
        cls.tx = read("scripts/config-transaction.sh")
        cls.html = read("www/settings.html")
        cls.launch = read("v3/linux66-sd/rtsp-launch.sh")

    def ints(self):
        return {k: e for k, e in self.p.items() if e["type"] == "int"}

    def test_family_is_complete(self):
        self.assertIn("daynight", self.cat["families"])
        self.assertEqual(len(self.p), 20)
        for k, e in self.p.items():
            self.assertEqual(e["id"], "daynight." + k.lower())
            self.assertEqual(e["source"]["path"], "/mnt/config/daynight.conf")
            self.assertTrue(e["label"]["en"] and e["label"]["fr"], k)
            if e["type"] == "int":
                lo, hi = e["range"]
                self.assertTrue(lo <= e["default"] <= hi, k)
            else:
                self.assertIn(e["default"], e["allowed_values"], k)

    def test_daemon_defaults(self):
        cname = {"LUMA_NIGHT": "THRESHOLD_NIGHT", "LUMA_DAY": "THRESHOLD_DAY"}
        for k, e in self.p.items():
            if "src/supervisord/supervisord.c" not in e["read_by"] or e["type"] != "int":
                continue
            n = cname.get(k, k)
            self.assertRegex(self.c, rf"\b{n} = {e['default']}\b", "supervisord.c " + k)
            self.assertRegex(self.sh, rf"(?m)^{n}={e['default']}$", "auto-night-daemon.sh " + k)
        self.assertIn("static int DAYNIGHT_SOURCE = SRC_LUMA;", self.c)
        self.assertEqual(self.p["DAYNIGHT_SOURCE"]["default"], "luma")
        self.assertRegex(self.sh, r"(?m)^DAYNIGHT_SOURCE=luma$")
        self.assertEqual(self.p["DAYNIGHT_SOURCE"]["allowed_values"], ["luma", "ae", "isp", "vendor"])
        self.assertIn('src_name[] = { "luma", "ae", "isp", "vendor" }', self.c)
        self.assertIn("static int IR_LED_MODE;	/* 0 auto, 1 off, 2 force */", self.c)
        self.assertRegex(self.sh, r"(?m)^IR_LED_MODE=auto$")

    def test_daemons_accept_the_whole_range(self):
        # the daemons skip a value they do not accept: they must take everything the writers can store
        c_bounds = {"LUMA_NIGHT": 255, "LUMA_DAY": 255, "NIGHT_HOLD": 3600, "DAY_HOLD": 3600, "MIN_SWITCH": 3600}
        for k, e in self.ints().items():
            if "src/supervisord/supervisord.c" not in e["read_by"]:
                continue
            self.assertIn(f'"{k}"', self.c, k)
            self.assertIn(k, self.sh, k)
            self.assertLessEqual(e["range"][1], c_bounds.get(k, 999999999), k)
        self.assertIn("dec(v) < 1 || dec(v) > 3600", self.c)

    def test_page_state_defaults(self):
        for k, e in self.p.items():
            if not e["state_json"]:
                continue
            self.assertIn(f'"{e["state_json"]}":', self.state, k)
            if e["type"] in ("int", "bool") and k != "LOWLIGHT_FPS_VALUE":
                self.assertRegex(self.state, rf"cfg_int _dn_\w+ {k} {e['default']}\b", "state.cgi " + k)
        self.assertIn("*) _dn_src=luma ;;", self.state)
        self.assertIn("cfg_int _dn_lv LOWLIGHT_FPS_VALUE 10; case \"$_dn_lv\" in 15|20) ;; *) _dn_lv=10 ;; esac", self.state)
        self.assertIn("*) _dn_irm=auto ;;", self.state)

    def test_form_handler_bounds_and_keys(self):
        for k, e in self.ints().items():
            if k in ("AWB_DAY_CNT", "AWB_NIGHT_CNT", "VENDOR_LOCK", "IR_LED_REST"):
                continue
            lo, hi = e["range"]
            src = r"\$\{_irs\}" if k == "IR_LED_MAX_ON" else rf"\$\{{F_\w+:-\$\(_dn_get {k}\)\}}"
            self.assertRegex(self.video, rf'sanitize_int_range "{src}" {lo} {hi} {e["default"]}\)', "video.sh " + k)
        # every key survives a save of the page: written by the printf, or kept as it is
        written = re.search(r"printf '(LUMA_NIGHT=.*?)' \\", self.video).group(1)
        kept = re.search(r"for _k in ([A-Z_ ]+); do\n\s+_v=\$\(_dn_get", self.video).group(1).split()
        for k in self.p:
            self.assertTrue(f"{k}=%s" in written or k in kept, "a page save drops " + k)
        self.assertIn("*) _ds=luma ;;", self.video)
        self.assertIn("_ns0=${_ns0:-1}", self.video)
        self.assertIn("_lf0=${_lf0:-1}", self.video)
        self.assertIn("_n7200=${_n7200:-0}", self.video)
        self.assertIn("*) _lv0=10 ;;", self.video)
        self.assertIn("_irm0=${_irm0:-auto}", self.video)

    def test_page_fields(self):
        for k, e in self.p.items():
            f = e["ui_field"]
            if not f:
                continue
            m = re.search(rf'<(input|select)[^>]*name="{f}"[^>]*>', self.html)
            self.assertTrue(m, "settings.html " + f)
            if e["type"] == "int" and k != "IR_LED_MAX_ON":
                lo, hi = e["range"]
                self.assertIn(f'min="{lo}"', m.group(0), f)
                self.assertIn(f'max="{hi}"', m.group(0), f)
        m = re.search(r'<input[^>]*name="dn_ir_max_h"[^>]*>', self.html).group(0)
        self.assertIn('max="48"', m)
        self.assertEqual(self.p["IR_LED_MAX_ON"]["range"][1], 48 * 3600)

    def validator(self, e):
        if e["type"] == "int":
            return "u:%d:%d" % tuple(e["range"])
        if e["type"] == "bool":
            return "bool"
        return {"DAYNIGHT_SOURCE": "dn_source", "LOWLIGHT_FPS_VALUE": "lowlight_fps_value",
                "IR_LED_MODE": "ir_led_mode"}[e["source"]["key"]]

    def test_export_and_validation(self):
        for k, e in self.p.items():
            v = self.validator(e)
            self.assertIn(f'row("daynight.conf";"flat";"root";"{k}";"{v}";"general";{e["export_json"]}),', self.exch, k)
            self.assertRegex(self.tx, rf'tc_check_flat "\$_tc_file" {k} {re.escape(v)} "\$_tc_rel" \|\| return 1', k)
        for hi, lo in self.cat["daynight_pairs"]:
            self.assertIn(f'tc_check_pair "$_tc_file" {hi} {lo} "$_tc_rel" || return 1', self.tx)

    def test_video_launch_defaults(self):
        self.assertIn('[ "$(dnc NIGHT_STYLE)" = 0 ] || export RTSP_NIGHTSTYLE=1', self.launch)
        self.assertIn('[ "$(dnc LOWLIGHT_FPS)" = 0 ] || export RTSP_LOWLIGHT_FPS=1', self.launch)
        self.assertIn('[ "$(dnc NIGHT_720P)" = 1 ]', self.launch)
        self.assertIn("case \"$(dnc LOWLIGHT_FPS_VALUE)\" in 15|20)", self.launch)
        self.assertEqual(self.p["NIGHT_STYLE"]["default"], 1)
        self.assertEqual(self.p["LOWLIGHT_FPS"]["default"], 1)
        self.assertEqual(self.p["NIGHT_720P"]["default"], 0)
        self.assertEqual(self.p["LOWLIGHT_FPS_VALUE"]["allowed_values"], [10, 15, 20])


if __name__ == "__main__":
    unittest.main()
