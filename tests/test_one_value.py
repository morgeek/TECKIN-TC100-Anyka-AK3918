"""One value, one definition: Wi-Fi signal (scripts/wifi-signal.sh), RAM (MemAvailable), SD card health
(sdinfo-sd.sh writes /tmp/sd-health, sd-diag.sh reads it), stability.csv on the card."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
HDR = ('Inter-| sta-|   Quality        |   Discarded packets\n'
       ' face | tus | link level noise |  nwid  crypt\n')


def sh(code, env=None):
    return subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, timeout=20,
                          env=dict(os.environ, **(env or {})))


def text(path):
    return (ROOT / path).read_text(encoding='utf-8', errors='replace')


class WifiSignal(unittest.TestCase):

    def read(self, body, arg=''):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'wireless'
            f.write_text(HDR + body)
            r = sh('. %s; WIFI_PROC_FILE=%s; wifi_signal_read %s; echo "rc=$? [$WIFI_DBM] [$WIFI_QUAL] [$WIFI_IF]"'
                   % (ROOT / 'scripts/wifi-signal.sh', f, arg))
            return r.stdout.strip()

    def test_levels(self):
        self.assertEqual(self.read(' wlan0: 0000   44.  -66.  -256        0      0\n'), 'rc=0 [-66] [44] [wlan0]')
        # the RTL8188FU driver's -256 is "no reading", never a level; neither is an idle 0 or a 0-100 value
        self.assertEqual(self.read(' wlan0: 0000   44.  -256.  -256\n'), 'rc=0 [] [44] [wlan0]')
        self.assertEqual(self.read(' wlan0: 0000   0.  0.  0\n'), 'rc=0 [] [0] [wlan0]')
        self.assertEqual(self.read(' wlan0: 0000   86.   78.    0.\n'), 'rc=0 [] [86] [wlan0]')

    def test_no_interface_and_any(self):
        self.assertTrue(self.read('').startswith('rc=1 [] [] []'))
        idle = ' wlan1: 0000    0.    0.    0.\n'
        self.assertTrue(self.read(idle).startswith('rc=1'))
        self.assertTrue(self.read(idle, 'any').startswith('rc=1'))
        self.assertEqual(self.read(' wlan1: 0000   40.  -50.    0.\n', 'any'), 'rc=0 [-50] [40] [wlan1]')
        self.assertEqual(self.read(' wlan1: 0000   40.  -50.    0.\n wlan0: 0000   20.  -70.    0.\n', 'any'),
                         'rc=0 [-70] [20] [wlan0]')

    def test_single_reader(self):
        """No caller parses /proc/net/wireless or the 2.x rx_signal path itself any more."""
        for f in ('www/cgi-bin/dash.cgi', 'www/cgi-bin/metrics.cgi', 'www/cgi-bin/statelib.cgi',
                  'scripts/mqtt-bridge.sh', 'scripts/wifi-quality.sh', 'scripts/common_functions.sh'):
            t = text(f)
            self.assertNotIn('rx_signal', t, f)
            self.assertNotIn('/proc/net/wireless', re.sub(r'#.*', '', t), f)
        self.assertNotIn('get_wifi_signal_strength', text('scripts/common_functions.sh'))

    def test_metrics_omit_unknown_samples(self):
        m = text('www/cgi-bin/metrics.cgi')
        self.assertIn('[ -n "$_wl" ] && printf', m)
        self.assertNotIn('_wq=0; _wl=0', m)


class RamDefinition(unittest.TestCase):

    def test_dash_reports_memavailable(self):
        d = text('www/cgi-bin/dash.cgi')
        self.assertIn('MemAvailable:) _d_ma=$_v', d)
        self.assertNotIn('Buffers', d)
        js = text('src/webui/index/47-dashboard.js')
        self.assertNotIn('d.mem[2]', js)
        self.assertIn('d.mem[0] - d.mem[1]', js)

    def test_used_is_total_minus_available(self):
        with tempfile.TemporaryDirectory() as d:
            mi = Path(d) / 'meminfo'
            mi.write_text('MemTotal:       45000 kB\nMemFree:         5000 kB\nMemAvailable:   12000 kB\n'
                          'Buffers: 300 kB\nCached: 4000 kB\n')
            code = (text('scripts/common_functions.sh'))
            m = re.search(r'^get_mem_available_kb\(\)\s*\{.*?^\}', code, re.M | re.S).group(0)
            u = re.search(r'^get_current_memory_usage\(\)\s*\{.*?^\}', code, re.M | re.S).group(0)
            body = (m + '\n' + u + '\n').replace('/proc/meminfo', str(mi))
            r = sh(body + 'get_current_memory_usage')
            self.assertEqual(r.stdout.strip(), '33000', r.stderr)

    def test_heartbeat_records_memavailable(self):
        t = text('scripts/reboot-tracker.sh')
        self.assertIn('^MemAvailable:', t)
        self.assertNotIn('^MemFree:', t)


class SdHealth(unittest.TestCase):

    def run_diag(self, cmd, mounts, flashmode, health='state=ok\nerrors=0\nreadonly=0\n'):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'mounts').write_text(mounts)
            (d / 'health').write_text(health)
            if flashmode:
                (d / 'flash').write_text('')
            env = dict(SDD_PROC_MOUNTS=str(d / 'mounts'), SDD_HEALTH=str(d / 'health'),
                       SDD_FLASHMODE=str(d / 'flash'), SDD_SDINFO=str(d / 'nosdinfo'))
            r = subprocess.run(SHELL + [str(ROOT / 'scripts/sd-diag.sh'), cmd], capture_output=True, text=True,
                               timeout=20, env=dict(os.environ, **env), cwd=str(d))
            return r

    def test_sdinfo_is_the_only_scanner_and_marks_errors(self):
        s = text('v3/linux66-sd/sdinfo-sd.sh')
        self.assertIn('[ "$health" = ok ] && [ "$errs" -gt 0 ] && health=errors', s)
        diag = text('scripts/sd-diag.sh')
        self.assertNotIn('dmesg', diag)
        self.assertNotIn('/mnt/records', diag)
        self.assertNotIn('/mnt/records', text('scripts/rec-storage.sh'))

    def test_check_reads_sd_health(self):
        r = self.run_diag('check', 'rootfs / rootfs rw 0 0\n', True, 'state=errors\nerrors=7\nreadonly=0\n')
        j = json.loads(r.stdout)
        self.assertEqual((j['state'], j['errors']), ('errors', 7))

    def test_repair_refused_on_the_running_card(self):
        sdmode = '/dev/mmcblk0p1 /mnt vfat rw,relatime 0 0\n'
        r = self.run_diag('repair', sdmode, False)
        j = json.loads(r.stdout)
        self.assertFalse(j['ok'])
        self.assertEqual(j['state'], 'refused')
        self.assertNotEqual(r.returncode, 0)
        # flash mode: the card is only storage, the repair goes on
        r = self.run_diag('repair', '/dev/mmcblk0p1 /mnt/sd vfat rw 0 0\n', True)
        self.assertNotEqual(json.loads(r.stdout).get('state'), 'refused')


class StabilityCsv(unittest.TestCase):

    def test_goes_to_the_card_when_mounted_rw_else_ram(self):
        s = text('scripts/health-snapshot.sh')
        fn = re.search(r'^stability_default_path\(\)\s*\{.*?^\}', s, re.M | re.S).group(0)
        with tempfile.TemporaryDirectory() as d:
            for mounts, want in (('/dev/mmcblk0p1 /mnt/sd vfat rw 0 0\n', '/mnt/sd/logs/stability.csv'),
                                 ('/dev/mmcblk0p1 /mnt/sd vfat ro,x 0 0\n', '/mnt/log/stability.csv'),
                                 ('rootfs / rootfs rw 0 0\n', '/mnt/log/stability.csv')):
                f = Path(d) / 'mounts'
                f.write_text(mounts)
                r = sh(fn.replace('/proc/mounts', str(f)) + '\nstability_default_path; echo "$_sf"')
                self.assertEqual(r.stdout.strip(), want, mounts)


if __name__ == '__main__':
    unittest.main()


class NightFindings(unittest.TestCase):
    """Tester's night of 2026-11-03/04: averaged Wi-Fi signal, no stuck sample, switched-off services shown as
    disabled, the card left clean by a deliberate reboot."""

    def test_averaged_signal_is_used_while_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'wireless').write_text(HDR + ' wlan0: 0000   70.  -14.  -256        0      0\n')
            (d / 'up').write_text('1000.00 1\n')
            code = ('. %s; WIFI_PROC_FILE=%s; WIFI_UPTIME_FILE=%s; WIFI_AVG_FILE=%s; wifi_signal_read; echo "[$WIFI_DBM]"'
                    % (ROOT / 'scripts/wifi-signal.sh', d / 'wireless', d / 'up', d / 'avg'))
            self.assertEqual(sh(code).stdout.strip(), '[-14]')              # no average yet: the /proc level
            (d / 'avg').write_text('900 -25\n')
            self.assertEqual(sh(code).stdout.strip(), '[-25]')              # 100 s old: the average
            (d / 'avg').write_text('700 -25\n')
            self.assertEqual(sh(code).stdout.strip(), '[-14]')              # 300 s old: stale

    def test_quality_sample_takes_signal_avg_and_bounds_iw_and_ping(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'wireless').write_text(HDR + ' wlan0: 0000   70.  -14.  -256        0      0\n')
            (d / 'st').write_text('Station aa:bb (on wlan0)\n\tsignal avg:\t-25 [-27, -29] dBm\n\ttx retries:\t3\n\ttx failed:\t0\n')
            (d / 'ping').write_text('3 packets transmitted, 3 packets received, 0% packet loss\n')
            (d / 'up').write_text('500.00 1\n')
            env = dict(WQ_LOG=str(d / 'log'), WQ_SUM=str(d / 'sum'), WQ_STATE=str(d / 'prev'), WQ_WIRELESS=str(d / 'wireless'),
                       WQ_STATION=str(d / 'st'), WQ_PING=str(d / 'ping'), WQ_UPTIME=str(d / 'up'), WIFI_AVG_FILE=str(d / 'avg'))
            r = sh('WQ_NOW=1000 sh %s sample' % (ROOT / 'scripts/wifi-quality.sh'), env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((d / 'log').read_text().split()[:2], ['1000', '-25'])
            self.assertEqual((d / 'avg').read_text().strip(), '500 -25')
        w = text('scripts/wifi-quality.sh')
        self.assertIn('timeout 5 "$(command -v iw', w)
        self.assertIn('timeout 8 ping', w)

    def test_switched_off_service_is_disabled_not_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'autostart').mkdir()
            (d / 'boot.conf').write_text('MEM_GUARD_ENABLE=0\n')
            cs = d / 'cs'; cs.mkdir()
            for n in ('memory-guard', 'ftp-server'):
                (cs / n).write_text('#!/bin/sh\n'); (cs / n).chmod(0o755)
            code = ('SW_CONF_DIR=%s; HP_CONF_DIR=%s; HP_SWITCH_SH=%s; . %s\n'
                    'probe() { _pf_svc=$1; case $1 in *) ;; esac; _pf_down; }\n'
                    'probe memory-guard; probe ftp-server; touch %s/autostart/ftp-server; probe ftp-server\n'
                    % (d, d, ROOT / 'scripts/service-switch.sh', ROOT / 'scripts/health-probe.sh', d))
            self.assertEqual(sh(code).stdout.split(), ['disabled', 'disabled', 'stopped'])

    def test_deliberate_reboot_leaves_the_card_clean(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'fm').write_text('')
            (d / 'mounts').write_text('/dev/mmcblk0p1 /mnt/sd vfat rw,noatime 0 0\n')
            (d / 'rec').write_text('state=paused\n')
            code = ('REBOOT_TRACKER_FLASHMODE=%s; REBOOT_TRACKER_MOUNTS=%s; TC100FIX_REC_STATUS=%s; '
                    'REBOOT_TRACKER_REMOUNT="touch %s/remounted"; . %s >/dev/null 2>&1; rt_card_clean'
                    % (d / 'fm', d / 'mounts', d / 'rec', d, ROOT / 'scripts/reboot-tracker.sh'))
            self.assertEqual(sh(code).returncode, 0)
            self.assertTrue((d / 'rec.pause').exists())
            self.assertTrue((d / 'remounted').exists())
        self.assertIn('mount -o remount,ro /mnt/sd', text('v3/install/update66.sh'))

    def test_frigate_yaml_never_holds_the_password(self):
        s = text('www/cgi-bin/state.cgi')
        block = s[s.index('  frigateyaml)'):s.index('    ;;', s.index('  frigateyaml)'))]
        self.assertIn('fy_auth="${fy_user}:{FRIGATE_RTSP_PASSWORD}@"', block)
        self.assertNotIn('USERPASSWORD', block)
