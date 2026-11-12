"""IR-cut filter polarity (2026-11-12): on both test cameras the day pulse is GPIO 592 and the night pulse 593.

With the old default (day 593) the .11 kept the filter in front of the sensor at night: a dark picture under IR, and
switching the IR LEDs off changed nothing. The board profile and the setconf fallback must agree, and a boot.conf
IRCUT_* line must still win (cameras wired the other way).
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASH = shutil.which("busybox")



class IrcutPolarity(unittest.TestCase):
    def test_board_profile_and_fallback_agree(self):
        board = (ROOT / "v3/board/tc100-f23-rtl8188fu.conf").read_text(encoding="utf-8")
        self.assertRegex(board, r"(?m)^IRCUT_DAY_GPIO=592$")
        self.assertRegex(board, r"(?m)^IRCUT_NIGHT_GPIO=593$")
        self.assertIn("day=${day:-592}; night=${night:-593};", (ROOT / "bin/setconf").read_text(encoding="utf-8"))

    @unittest.skipUnless(ASH, "needs busybox")
    def test_pulses(self):
        s = (ROOT / "bin/setconf").read_text(encoding="utf-8")
        funcs = "\n".join(re.search(r"^" + n + r"\(\)\s*\{.*?^}", s, re.M | re.S).group(0) for n in ("ircut",))
        kvbd = "\n".join(l for l in s.split("\n") if l.startswith(("kv()", "bd()")))
        with tempfile.TemporaryDirectory() as t:
            boot, board = Path(t, "boot.conf"), Path(t, "board.conf")
            board.write_text((ROOT / "v3/board/tc100-f23-rtl8188fu.conf").read_text(encoding="utf-8"))

            def run(boot_text, v, board_path=board):
                boot.write_text(boot_text)
                code = (kvbd.replace("/mnt/config/boot.conf", str(boot)).replace("/tmp/board.conf", str(board_path))
                        + '\ngpio_out() { echo "$1=$2"; }\nusleep() { :; }\n'
                        + funcs.replace("/tmp/.ircut.lock", str(Path(t, "lock"))) + f"\nircut {v}")
                r = subprocess.run([ASH, "ash", "-c", code], capture_output=True, text=True, timeout=20)
                return [l for l in r.stdout.split() if l.endswith("=1")]

            self.assertEqual(run("", 1), ["592=1"])        # day: filter in
            self.assertEqual(run("", 0), ["593=1"])        # night: filter out
            self.assertEqual(run("", 1, Path(t, "none")), ["592=1"])     # no board file: same fallback
            self.assertEqual(run("IRCUT_DAY_GPIO=593\nIRCUT_NIGHT_GPIO=592\n", 1), ["593=1"])   # boot.conf wins
            self.assertEqual(run("IRCUT_DAY_GPIO=593\nIRCUT_NIGHT_GPIO=592\n", 0), ["592=1"])


if __name__ == "__main__":
    unittest.main()
