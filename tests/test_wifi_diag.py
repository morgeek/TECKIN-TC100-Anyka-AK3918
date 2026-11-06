"""Audit 2026-11-06, W1: scripts/wifi-diag.sh tells a stalled camera, a frozen receive path and a frozen USB host apart
during the Wi-Fi ping losses. It must stay read-only (no serial console: nothing may risk the link) and RAM-only."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
SCRIPT = ROOT / 'scripts/wifi-diag.sh'


class WifiDiag(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.sys = self.t / 'stat'; self.sys.mkdir()
        for k, v in (('rx_packets', 1000), ('tx_packets', 500), ('rx_dropped', 3)):
            (self.sys / k).write_text('%d\n' % v)
        (self.t / 'intr').write_text('           CPU0\n 17:     123456  ak-intc  usb-otg\n 18:  99  ak-intc  ak_venc\n')
        (self.t / 'uptime').write_text('8000.25 100.00\n')
        (self.t / 'station').write_text('Station 00:11:22:33:44:55 (on wlan0)\n\tbeacon rx:\t4242\n\ttx retries:\t0\n')
        (self.t / 'ping').write_text('64 bytes from 192.0.2.1: seq=0 ttl=64 time=12.345 ms\n')

    def tearDown(self):
        shutil.rmtree(self.t)

    def env(self, **kw):
        e = dict(os.environ, WD_LOG=str(self.t / 'log'), WD_PID=str(self.t / 'pid'), WD_SYS=str(self.sys),
                 WD_INTR=str(self.t / 'intr'), WD_UPTIME=str(self.t / 'uptime'), WD_STATION=str(self.t / 'station'),
                 WD_PING=str(self.t / 'ping'), WD_SLEEP='0', WD_GW='192.0.2.1')
        e.update(kw)
        return e

    def test_run_writes_one_line_a_second_and_stops(self):
        r = subprocess.run(SH + [str(SCRIPT), 'run', '3', 'ping'], env=self.env(), capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in (self.t / 'log').read_text().splitlines() if not l.startswith('#')]
        self.assertEqual(len(lines), 3)
        f = lines[0].split()
        self.assertEqual(f, ['8000250', '0', '1000', '500', '3', '123456', '4242', '12'])
        self.assertEqual(lines[1].split()[6], '-')          # beacons every 5 s only
        self.assertFalse((self.t / 'pid').exists())          # pid file removed at the end
        self.assertIn('gw=192.0.2.1', (self.t / 'log').read_text())

    def test_summary_names_stalls_frozen_receive_and_lost_pings(self):
        rows = ['# wifi-diag start 2026-11-06 secs=10 gw=192.0.2.1', '# up_ms gap_ms ...']
        rx, usb = 100, 5000
        for i in range(10):
            gap = 900 if i == 2 else 0
            if not 4 <= i <= 7:
                rx += 10; usb += 600            # receive and USB frozen from 4 to 7
            ping = '-' if i in (5, 6) else '3'
            rows.append('%d %d %d 50 0 %d - %s' % (1000 * (i + 1), gap, rx, usb, ping))
        (self.t / 'log').write_text('\n'.join(rows) + '\n')
        r = subprocess.run(SH + [str(SCRIPT), 'summary'], env=self.env(), capture_output=True, text=True, timeout=30)
        out = r.stdout
        self.assertIn('camera stalled 900 ms', out)
        self.assertRegex(out, r'receive frozen [34] s')
        self.assertRegex(out, r'USB interrupts frozen [34] s')
        self.assertEqual(out.count('ping lost'), 2)
        self.assertIn('lost 2', out)

    def test_read_only_and_ram_only(self):
        src = re.sub(r'(?m)^\s*#.*$', '', SCRIPT.read_text())
        for bad in ('wpa_cli', 'ip link', 'ifconfig', 'iw dev wlan0 set', 'iwconfig', 'rmmod', 'modprobe',
                    'wifi-apply', 'wifi-recover', 'reboot', 'rewrite_config', '/mnt/config', '/mnt/sd', 'unbind'):
            self.assertNotIn(bad, src, bad)
        self.assertIn('LOG=${WD_LOG:-/tmp/wifi-diag.log}', SCRIPT.read_text())
        self.assertIn('[ "$_secs" -gt 86400 ] && _secs=86400', SCRIPT.read_text())   # always stops by itself


if __name__ == '__main__':
    unittest.main()
