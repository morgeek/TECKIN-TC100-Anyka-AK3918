"""Item 32: the Wi-Fi placement aid: the LED blink period from the signal (scripts/wifi-aim.sh), started by autorun with
WIFI_AIM=1, and the dashboard colour of the signal."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def period(d):
    return subprocess.run(SH + [str(ROOT / 'scripts/wifi-aim.sh'), 'period', d], capture_output=True, text=True).stdout.strip()


class WifiAim(unittest.TestCase):
    def test_period_follows_the_signal(self):
        got = [period(d) for d in ('-30', '-50', '-60', '-70', '-85', '-100', '', 'x')]
        self.assertEqual(got, ['2', '2', '7', '12', '20', '20', '0', '0'])

    def test_wiring(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('on "$BC_WIFI_AIM" && ( exec sh /mnt/scripts/wifi-aim.sh run )', a)
        self.assertIn('WIFI_AIM=0', (ROOT / 'config/boot.conf.dist').read_text())
        js = (ROOT / 'src/webui/index/47-dashboard.js').read_text()
        self.assertIn('lvl >= -60 ? "#2e7d32" : lvl >= -70 ? "#b26a00" : "#c62828"', js)


if __name__ == '__main__':
    unittest.main()
