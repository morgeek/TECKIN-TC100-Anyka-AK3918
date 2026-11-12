"""Keep every copy of the live image tuning settings aligned with config/parameter-catalog.json (family image, item 64).

/mnt/config/isp_tune.conf is read by tc100_rtsp, written by the Image page (video.sh), MQTT and Home Assistant (both
bridges), the configuration import, and checked by isp-tune.sh and config-transaction.sh. A key one of them forgets
(as Noise reduction was missing from MQTT at first) or a bound that differs fails here.
"""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class ImageCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat = json.loads(read("config/parameter-catalog.json"))
        cls.p = {e["source"]["key"]: e for e in cat["parameters"] if e.get("family") == "image"}
        cls.eff = [k for k, e in cls.p.items() if e["type"] == "effect"]
        cls.rtsp = read("src/tc100rtsp/tc100_rtsp.c")
        cls.tune = read("scripts/isp-tune.sh")
        cls.video = read("scripts/action.d/video.sh")
        cls.html = read("www/settings.html")
        cls.save = read("src/webui/index/60-settings-save.js")
        cls.exch = read("www/cgi-bin/config_exchange.cgi")
        cls.tx = read("scripts/config-transaction.sh")
        cls.dist = read("config/isp_tune.conf.dist")
        cls.bridge = read("scripts/mqtt-bridge.sh")
        cls.mqttd = read("src/mqttd/mqttd.c")

    def test_family(self):
        self.assertEqual(len(self.p), 13)
        self.assertEqual(self.eff, ["BRIGHTNESS", "CONTRAST", "SATURATION", "SHARPNESS", "DENOISE", "HUE"])
        for k, e in self.p.items():
            self.assertEqual(e["id"], "image." + k.lower())
            self.assertTrue(e["label"]["en"] and e["label"]["fr"], k)

    def test_shell_key_lists_and_defaults(self):
        tune_keys = re.search(r'ISP_TUNE_KEYS="([A-Z_ ]+)"', self.tune).group(1).split()
        mask_keys = re.search(r'ISP_MASK_KEYS="([A-Z_0-9 ]+)"', self.tune).group(1).split()
        self.assertEqual(sorted(tune_keys + mask_keys), sorted(self.p))
        self.assertIn("    " + "|".join(self.eff) + ")\n", self.tune)
        for k, e in self.p.items():
            if e["type"] == "rect":     # no mask by default: the .dist only shows an example, commented out
                self.assertNotRegex(self.dist, rf"(?m)^{k}=.")
                continue
            self.assertRegex(self.dist, rf"(?m)^{k}={re.escape(str(e['default']))}$", "isp_tune.conf.dist " + k)

    def test_tc100_rtsp_reads_and_bounds(self):
        var = {"BRIGHTNESS": "p_bri", "CONTRAST": "p_con", "SATURATION": "p_sat", "SHARPNESS": "p_sharp",
               "DENOISE": "p_dnr", "HUE": "p_hue"}
        for k, e in self.p.items():
            if e["type"] == "rect":
                continue
            self.assertIn(f'cfg_get(fn[1], "", "{k}", v, sizeof v)', self.rtsp, k)
        self.assertIn('snprintf(k, sizeof k, "MASK%d", i + 1);', self.rtsp)
        for k in self.eff:
            v = var[k]
            self.assertIn(f"{v} = {v} < -50 ? -50 : {v} > 50 ? 50 : {v};", self.rtsp, "tc100_rtsp bound " + k)
        status = re.search(r'"(BRIGHTNESS=%d\\n.*?)"', self.rtsp).group(1)
        for k in self.eff + ["POWER_HZ"]:
            self.assertIn(k + "=", status, "isp_tune.status " + k)

    def test_page_form_and_save(self):
        for k, e in self.p.items():
            f = e["ui_field"]
            self.assertRegex(self.html, rf'name="{f}"', "settings.html " + f)
            self.assertIn(f'{k}) _it_in="$F_{f}" ;;', self.video, "video.sh " + k)
            if e["type"] == "effect":
                m = re.search(rf'<input[^>]*name="{f}"[^>]*>', self.html).group(0)
                self.assertIn('min="-50"', m)
                self.assertIn('max="50"', m)
                self.assertIn(f'[ -n "${{F_{f}+x}}" ] && isp_tune_set {k} "$F_{f}"', self.video, k)
                self.assertIn(f'{f}: "{k}"', self.save, "60-settings-save.js " + k)

    def test_export_and_validation(self):
        loop = re.search(r"for _tc_k in ([A-Z ]+); do\n\s+tc_check_flat \"\$_tc_file\" \"\$_tc_k\" isp_effect", self.tx).group(1).split()
        self.assertEqual(loop, self.eff)
        masks = re.search(r"for _tc_k in (MASK[0-9 MASK]+); do\n\s+tc_check_flat \"\$_tc_file\" \"\$_tc_k\" isp_mask ", self.tx).group(1).split()
        self.assertEqual(masks, ["MASK1", "MASK2", "MASK3", "MASK4"])
        for k, e in self.p.items():
            self.assertIn(f'row("isp_tune.conf";"flat";"root";"{k}";"{e["validator"]}";"general";{e["export_json"]}),', self.exch, k)
            if e["type"] not in ("effect", "rect"):
                self.assertIn(f'tc_check_flat "$_tc_file" {k} {e["validator"]} "$_tc_rel" || return 1', self.tx, k)

    def test_mqtt_and_home_assistant(self):
        cmds = re.search(r"\n    (isp_brightness\|[a-z_|]+)\)\n", self.bridge).group(1).split("|")
        want = [e["mqtt_command"] for e in self.p.values() if e["mqtt_command"]]
        self.assertEqual(sorted(cmds), sorted(want))
        sh_list = re.search(r"for isp_key in ([a-z_ ]+); do", self.bridge).group(1).split()
        c_list = re.findall(r'\{ "([a-z_]+)", "[^"]+", "mdi:[^"]+", "\{\{ value_json\.conf\.[A-Z_]+', self.mqttd)
        sliders = [k.lower() for k in self.eff] + ["exposure_max_pct"]
        self.assertEqual(sh_list, sliders)
        self.assertEqual(c_list, sliders)
        for k in self.eff:
            n = k.lower()
            self.assertRegex(self.bridge, rf"\n\s+{n}\) isp_name=\"[^\"]+\"; isp_ic=\"[^\"]+\"; isp_min=-50; isp_max=50;", n)
            self.assertRegex(self.mqttd, rf'\{{ "{n}", "[^"]+", "mdi:[^"]+", "\{{\{{ value_json\.conf\.{k}[^"]*\}}\}}", -50, 50, 1 \}}', n)


if __name__ == "__main__":
    unittest.main()
