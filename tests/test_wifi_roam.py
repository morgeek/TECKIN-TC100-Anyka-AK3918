"""Item 40: scripts/wifi-roam.sh: two weak checks -> scan -> roam to a BSS of the same SSID at least 15 dB stronger;
nothing when the signal is fine, no better access point, or within the hold time."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']

RESULTS = ('bssid / frequency / signal level / flags / ssid\n'
           'aa:bb:cc:00:00:01\t2437\t-80\t[WPA2-PSK-CCMP][ESS]\tHome\n'
           'aa:bb:cc:00:00:02\t2412\t-58\t[WPA2-PSK-CCMP][ESS]\tHome\n'
           'aa:bb:cc:00:00:03\t2462\t-40\t[WPA2-PSK-CCMP][ESS]\tNeighbour\n')


class WifiRoam(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        (self.t / 'results').write_text(RESULTS)
        (self.t / 'wpa_cli').write_text(
            '#!/bin/sh\necho "$*" >> %s/calls\ncase "$3" in\n'
            '  status) printf "bssid=AA:BB:CC:00:00:01\\nssid=Home\\nwpa_state=COMPLETED\\n" ;;\n'
            '  scan_results) cat %s/results ;;\nesac\n' % (self.t, self.t))
        (self.t / 'wpa_cli').chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def once(self, dbm, now):
        env = dict(os.environ, WRO_STATE=str(self.t / 'st'), WRO_WPA_CLI=str(self.t / 'wpa_cli'), WRO_DBM=str(dbm),
                   WRO_NOW=str(now), WRO_SCAN_WAIT='0')
        subprocess.run(SH + [str(ROOT / 'scripts/wifi-roam.sh'), 'once'], env=env, capture_output=True, timeout=10)
        c = self.t / 'calls'
        return c.read_text().splitlines() if c.exists() else []

    def test_roams_after_two_weak_checks_then_holds(self):
        self.assertEqual(self.once(-80, 100), [])                         # first weak check: wait
        calls = self.once(-80, 160)
        self.assertIn('-i wlan0 roam aa:bb:cc:00:00:02', calls)           # same SSID, 22 dB better; not the neighbour
        n = len(calls)
        self.once(-80, 220); self.once(-80, 280)
        self.assertEqual(len(self.once(-80, 300)), n)                     # hold: nothing within 10 minutes

    def test_nothing_when_fine_or_none_better(self):
        self.assertEqual(self.once(-60, 100), [])
        self.assertEqual(self.once(-60, 160), [])
        (self.t / 'results').write_text(RESULTS.replace('-58', '-70'))   # only 10 dB better
        self.once(-80, 200)
        calls = self.once(-80, 260)
        self.assertFalse(any(' roam ' in c for c in calls))

    def test_registered_by_autorun(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('on "$BC_WIFI_ROAM" && sh /mnt/scripts/housekeeper.sh job add wifi-roam bg 60 120 -', a)


if __name__ == '__main__':
    unittest.main()
