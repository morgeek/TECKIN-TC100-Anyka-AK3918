"""Tests for scripts/wifi-try.sh (safe rtl8xxxu runtime parameter trials)."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/wifi-try.sh'


@unittest.skipIf(os.name == 'nt', 'needs a POSIX shell')
class WifiTryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sys = self.tmp / 'sys'
        self.state = self.tmp / 'state'
        self.wr = self.tmp / 'wr'
        self.sys.mkdir()
        self.wr.mkdir()
        (self.sys / 'ampdu_rx').write_text('Y\n')
        (self.sys / 'ampdu_tx').write_text('Y\n')
        (self.sys / 'tx_atten').write_text('0\n')
        (self.sys / 'dma_aggregation').write_text('Y\n')
        self.ping_count = self.tmp / 'ping_count'
        # fake wpa_cli: one line of arguments per call
        self.wpa_log = self.tmp / 'wpa_log'
        self.wpa_cli = self.tmp / 'wpa_cli.sh'
        self.wpa_cli.write_text(f'#!/bin/sh\necho "$*" >> "{self.wpa_log}"\n')
        self.wpa_cli.chmod(0o755)
        self.procs = []

    def tearDown(self):
        # Stop any left-over background watcher or dummy process cleanly.
        pid_file = self.state / 'pid'
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), 15)
            except (OSError, ValueError):
                pass
        for p in self.procs:
            p.terminate()
            p.wait(timeout=2)

    def _make_ping(self, script_body):
        p = self.tmp / 'ping.sh'
        p.write_text('#!/bin/sh\n' + script_body + '\n')
        p.chmod(0o755)
        return str(p)

    def _env(self, ping_bin, extra=None):
        env = os.environ.copy()
        env.update({
            'WT_SYS': str(self.sys),
            'WT_STATE': str(self.state),
            'WT_WR_RUN': str(self.wr),
            'WT_GW': '192.168.1.1',
            'WT_PING': ping_bin,
            'WT_POLL_S': '0',
            'WT_STEP_S': '5',
            'WT_SLEEP': 'true',
            'WT_WPA_CLI': str(self.wpa_cli),
        })
        if extra:
            env.update(extra)
        return env

    def _run(self, args, env):
        return subprocess.run(
            ['sh', str(SCRIPT), *args],
            env=env, capture_output=True, text=True, timeout=5,
        )

    def _wait_watcher_exit(self, timeout=5.0):
        pid_file = self.state / 'pid'
        if not pid_file.exists():
            return
        try:
            pid = int(pid_file.read_text().strip())
        except ValueError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.05)
        self.fail(f'watcher pid {pid} did not exit within {timeout}s')

    def test_whitelist_and_window_validation(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping)
        bad_calls = [
            [],
            ['ampdu_rx=2'],
            ['ampdu_tx=2'],
            ['ampdu_tx='],
            ['ampdu_tx=Y'],
            ['tx_atten=31'],
            ['tx_atten=-1'],
            ['dma_aggregation=0'],
            ['../ampdu_rx=0'],
            ['ampdu_rx'],
            ['ampdu_rx=0', '9'],
            ['ampdu_rx=0', '601'],
            ['ampdu_rx=0', 'abc'],
        ]
        for args in bad_calls:
            r = self._run(args, env)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
        self.assertEqual((self.sys / 'ampdu_rx').read_text().strip(), 'Y')
        self.assertEqual((self.sys / 'tx_atten').read_text().strip(), '0')
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), 'Y')
        self.assertFalse(self.wpa_log.exists())

    def _reassocs(self):
        return self.wpa_log.read_text().splitlines() if self.wpa_log.exists() else []

    def test_ampdu_tx_reassociates_on_apply_and_on_expiry_revert(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping)
        r = self._run(['ampdu_tx=0', '15'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('applied ampdu_tx=0 (prev=Y', r.stdout)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), 'Y')
        self.assertEqual(self._reassocs(), ['-i wlan0 reassociate'] * 2)

    def test_ampdu_tx_reverts_after_three_ping_misses(self):
        ping = self._make_ping(f'''
c=0
[ -f "{self.ping_count}" ] && read -r c < "{self.ping_count}"
c=$((c + 1))
echo "$c" > "{self.ping_count}"
[ "$c" -eq 1 ] && exit 0
exit 1
''')
        r = self._run(['ampdu_tx=0', '600'], self._env(ping))
        self.assertEqual(r.returncode, 0, r.stderr)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), 'Y')
        self.assertEqual(len(self._reassocs()), 2)

    def test_ampdu_tx_confirm_and_manual_revert(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping, extra={'WT_POLL_S': '1', 'WT_STEP_S': '5', 'WT_SLEEP': 'sleep'})
        r = self._run(['ampdu_tx=0', '20'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), '0')
        self.assertIn('pending ampdu_tx=0 prev=Y', self._run(['status'], env).stdout)
        self.assertEqual(self._run(['confirm'], env).returncode, 0)
        self._wait_watcher_exit(timeout=3.0)
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), '0')
        self.assertEqual(len(self._reassocs()), 1)      # kept: no second reassociation

        r = self._run(['ampdu_tx=1', '20'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rv = self._run(['revert'], env)
        self.assertEqual(rv.returncode, 0, rv.stderr)
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), '0')
        self.assertEqual(len(self._reassocs()), 3)

    def test_other_parameters_do_not_reassociate(self):
        ping = self._make_ping('exit 0')
        r = self._run(['ampdu_rx=0', '15'], self._env(ping))
        self.assertEqual(r.returncode, 0, r.stderr)
        self._wait_watcher_exit()
        self.assertEqual(self._reassocs(), [])

    def test_missing_wpa_cli_does_not_block(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping, extra={'WT_WPA_CLI': str(self.tmp / 'absent')})
        r = self._run(['ampdu_tx=0', '15'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'ampdu_tx').read_text().strip(), 'Y')

    def test_refuses_when_rescue_ap_active(self):
        sleeper = subprocess.Popen(['sleep', '30'])
        self.procs.append(sleeper)
        (self.wr / 'hostapd.pid').write_text(f'{sleeper.pid}\n')
        ping = self._make_ping('exit 0')
        r = self._run(['ampdu_rx=0'], self._env(ping))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('rescue AP', r.stderr)
        self.assertEqual((self.sys / 'ampdu_rx').read_text().strip(), 'Y')

    def test_refuses_when_router_unreachable_before_change(self):
        ping = self._make_ping('exit 1')
        r = self._run(['tx_atten=6'], self._env(ping))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unreachable', r.stderr)
        self.assertEqual((self.sys / 'tx_atten').read_text().strip(), '0')

    def test_pre_check_survives_one_lost_ping(self):
        # the .11 has 2-5 s Wi-Fi stalls: one lost ping before the change must not refuse the trial (2026-11-14)
        ping = self._make_ping(f'''
c=0
[ -f "{self.ping_count}" ] && read -r c < "{self.ping_count}"
c=$((c + 1))
echo "$c" > "{self.ping_count}"
[ "$c" -eq 1 ] && exit 1
exit 0
''')
        r = self._run(['tx_atten=6', '30'], self._env(ping))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.sys / 'tx_atten').read_text().strip(), '6')
        self._run(['revert'], self._env(ping))
        self._wait_watcher_exit()

    def test_reverts_after_three_ping_misses(self):
        ping = self._make_ping(f'''
c=0
[ -f "{self.ping_count}" ] && read -r c < "{self.ping_count}"
c=$((c + 1))
echo "$c" > "{self.ping_count}"
[ "$c" -eq 1 ] && exit 0
exit 1
''')
        env = self._env(ping)
        r = self._run(['ampdu_rx=0', '60'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'ampdu_rx').read_text().strip(), 'Y')
        self.assertEqual(int(self.ping_count.read_text().strip()), 4)

    def test_reverts_on_window_expiry_without_confirm(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping)
        r = self._run(['tx_atten=10', '15'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'tx_atten').read_text().strip(), '0')

    def test_confirm_keeps_change_and_cleans_state(self):
        ping = self._make_ping('exit 0')
        env = self._env(ping, extra={'WT_POLL_S': '1', 'WT_STEP_S': '5', 'WT_SLEEP': 'sleep'})
        r = self._run(['ampdu_rx=0', '20'], env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.sys / 'ampdu_rx').read_text().strip(), '0')

        st = self._run(['status'], env)
        self.assertIn('pending ampdu_rx=0 prev=Y', st.stdout)

        cf = self._run(['confirm'], env)
        self.assertEqual(cf.returncode, 0, cf.stderr)
        self._wait_watcher_exit()
        self.assertEqual((self.sys / 'ampdu_rx').read_text().strip(), '0')
        self.assertFalse((self.state / 'confirm').exists())

    def test_manual_revert_and_concurrent_refusal(self):
        ping = self._make_ping('exit 0')
        route = self.tmp / 'route'
        route.write_text('Destination Gateway Genmask\n0.0.0.0 192.168.1.1 0.0.0.0\n')
        env = self._env(ping, extra={
            'WT_GW': '',
            'WT_ROUTE_FILE': str(route),
            'WT_POLL_S': '1',
            'WT_STEP_S': '5',
            'WT_SLEEP': 'sleep',
        })
        r1 = self._run(['tx_atten=8', '30'], env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self._run(['ampdu_rx=0', '30'], env)
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn('already running', r2.stderr)

        rv = self._run(['revert'], env)
        self.assertEqual(rv.returncode, 0, rv.stderr)
        self.assertEqual((self.sys / 'tx_atten').read_text().strip(), '0')
        self.assertIn('inactive', self._run(['status'], env).stdout)


if __name__ == '__main__':
    unittest.main()
