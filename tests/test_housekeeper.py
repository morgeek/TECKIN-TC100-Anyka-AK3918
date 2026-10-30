"""Host tests of scripts/housekeeper.sh (one resident loop for web-guard, net-guard, the SD panel, the service
watchdogs, health-snapshot and log-persist) and of the one-shot modes it relies on. Camera-side scripts run in busybox
ash when it is installed (the CI image has it).
Run: python3 -m unittest tests/test_housekeeper.py
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']
HK = str(ROOT / 'scripts/housekeeper.sh')


def sh(code, env=None, timeout=60):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(SH + ['-c', code], capture_output=True, text=True, timeout=timeout, env=e)


def script(path, *args, env=None, timeout=60):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(SH + [str(path)] + list(args), capture_output=True, text=True, timeout=timeout, env=e)


def lines(p):
    p = Path(p)
    return p.read_text().split() if p.exists() else []


def wait_for(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        (d / 'scripts').mkdir()
        self.env = dict(HK_DIR=str(d / 'hk'), HK_PIDFILE=str(d / 'hk.pid'),
                        HK_SCRIPTS=str(d / 'scripts'), HK_WDSTATE=str(d / 'wd'), HK_RUNDIR=str(d / 'run'))
        (d / 'run').mkdir()
        if shutil.which('busybox'):      # the `sh` that scripts start (hk start, hk_bg) is busybox ash, as on the camera
            (d / 'bin').mkdir()
            (d / 'bin' / 'sh').write_text('#!/bin/sh\nexec busybox ash "$@"\n')
            (d / 'bin' / 'sh').chmod(0o755)
            self.env['PATH'] = '%s:%s' % (d / 'bin', os.environ['PATH'])

    def tearDown(self):
        if (self.d / 'hk.pid').exists():
            try:
                os.kill(int((self.d / 'hk.pid').read_text().split()[0]), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        for p in (self.d / 'hk' / 'run').glob('*') if (self.d / 'hk' / 'run').exists() else []:
            try:
                os.kill(int(p.read_text().split()[0]), signal.SIGKILL)
            except (OSError, ValueError, IndexError):
                pass
        self.tmp.cleanup()

    def fake(self):
        return dict(self.env, HK_CLOCK=str(self.d / 'clock'))

    def prog(self, name, body):
        p = self.d / name
        p.write_text('#!/bin/sh\n' + body)
        p.chmod(0o755)
        return p

    def ticks(self, times, setup='', after=''):
        """Source the housekeeper with a fake clock and call hk_tick at each of the times."""
        code = ('HK_TEST_SOURCE=1; . %s\n%s\nfor t in %s; do echo "$t.50 0" > "$HK_CLOCK"; hk_tick; %s\ndone\n'
                % (HK, setup, ' '.join(str(t) for t in times), after))
        return sh(code, self.fake())


class Scheduler(Base):
    def test_each_job_keeps_its_own_period_and_first_delay(self):
        out = self.d / 'out'
        setup = ('hk_write_spec a fn 10 10 - "echo a >> %s"\n'
                 'hk_write_spec b fn 25 5 - "echo b >> %s"\n' % (out, out))
        r = self.ticks([0, 5, 9, 10, 14, 20, 29, 30, 31, 40, 50, 55], setup)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = lines(out)
        # a: first at 10, then 20, 30, 40, 50 (10 s after each run); b: first at 5, then 30, 55
        self.assertEqual(got.count('a'), 5, got)
        self.assertEqual(got.count('b'), 3, got)
        self.assertEqual(got[:2], ['b', 'a'])

    def test_fifo_wait_nap_is_the_time_to_the_next_job(self):
        setup = 'hk_write_spec a fn 100 100 - ":"\nhk_write_spec b fn 40 40 - ":"\n'
        r = sh('HK_TEST_SOURCE=1; . %s\necho "0.5 0" > "$HK_CLOCK"\n%s\nhk_tick; echo "$_hk_next"\n' % (HK, setup),
               dict(self.fake(), HK_MAXWAIT='300'))
        self.assertEqual(r.stdout.strip(), '40', r.stderr)
        # nothing registered: at most HK_MAXWAIT
        r = sh('HK_TEST_SOURCE=1; . %s\necho "0.5 0" > "$HK_CLOCK"; hk_tick; echo "$_hk_next"\n' % HK, dict(self.fake(), HK_MAXWAIT='30'))
        self.assertEqual(r.stdout.strip(), '30')

    def test_a_hung_job_does_not_stall_the_others_nor_overlap_itself(self):
        hang = self.prog('hang.sh', 'echo run >> %s\nexec sleep 300\n' % (self.d / 'hang.log'))
        fast = self.d / 'fast.log'
        setup = ('hk_write_spec hung bg 1 0 - sh %s\n'
                 'hk_write_spec fast fn 1 0 - "echo f >> %s"\n' % (hang, fast))
        code = ('HK_TEST_SOURCE=1; . %s\n%s\n'
                'for t in 1 2 3 4 5; do echo "$t.5 0" > "$HK_CLOCK"; hk_tick; sleep 0.2; done\n'
                'read -r p < "$HK_DIR/run/hung"; kill "$p"; sleep 0.3\n'     # the hung run ends (killed)
                'echo "6.5 0" > "$HK_CLOCK"; hk_tick; sleep 0.3\n'
                'read -r p < "$HK_DIR/run/hung"; kill "$p"\n'
                'read -r st < "$HK_DIR/state/hung"; echo "$st"\n' % (HK, setup))
        r = sh(code, self.fake())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(lines(fast).count('f'), 6)            # the fast job ran at every tick
        self.assertEqual(lines(self.d / 'hang.log').count('run'), 2)   # started once, again only after it ended
        self.assertIn('skipped=4', r.stdout)

    def test_a_new_spec_with_the_same_name_restarts_the_schedule(self):
        out = self.d / 'out'
        setup = 'hk_write_spec a fn 100 0 - "echo one >> %s"\n' % out
        code = ('HK_TEST_SOURCE=1; . %s\n%s\n'
                'echo "1.5 0" > "$HK_CLOCK"; hk_tick\n'
                'hk_write_spec a fn 100 3 - "echo two >> %s"\n'
                'echo "2.5 0" > "$HK_CLOCK"; hk_tick\n'
                'echo "4.5 0" > "$HK_CLOCK"; hk_tick\n'
                'echo "5.5 0" > "$HK_CLOCK"; hk_tick\n' % (HK, setup, out))
        sh(code, self.fake())
        self.assertEqual(lines(out), ['one', 'two'])

    def test_period_override_of_a_job(self):
        out = self.d / 'out'
        code = ('HK_TEST_SOURCE=1; . %s\nhk_ovr() { echo a >> %s; echo 3 > "$HK_DIR/period/a"; }\n'
                'hk_write_spec a fn 10 0 - hk_ovr\n'
                'for t in 1 2 3 4 5 6 7 8; do echo "$t.5 0" > "$HK_CLOCK"; hk_tick; done\n' % (HK, out))
        sh(code, self.fake())
        self.assertEqual(lines(out).count('a'), 3)   # t=1 (period then 3), 4, 7


class DaemonLifecycle(Base):
    """The real loop, started and stopped through the command line, with the real clock."""

    def hk(self, *args, env=None):
        return script(HK, *args, env=dict(self.env, HK_WAITMODE='fifo', HK_MAXWAIT='2', **(env or {})))

    def pid(self):
        return int((self.d / 'hk.pid').read_text().split()[0])

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            return 'Z' not in Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[0]
        except OSError:
            return True

    def test_start_register_run_stop_job_start_again(self):
        # no web-guard.sh in HK_SCRIPTS: only the jobs registered here
        a, b = self.d / 'a.log', self.d / 'b.log'
        pa = self.d / 'a.pid'
        ja = self.prog('ja.sh', 'echo a >> %s\n' % a)
        jb = self.prog('jb.sh', 'echo b >> %s\n' % b)
        self.assertNotEqual(self.hk('active').returncode, 0)
        self.assertNotEqual(self.hk('job', 'add', 'a', 'bg', '1', '0', str(pa), 'sh', str(ja)).returncode, 0,
                            'no loop running: job add must fail so that the caller starts its own daemon')
        self.assertNotEqual(self.hk('watch-add', 'rtsp-h26x', str(self.d / 'w.pid')).returncode, 0)
        self.assertEqual(self.hk('start').returncode, 0)
        self.assertEqual(self.hk('active').returncode, 0)
        pid = self.pid()
        self.assertEqual(self.hk('job', 'add', 'a', 'bg', '1', '0', str(pa), 'sh', str(ja)).returncode, 0)
        self.assertEqual(self.hk('job', 'add', 'b', 'bg', '1', '0', '-', 'sh', str(jb)).returncode, 0)
        self.assertEqual(int(pa.read_text()), pid, 'the pid file of a job holds the housekeeper pid')
        self.assertTrue(wait_for(lambda: len(lines(a)) >= 2 and len(lines(b)) >= 2, 12), (lines(a), lines(b)))
        # stop job a: no more runs, pid file gone; b goes on
        self.assertEqual(self.hk('job', 'del', 'a').returncode, 0)
        self.assertFalse(pa.exists())
        n = len(lines(a))
        nb = len(lines(b))
        time.sleep(3.5)
        self.assertEqual(len(lines(a)), n)
        self.assertGreater(len(lines(b)), nb)
        self.assertNotEqual(self.hk('job', 'has', 'a').returncode, 0)
        self.assertEqual(self.hk('job', 'del', 'a').returncode, 1)     # already gone
        st = self.hk('status').stdout
        self.assertIn('PID: %d' % pid, st)
        self.assertIn('b kind=bg period=1', st)
        self.assertNotIn('\na ', st)
        # start it again
        self.assertEqual(self.hk('job', 'add', 'a', 'bg', '1', '0', str(pa), 'sh', str(ja)).returncode, 0)
        self.assertTrue(wait_for(lambda: len(lines(a)) > n, 8))
        self.assertEqual(int(pa.read_text()), pid)
        # stop the loop: the pid file of the job then names a dead process (the Services page says "stopped")
        self.assertEqual(self.hk('stop').returncode, 0)
        self.assertFalse(self.alive(pid))
        self.assertNotEqual(self.hk('active').returncode, 0)

    def test_job_del_stops_the_run_that_is_going(self):
        marker = self.d / 'marker'
        long_job = self.prog('long.sh', 'echo $$ > %s\nexec sleep 300\n' % marker)
        self.hk('start')
        self.hk('job', 'add', 'long', 'bg', '60', '0', '-', 'sh', str(long_job))
        self.assertTrue(wait_for(marker.exists, 8))
        lp = int(marker.read_text())
        self.assertTrue(self.alive(lp))
        # the loop records the run's pid just after the fork: a del before that leaves the run to finish (harmless)
        run = self.d / 'hk' / 'run' / 'long'
        self.assertTrue(wait_for(lambda: run.exists() and run.read_text().strip() == str(lp), 5))
        self.hk('job', 'del', 'long')
        self.assertTrue(wait_for(lambda: not self.alive(lp), 5), 'the run in progress must be stopped')

    def test_restart_of_the_loop_keeps_jobs_and_rewrites_pid_files(self):
        pa = self.d / 'a.pid'
        ja = self.prog('ja.sh', ':\n')
        self.hk('start')
        old = self.pid()
        self.hk('job', 'add', 'a', 'bg', '60', '60', str(pa), 'sh', str(ja))
        self.hk('stop')
        self.hk('start')
        new = self.pid()
        self.assertTrue(wait_for(lambda: pa.exists() and pa.read_text().strip() == str(new), 5), (old, new))

    def test_read_t_probe_picks_a_wait_mode(self):
        r = script(HK, 'start', env=dict(self.env, HK_MAXWAIT='2'))
        self.assertEqual(r.returncode, 0)
        time.sleep(0.5)
        self.assertEqual(script(HK, 'active', env=self.env).returncode, 0)
        script(HK, 'stop', env=self.env)

    def test_bad_arguments_are_refused(self):
        self.hk('start')
        for args in (('job', 'add', 'bad name', 'bg', '1', '0', '-', 'x'), ('job', 'add', 'a', 'zz', '1', '0', '-', 'x'),
                     ('job', 'add', 'a', 'bg', '0', '0', '-', 'x'), ('job', 'add', 'a', 'bg', '1', 'x', '-', 'x'),
                     ('job', 'add', 'a', 'bg', '1', '0', '-')):
            self.assertEqual(self.hk(*args).returncode, 2, args)


class WatchdogJobs(Base):
    def test_fast_path_counts_successes_without_launching_anything(self):
        pidf = self.d / 'run' / 'v4l2rtspserver.pid'
        pidf.write_text('%d\n' % os.getpid())          # a live process
        fake = self.prog('scripts/service-watchdog.sh', 'echo launched "$@" >> %s\n' % (self.d / 'launch.log'))
        setup = 'hk_write_spec watch-rtsp-h26x wd 60 60 - "/mnt/controlscripts/rtsp-h26x 0 status"\n'
        r = self.ticks([0, 60, 120, 180], setup)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.d / 'launch.log').exists())
        self.assertEqual((self.d / 'wd' / 'rtsp-h26x').read_text().split(), ['0', '3', '-', '0'])

    def test_dead_service_launches_a_tick_with_the_environment_of_the_job(self):
        (self.d / 'run' / 'v4l2rtspserver.pid').write_text('999999\n')
        self.prog('scripts/service-watchdog.sh', 'echo "$CHECK_TIMEOUT_SECONDS $WATCHDOG_LOG_BACKUPS $HK_JOB" "$@" >> %s\n' % (self.d / 'launch.log'))
        setup = ('hk_write_spec watch-rtsp-h26x wd 45 45 - '
                 '"/mnt/controlscripts/rtsp-h26x 0 status WATCHDOG_LOG_BACKUPS=3"\n')
        self.ticks([0, 45], setup, after='wait')
        self.assertTrue(wait_for((self.d / 'launch.log').exists, 5))
        self.assertEqual(lines(self.d / 'launch.log'),
                         ['45', '3', 'watch-rtsp-h26x', '--tick', '/mnt/controlscripts/rtsp-h26x', '0', 'status'])

    def test_other_services_and_health_mode_always_use_the_tick(self):
        self.prog('scripts/service-watchdog.sh', 'echo "$@" >> %s\n' % (self.d / 'launch.log'))
        setup = ('hk_write_spec watch-telegram-bot wd 60 60 - "/mnt/controlscripts/telegram-bot 0 status"\n'
                 'hk_write_spec watch-onvif wd 60 60 - "/mnt/controlscripts/onvif 0 health"\n')
        (self.d / 'run' / 'onvif.pid').write_text('%d\n' % os.getpid())
        self.ticks([0, 60], setup, after='wait')
        self.assertTrue(wait_for(lambda: len(lines(self.d / 'launch.log')) >= 8, 5))
        got = (self.d / 'launch.log').read_text()
        self.assertIn('--tick /mnt/controlscripts/telegram-bot 0 status', got)
        self.assertIn('--tick /mnt/controlscripts/onvif 0 health', got)

    def test_watch_add_registers_clamped_numeric_environment_only(self):
        script(HK, 'start', env=dict(self.env, HK_WAITMODE='fifo'))
        pf = self.d / 'w.pid'
        env = dict(self.env, CHECK_TIMEOUT_SECONDS='2', WATCHDOG_LOG_BACKUPS='4', WATCHDOG_NO_REBOOT_MAX_DELAY_SECONDS='x; rm -rf /')
        r = script(HK, 'watch-add', 'rtsp-h26x', str(pf), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        spec = (self.d / 'hk' / 'jobs' / 'watch-rtsp-h26x').read_text().split(None, 5)
        self.assertEqual(spec[1:5], ['wd', '5', '5', str(pf)])             # at least 5 s
        self.assertEqual(spec[5].strip(), '/mnt/controlscripts/rtsp-h26x 0 status WATCHDOG_LOG_BACKUPS=4')
        self.assertTrue(pf.exists())
        self.assertEqual(script(HK, 'watch-del', 'rtsp-h26x', env=self.env).returncode, 0)
        self.assertFalse(pf.exists())
        script(HK, 'stop', env=self.env)

    def service_watchdog(self):
        """service-watchdog.sh with its absolute /mnt paths pointed into the temp dir."""
        d = self.d
        (d / 'event-logger.sh').write_text('log_event() { echo "$*" >> %s; }\n' % (d / 'events'))
        (d / 'reboot-tracker.sh').write_text('echo "$@" >> %s\n' % (d / 'tracker'))
        s = (ROOT / 'scripts/service-watchdog.sh').read_text()
        s = s.replace('/mnt/scripts/event-logger.sh', str(d / 'event-logger.sh'))
        s = s.replace('/mnt/scripts/reboot-tracker.sh', str(d / 'reboot-tracker.sh'))
        s = s.replace('/sbin/reboot -f', 'echo reboot >> %s' % (d / 'tracker'))
        s = s.replace('/mnt/controlscripts/', str(d) + '/')
        (d / 'wd.sh').write_text(s)
        return d / 'wd.sh'

    def fake_service(self, name, healthy):
        return self.prog(name, 'case "$1" in\n status) %s;;\n start|restart) echo start >> %s;;\nesac\n'
                         % ('echo "PID: 1"' if healthy else ':', self.d / (name + '.calls')))

    def test_tick_counters_survive_between_runs_no_reboot_mode(self):
        wd = self.service_watchdog()
        svc = self.fake_service('svc', False)
        env = dict(self.env, LOGPATH=str(self.d / 'wd.log'), CHECK_TIMEOUT_SECONDS='5')
        r = script(wd, '--tick', str(svc), '0', 'status', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(lines(self.d / 'svc.calls'), ['start'])
        e, s, delay, last = (self.d / 'wd' / 'svc').read_text().split()
        self.assertEqual((e, s, delay), ('0', '0', '35'))                  # backoff 20 s -> 35 s
        self.assertGreater(int(last), 0)
        # the next check comes at once: the restart is deferred, as in the loop
        time.sleep(1.2)
        script(wd, '--tick', str(svc), '0', 'status', env=env)
        self.assertEqual(lines(self.d / 'svc.calls'), ['start'])
        self.assertIn('restart deferred', (self.d / 'wd.log').read_text())

    def test_tick_error_count_and_reboot_limit(self):
        wd = self.service_watchdog()
        svc = self.fake_service('svc', False)
        (self.d / 'wd').mkdir(exist_ok=True)
        (self.d / 'wd' / 'svc').write_text('5 0 - 0\n')                    # five errors already
        env = dict(self.env, LOGPATH=str(self.d / 'wd.log'), CHECK_TIMEOUT_SECONDS='5')
        r = script(wd, '--tick', str(svc), '1', 'status', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.d / 'wd' / 'svc').read_text().split()[0], '6')
        self.assertIn('perform reboot', (self.d / 'wd.log').read_text())   # more than MAX_ERRORS_TO_REBOOT (5)
        self.assertIn('reboot', (self.d / 'tracker').read_text())

    def test_tick_success_resets_after_thirty(self):
        wd = self.service_watchdog()
        svc = self.fake_service('svc', True)
        (self.d / 'wd').mkdir(exist_ok=True)
        (self.d / 'wd' / 'svc').write_text('3 30 77 0\n')
        env = dict(self.env, LOGPATH=str(self.d / 'wd.log'), CHECK_TIMEOUT_SECONDS='5')
        script(wd, '--tick', str(svc), '1', 'status', env=env)
        self.assertEqual((self.d / 'wd' / 'svc').read_text().split(), ['0', '0', '-', '0'])

    def test_loop_mode_is_still_there(self):
        s = (ROOT / 'scripts/service-watchdog.sh').read_text()
        self.assertIn('monitor_service "$1" "${2:-1}" "${3:-status}"', s)
        self.assertIn('sleep $CHECK_TIMEOUT_SECONDS', s)


class WebGuardJobs(Base):
    def setUp(self):
        super().setUp()
        d = self.d
        (d / 'ports').write_text('')
        (d / 'common.sh').write_text('port_listening() { grep -qx "$1" "%s/ports"; }\n'
                                     'http_server() { echo restart >> "%s/restarts"; }\n' % (d, d))
        self.prog('netguard.sh', 'echo ng >> %s\n' % (d / 'ng.log'))
        self.prog('sdinfo.sh', 'echo sd >> %s\n' % (d / 'sd.log'))
        (d / 'telnetd').write_text('#!/bin/sh\nexec sleep 300\n')
        (d / 'telnetd').chmod(0o755)
        self.env.update(HK_SCRIPTS=str(ROOT / 'scripts'), WG_COMMON=str(d / 'common.sh'), WG_STATE=str(d / 'wgst'),
                        WG_PIDFILE=str(d / 'rescue.pid'), WG_TELNETD=str(d / 'telnetd'),
                        WG_RESTART='http_server', WG_NETGUARD=str(d / 'netguard.sh'), WG_SDINFO=str(d / 'sdinfo.sh'),
                        WG_NETSTATE=str(d / 'ngst'), WG_FIRST='60')

    def tearDown(self):
        p = self.d / 'rescue.pid'
        if p.exists():
            try:
                os.kill(int(p.read_text().strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        super().tearDown()

    def run_ticks(self, n):
        """A fresh loop: a registering pass at 0, then n minutes (so n runs of the 60 s jobs)."""
        return self.ticks([60 * k for k in range(n + 1)], 'hk_core_jobs', after='wait;')

    def test_core_jobs_registered_with_the_web_guard_period(self):
        r = sh('HK_TEST_SOURCE=1; . %s\nhk_core_jobs; ls "$HK_JOBS"' % HK, self.fake())
        self.assertEqual(r.stdout.split(), ['net', 'sd', 'web'], r.stderr)

    def test_net_guard_every_third_minute_while_up_every_minute_once_down(self):
        (self.d / 'ports').write_text('80\n')
        # 9 minutes: net-guard on the 1st, 4th and 7th run
        self.run_ticks(9)
        self.assertEqual(len(lines(self.d / 'ng.log')), 3)
        # a failed check leaves down_since: from then on every minute
        (self.d / 'ngst').mkdir()
        (self.d / 'ngst' / 'down_since').write_text('1\n')
        self.run_ticks(3)
        self.assertEqual(len(lines(self.d / 'ng.log')), 3 + 3)

    def test_sd_panel_first_tick_and_every_tenth(self):
        (self.d / 'ports').write_text('80\n')
        self.run_ticks(11)
        self.assertEqual(len(lines(self.d / 'sd.log')), 2)        # ticks 0 and 10 (the card state does not change here)

    def test_web_down_restarts_once_then_opens_rescue_telnet_then_closes_it(self):
        self.run_ticks(3)
        self.assertEqual((self.d / 'restarts').read_text(), 'restart\n')
        self.assertTrue(wait_for((self.d / 'rescue.pid').exists, 5))
        pid = (self.d / 'rescue.pid').read_text().strip()
        os.kill(int(pid), 0)
        # web back for two checks: the rescue telnet is closed
        (self.d / 'ports').write_text('80\n')
        self.run_ticks(2)
        self.assertFalse((self.d / 'rescue.pid').exists())

    def test_a_hung_sd_card_script_does_not_stop_the_web_check(self):
        self.prog('sdinfo.sh', 'echo sd >> %s\nexec sleep 300\n' % (self.d / 'sd.log'))
        (self.d / 'ports').write_text('')
        code = ('HK_TEST_SOURCE=1; . %s\nhk_core_jobs\n'
                'for t in 0 60 120 180 240 300 360 420 480 540 600 660; do echo "$t.5 0" > "$HK_CLOCK"; hk_tick; sleep 0.1; done\n'
                'read -r p < "$HK_DIR/run/sdinfo"; kill "$p"\n' % HK)
        r = sh(code, dict(self.env, HK_CLOCK=str(self.d / 'clock')))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(lines(self.d / 'sd.log')), 1)       # the second run (10th minute) was skipped, not stacked
        self.assertTrue((self.d / 'restarts').exists())          # and the web server was restarted all the same


class OneShotModes(Base):
    def test_health_snapshot_once_does_not_touch_the_pid_file_and_counts_the_stability_time(self):
        d = self.d
        env = dict(self.env, HEALTH_SNAPSHOT_INTERVAL_SECONDS='30', STABILITY_SAMPLE_SECONDS='60',
                   STABILITY_FILE=str(d / 'stab.csv'), STABILITY_PENDING=str(d / 'pending'),
                   STABILITY_ELAPSED_FILE=str(d / 'elapsed'), HEALTH_SNAPSHOT_CACHE=str(d / 'cache'),
                   HEALTH_SNAPSHOT_PIDFILE=str(d / 'hs.pid'), STABILITY_FLUSH_SAMPLES='12')
        (d / 'hs.pid').write_text('4242\n')
        hs = ROOT / 'scripts/health-snapshot.sh'
        self.assertEqual(script(hs, 'interval', env=env).stdout.strip(), '30')
        self.assertEqual(script(hs, 'interval', env=dict(env, HEALTH_SNAPSHOT_INTERVAL_SECONDS='3')).stdout.strip(), '10')
        self.assertEqual(script(hs, 'interval', env=dict(env, HEALTH_SNAPSHOT_INTERVAL_SECONDS='999')).stdout.strip(), '300')
        r = script(hs, 'once', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((d / 'hs.pid').read_text(), '4242\n')
        self.assertTrue((d / 'cache').read_text().split('\n', 1)[1].startswith('{"ok":true'))
        self.assertEqual((d / 'elapsed').read_text().strip(), '30')
        self.assertFalse((d / 'pending').exists())
        script(hs, 'once', env=env)                                # 60 s: one sample is due
        self.assertEqual((d / 'elapsed').read_text().strip(), '0')
        self.assertEqual(len((d / 'pending').read_text().splitlines()), 1)
        r = script(hs, 'flush', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len((d / 'stab.csv').read_text().splitlines()), 2)   # header + the sample
        self.assertEqual((d / 'pending').read_text(), '')
        self.assertEqual((d / 'hs.pid').read_text(), '4242\n')

    def test_log_persist_hk_tells_the_housekeeper_its_next_period(self):
        d = self.d
        (d / 'boot.conf').write_text('LOG_PERSIST_MIN="3"\n')
        env = dict(self.env, LP_SD=str(d / 'sd'), LP_BOOTCONF=str(d / 'boot.conf'), LP_MOUNTS=str(d / 'mounts'),
                   LP_STATE=str(d / 'state'), LP_LOCK=str(d / 'lock'), LP_PIDFILE=str(d / 'lp.pid'))
        (d / 'mounts').write_text('')
        r = script(ROOT / 'scripts/log-persist.sh', 'hk', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((d / 'hk' / 'period' / 'log-persist').read_text().strip(), '180')
        (d / 'boot.conf').write_text('LOG_PERSIST_MIN=99999\n')
        script(ROOT / 'scripts/log-persist.sh', 'hk', env=env)
        self.assertEqual((d / 'hk' / 'period' / 'log-persist').read_text().strip(), '600')
        self.assertFalse((d / 'lp.pid').exists())                  # the loop's pid file is not written

    def test_log_persist_loop_is_still_there(self):
        s = (ROOT / 'scripts/log-persist.sh').read_text()
        self.assertIn('run) lp_run ;;', s)
        self.assertIn('sleep $((_m * 60))', s)


class BootWiring(unittest.TestCase):
    def read(self, p):
        return (ROOT / p).read_text()

    def test_housekeeper_switch_and_separate_daemons_path(self):
        a = self.read('v3/autorun-linux66.sh')
        self.assertIn('"$BC_HOUSEKEEPER" != 0', a)
        self.assertIn('housekeeper.sh start', a)
        # HOUSEKEEPER=0 (or a loop that is not running): today's start lines
        self.assertIn('log-persist.sh run', a)
        self.assertIn('web-guard.sh run', a)
        self.assertIn('housekeeper.sh active', a)
        self.assertIn('HOUSEKEEPER=1', self.read('config/boot.conf.dist'))

    def test_every_control_script_has_a_fallback_to_its_own_daemon(self):
        for name, own in (('mqtt-bridge', 'service-watchdog.sh /mnt/controlscripts/mqtt-bridge'),
                          ('telegram-bot', 'service-watchdog.sh /mnt/controlscripts/telegram-bot'),
                          ('onvif', 'service-watchdog.sh /mnt/controlscripts/onvif'),
                          ('rtsp-h26x', 'service-watchdog.sh /mnt/controlscripts/rtsp-h26x'),
                          ('health-snapshot', 'health-snapshot.sh </dev/null')):
            s = self.read('controlscripts/' + name)
            self.assertIn('housekeeper.sh', s, name)
            self.assertIn(own, s, name)

    def test_stop_unregisters_before_any_kill_of_a_pid_file(self):
        for name in ('mqtt-bridge', 'telegram-bot', 'onvif'):
            s = self.read('controlscripts/' + name)
            self.assertLess(s.index('housekeeper.sh watch-del'), s.index('killpid_graceful "$WATCHDOG_PIDFILE"'), name)
        s = self.read('controlscripts/rtsp-h26x')
        self.assertLess(s.index('housekeeper.sh watch-del'), s.index('kill "$wp"'))

    def test_scripts_parse(self):
        for p in ('scripts/housekeeper.sh', 'scripts/web-guard.sh', 'scripts/service-watchdog.sh',
                  'scripts/health-snapshot.sh', 'scripts/log-persist.sh', 'controlscripts/health-snapshot',
                  'controlscripts/mqtt-bridge', 'controlscripts/onvif', 'controlscripts/telegram-bot',
                  'controlscripts/rtsp-h26x', 'v3/autorun-linux66.sh'):
            r = subprocess.run(SH + ['-n', str(ROOT / p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (p, r.stderr))


if __name__ == '__main__':
    unittest.main()
