"""tc100-supervisord (src/supervisord): the always-on loops of the camera in one C process, on the build host.

  - parity: the same series of inputs (light levels, the ISP's exposure line, white balance counts, config files, the
    clock) go to scripts/auto-night-daemon.sh (its loop body, run by busybox ash when present) and to the C daemon's
    replay mode; every step compares the console messages, the IR-cut state, the calls of nightmode.sh and the wait
    before the next turn, for the four sources (luma, ae, isp, vendor), with garbage lines and missing files too;
  - the reset button: scripts/button-watch.sh in real time on a fake GPIO file, and the C daemon on the same file (and
    tick by tick in replay mode): hold durations -> rescue / reboot / back to the built-in code;
  - the real daemon: flag files switch the two jobs, SIGTERM, one instance, a refused button job; the button keeps its
    timing while a slow nightmode.sh runs, and a hung one is killed (audit 2026-11-24 R2);
  - scripts/supervisor.sh (the switch and the fallback to the shell loops), the build and the packaging.
Run: python3 -m unittest tests.test_supervisord -v
"""
from pathlib import Path
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAVE_CC = shutil.which('cc') is not None
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
BIN = {}


def build():
    if 'bin' not in BIN:
        d = Path(tempfile.mkdtemp())
        out = d / 'tc100-supervisord'
        r = subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-std=gnu11', '-o', str(out), str(ROOT / 'src/supervisord/supervisord.c')],
                           capture_output=True, text=True)
        assert r.returncode == 0 and not r.stderr, r.stderr
        BIN['bin'] = out
        BIN['dir'] = d
    return BIN['bin']


def tearDownModule():
    if 'dir' in BIN:
        shutil.rmtree(BIN['dir'], ignore_errors=True)


def proc_alive(pid):
    """a process that exists and is not a zombie (a killed orphan may wait for a reaper in a container)"""
    try:
        return Path('/proc/%d/stat' % pid).read_text().split(') ')[1][0] != 'Z'
    except (OSError, IndexError):
        return False


def fake_nightmode(d):
    nm = d / 'nightmode.sh'
    nm.write_text('#!/bin/sh\ncase "$1" in on) echo 0 > %s/ircut ;; off) echo 1 > %s/ircut ;; esac\n'
                  'echo "$1" >> %s/calls\n' % (d, d, d))
    nm.chmod(0o755)
    return nm


# ---------------------------------------------------------------- auto night: shell against C

class Scenario:
    """A list of steps: ('now', t) ('ae', text) ('aen', text) ('luma', text) ('awb', text) ('rmae',) ('rmluma',)
    ('rtsp', text) ('conf', text) ('night',). Rendered for the shell loop body and for the C replay mode."""

    def __init__(self, d):
        self.d = d
        self.steps = []

    def path(self, name):
        return str(self.d / name)

    def add(self, *s):
        self.steps.append(s)

    FILES = {'ae': 'ae', 'aen': 'ae', 'luma': 'luma', 'awb': 'awb', 'rtsp': 'rtspserver.conf', 'conf': 'daynight.conf'}

    def replay(self):
        out = []
        for s in self.steps:
            k = s[0]
            if k == 'now':
                out.append('now %d' % s[1])
            elif k == 'night':
                out += ['night', 'cat ' + self.path('console'), 'rm ' + self.path('console'), 'echo @ircut',
                        'cat ' + self.path('ircut'), 'echo ---']
            elif k in ('ae', 'luma', 'awb', 'rtsp', 'conf'):
                text = s[1]
                # `write PATH TEXT` takes one line: a multi-line conf is written with one command per line is not
                # possible, so those use the `\x01` stand-in for the newline
                out.append('writeml %s %s' % (self.path(self.FILES[k]), text.replace('\n', '\x01')))
            elif k == 'aen':
                out.append('writen %s %s' % (self.path('ae'), s[1]))
            elif k == 'rmae':
                out.append('rm ' + self.path('ae'))
            elif k == 'rmluma':
                out.append('rm ' + self.path('luma'))
        return '\n'.join(out) + '\n'

    def shell(self, daemon):
        q = shlex.quote
        code = ['. %s' % q(daemon), 'rm -f %s' % q(self.path('console')), 'SLP=8', '''iter() {
  read_daynight; dn_log
  [ "$DN_MODE" != "2" ] && return 0
  dn_ir_guard && return 0
  if [ "$DAYNIGHT_SOURCE" = vendor ]; then SLP=2; dn_step_vendor && return 0
  elif [ "$DAYNIGHT_SOURCE" != luma ]; then SLP=2; dn_step_ae && return 0; fi
  SLP=8; dn_step_luma
}''']
        for s in self.steps:
            k = s[0]
            if k == 'now':
                code.append('DN_NOW=%d' % s[1])
            elif k == 'night':
                code += ['iter', 'echo "slp=$SLP"', 'cat %s 2>/dev/null; rm -f %s' % (q(self.path('console')), q(self.path('console'))),
                         'echo @ircut', 'cat %s' % q(self.path('ircut')), 'echo ---']
            elif k in ('ae', 'luma', 'awb', 'rtsp', 'conf'):
                code.append('printf "%%s\\n" %s > %s' % (q(s[1]), q(self.path(self.FILES[k]))))
            elif k == 'aen':
                code.append('printf "%%s" %s > %s' % (q(s[1]), q(self.path('ae'))))
            elif k == 'rmae':
                code.append('rm -f ' + q(self.path('ae')))
            elif k == 'rmluma':
                code.append('rm -f ' + q(self.path('luma')))
        return '\n'.join(code) + '\n'


def mask_log(text):
    return re.sub(r'(?m)^\d\d:\d\d ', 'HH:MM ', text)


@unittest.skipUnless(HAVE_CC, 'needs cc')
class AutoNightParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.nm = fake_nightmode(self.d)
        self.env = dict(os.environ, TZ='UTC', DN_CONSOLE=str(self.d / 'console'), CAM_AE=str(self.d / 'ae'),
                        CAM_LUMA=str(self.d / 'luma'), CAM_AWB=str(self.d / 'awb'), DN_IRCUT=str(self.d / 'ircut'),
                        DN_NIGHTMODE=str(self.nm), DN_CONF=str(self.d / 'daynight.conf'),
                        DN_RTSPCONF=str(self.d / 'rtspserver.conf'), DN_LOG=str(self.d / 'daynight.log'),
                        DN_LOG_EVERY='20', BUTTON_L66_FLAG=str(self.d / 'nolinux66'))

    def tearDown(self):
        self.tmp.cleanup()

    def reset(self):
        for n in ('ircut', 'calls', 'console', 'daynight.log', 'daynight.log.1', 'ae', 'luma', 'awb', 'daynight.conf',
                  'rtspserver.conf'):
            (self.d / n).unlink(missing_ok=True)
        (self.d / 'ircut').write_text('1\n')

    def run_shell(self, sc):
        self.reset()
        env = dict(self.env, DN_TEST='1')
        (self.d / 'harness.sh').write_text(sc.shell(str(ROOT / 'scripts/auto-night-daemon.sh')))
        r = subprocess.run(SHELL + [str(self.d / 'harness.sh')], capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.collect(r.stdout)

    def run_c(self, sc):
        self.reset()
        script = self.d / 'replay.txt'
        script.write_text(sc.replay())
        r = subprocess.run([str(self.bin), '-r', str(script)], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.collect(r.stdout)

    def collect(self, out):
        def rd(n):
            p = self.d / n
            return p.read_text() if p.exists() else ''
        return out, rd('calls'), mask_log(rd('daynight.log')), mask_log(rd('daynight.log.1'))

    def compare(self, sc, label=''):
        a, b = self.run_shell(sc), self.run_c(sc)
        # the shell prints slp= before the console text, the C replay after `night`: both print slp first
        for i, (x, y) in enumerate(zip(a, b)):
            self.assertEqual(x, y, '%s: part %d differs\nshell:\n%s\nC:\n%s' % (label, i, x, y))
        return a

    # --- scenarios ---

    def ae(self, lumi=40, exp=100, a=256, d=256, i=256, dark=0, m=''):
        return '%d %d %d %d %d %d %s' % (lumi, exp, a, d, i, dark, m)

    def test_ae_source_dusk_and_dawn(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=ae\nMIN_SWITCH=0\nNIGHT_HOLD=10\nDAY_HOLD=30\nIR_LED_MAX_ON=0')
        t = 100
        for exp in [100] * 3 + [30000] * 8 + [5000] * 4 + [100] * 20:
            t += 2
            sc.add('now', t)
            sc.add('ae', self.ae(exp=exp))
            sc.add('night')
        out, calls, _, _ = self.compare(sc)
        self.assertEqual(calls.split(), ['on', 'off'])

    def test_isp_flag_and_min_switch(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=isp\nNIGHT_HOLD=4\nDAY_HOLD=4\nMIN_SWITCH=30\nIR_LED_MAX_ON=0')
        t = 0
        for dark in [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1] * 3:
            t += 2
            sc.add('now', t)
            sc.add('ae', self.ae(dark=dark))
            sc.add('night')
        out, calls, _, _ = self.compare(sc)
        self.assertIn('waiting 30 s', out)           # the minimum time between switches is exercised

    def test_luma_source_and_thresholds(self):
        sc = Scenario(self.d)
        sc.add('conf', 'LUMA_NIGHT=30\nLUMA_DAY=90\nMIN_SWITCH=0\nIR_LED_MAX_ON=0\nLUMA_DAY=999')
        t = 10
        for luma in [120, 20, 25, 25, 60, 95, 95, 95, 10, 10, 29, 29, 91, 5000, 'x', '', 91, 92, 12, 12]:
            t += 8
            sc.add('now', t)
            sc.add('luma', str(luma))
            sc.add('night')
        sc.add('rmluma')
        sc.add('night')
        out, calls, _, _ = self.compare(sc)
        self.assertEqual(calls.split(), ['on', 'off', 'on', 'off', 'on'][:len(calls.split())])
        self.assertGreaterEqual(len(calls.split()), 3)

    def test_a_missing_luma_file_reads_50(self):
        """CLEANUP-1124: no /tmp/cam_luma gives luma 50 in both (the mean of the cached JPEG's first bytes is gone)"""
        for night, want in ((60, ['on']), (40, [])):
            with self.subTest(LUMA_NIGHT=night):
                sc = Scenario(self.d)
                sc.add('conf', 'DAYNIGHT_SOURCE=luma\nLUMA_NIGHT=%d\nLUMA_DAY=999\nMIN_SWITCH=0\nIR_LED_MAX_ON=0' % night)
                sc.add('rmluma')
                for t in (10, 18, 26):
                    sc.add('now', t)
                    sc.add('night')
                out, calls, _, _ = self.compare(sc)
                self.assertEqual(calls.split(), want)
                if want:
                    self.assertIn('luma=50', out)
        for f in ('src/supervisord/supervisord.c', 'scripts/auto-night-daemon.sh'):
            self.assertNotIn('currentpic.cache.jpg', (ROOT / f).read_text(encoding='utf-8'), f)

    def test_vendor_source_with_awb_lock_and_stale_counts(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=vendor\nMIN_SWITCH=0\nIR_LED_MAX_ON=0\nVENDOR_LOCK=100')
        t = 0
        rnd = random.Random(7)
        for n in range(120):
            t += 2
            sc.add('now', t)
            bright = (n // 15) % 2 == 0
            exp = rnd.choice([2000, 2812]) if not bright else rnd.choice([50, 200, 400])
            sc.add('ae', self.ae(lumi=rnd.choice([30, 40, 60]), exp=exp, a=rnd.choice([256, 4000, 9000]), d=256, i=256,
                                 m='2812' if rnd.random() < .7 else ''))
            if n % 4 == 0:
                sc.add('awb', '%s 100 100 100 100 100 100 100 100 100 5000' % rnd.choice([100, 90000, 30000, 2000]))
            sc.add('night')
        self.compare(sc)

    def test_awb_restart_ignore_prevents_false_day(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=vendor\nMIN_SWITCH=0\nIR_LED_MAX_ON=0\nAWB_RESTART_IGNORE=30')
        # Start in night mode (ircut=0) with dark lum, then CAM_AE disappears and returns (video restart)
        # followed by an AWB spike for 20 s: must NOT switch to day during the 30 s ignore window.
        sc.add('cut', '0')
        sc.add('now', 100)
        sc.add('ae', self.ae(lumi=40, exp=100, a=256, d=256, i=256, m='1125'))
        sc.add('awb', '100 100 100 100 100 100 100 100 100 100 5000')
        sc.add('night')
        # Simulate video restart: CAM_AE missing, then returns at t=110 with AWB spike
        sc.add('ae', '')
        sc.add('now', 105)
        sc.add('night')
        for t in (110, 118, 126, 134):
            sc.add('now', t)
            sc.add('ae', self.ae(lumi=40, exp=100, a=256, d=256, i=256, m='1125'))
            sc.add('awb', '%d 100 100 100 100 100 100 100 100 100 5000' % (5000 + t))
            sc.add('night')
        out = self.compare(sc)
        self.assertEqual(out[1], '')

    def test_ir_led_protection_and_manual_mode(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=ae\nMIN_SWITCH=0\nNIGHT_HOLD=2\nDAY_HOLD=600\nIR_LED_MAX_ON=60\nIR_LED_REST=30')
        t = 0
        for n in range(80):
            t += 5
            sc.add('now', t)
            sc.add('ae', self.ae(exp=40000))
            if n == 60:
                sc.add('rtsp', 'daynight=3\n[0]\nfps=15')
            if n == 70:
                sc.add('rtsp', 'daynight 2\n[0]\nfps=15')
            sc.add('night')
        out, calls, _, _ = self.compare(sc)
        self.assertIn('IR LED protection', out)
        self.assertIn('off', calls.split())

    def test_dawn_flip_flop_and_ir_lift_hysteresis(self):
        # F6: IR-LED illumination lowering AE index slightly and brief bright spikes must not bounce night back to day.
        sc_ae = Scenario(self.d)
        sc_ae.add('conf', 'DAYNIGHT_SOURCE=ae\nAE_NIGHT_ABOVE=15000\nAE_DAY_BELOW=3000\n'
                          'NIGHT_HOLD=10\nDAY_HOLD=60\nMIN_SWITCH=180\nIR_LED_MAX_ON=0')
        t = 0
        for exp in (
            [200] * 3 +          # day baseline
            [20000] * 8 +        # dusk -> switches on at t=22
            [4000] * 10 +        # IR turns on, exposure drops into deadband (above AE_DAY_BELOW)
            [500] * 10 +         # brief 20 s bright glitch (< DAY_HOLD=60)
            [4500] * 4 +         # back into deadband: resets DAY_HOLD
            [500] * 70           # true dawn: holds >60 s, waits for MIN_SWITCH=180, then off
        ):
            t += 2
            sc_ae.add('now', t)
            sc_ae.add('ae', self.ae(exp=exp))
            sc_ae.add('night')
        out_ae, calls_ae, _, _ = self.compare(sc_ae, 'dawn_ae')
        self.assertEqual(calls_ae.split(), ['on', 'off'])
        self.assertIn('waiting 180 s', out_ae)

        # Vendor mode: quick bounce within 15 s due to IR lift locks state for VENDOR_LOCK seconds.
        sc_v = Scenario(self.d)
        sc_v.add('conf', 'DAYNIGHT_SOURCE=vendor\nMIN_SWITCH=0\nIR_LED_MAX_ON=0\nVENDOR_LOCK=900')
        step = 0
        for t_now, exp, a_gain, w0 in [
            (20, 1000, 9000, 100), (22, 1000, 9000, 101), (24, 1000, 9000, 102),  # switch on at t=24
            (26, 200, 256, 5000),  (28, 200, 256, 5001),  (30, 200, 256, 5002),   # bounce <15s -> lock 900s
            (32, 200, 256, 5003),  (34, 200, 256, 5004),  (36, 200, 256, 5005),
        ] + [(t, 200, 256, 5000) for t in range(38, 80, 2)]:   # the lock opens at the next decision (lum 30 % away)
            step += 1
            sc_v.add('now', t_now)
            sc_v.add('ae', self.ae(lumi=40, exp=exp, a=a_gain, d=256, i=256, m='1125'))
            sc_v.add('awb', '%d 100 100 100 100 100 100 100 100 100 5000' % (w0 + step))
            sc_v.add('night')
        out_v, calls_v, _, _ = self.compare(sc_v, 'dawn_vendor')
        # the real behaviour: the lock is set within 15 s of the switch, but the other mode's lum is always more than
        # 30 % away from the lum of the switch, so it opens at the next decision and the day switch goes through at
        # about t=42 (18 s after the switch). With the backoff on the lock is practically inert; the backoff is the anti-flap.
        self.assertEqual(calls_v.split(), ['on', 'off'])
        self.assertIn('switching back within 15 s: locked for 900 s', out_v)
        self.assertEqual(out_v.count('Switching to DAY'), 1)

    # --- DN-FLAP: day held back after a day -> night round trip (vendor source) ---

    # The camera of the field data (.11, dim room), closed loop on the shell daemon: night (IR on) lum 1400-2000 wave
    # (below VENDOR_DAY_LUM 1536 for about 70 s of each 300 s) with visible light; day (IR off) lum 4500 at maximum gain
    # while the AWB counts hold day (300000, > AWB_DAY_CNT) for 240-440 s, then dip (100000) -> night wanted. The
    # inputs of every step are recorded, then replayed through the shell and the C daemon (parity) by `compare`.
    FLAP_HARNESS = """
. %(daemon)s
rm -f %(d)s/console
SLP=8
iter() {
  read_daynight; dn_log
  [ "$DN_MODE" != "2" ] && return 0
  dn_ir_guard && return 0
  if [ "$DAYNIGHT_SOURCE" = vendor ]; then SLP=2; dn_step_vendor && return 0
  elif [ "$DAYNIGHT_SOURCE" != luma ]; then SLP=2; dn_step_ae && return 0; fi
  SLP=8; dn_step_luma
}
T=1000; END=$((T + %(secs)d)); SUNRISE=%(sunrise)d; SUNSET=%(sunset)d; BOUNCE=%(bounce)d
PREV=1; DAY_T0=$T; CYC=0
while [ $T -lt $END ]; do
  read -r IC < %(d)s/ircut
  if [ "$IC" = 1 ] && [ "$PREV" = 0 ]; then DAY_T0=$T; CYC=$((CYC + 1)); fi
  PREV=$IC
  B=$((T %% 53))
  if [ "$IC" = 0 ]; then
    X=$((T %% 300)); [ $X -gt 150 ] && X=$((300 - X))
    LUM=$((1400 + X * 4)); AWB="$((5000 + B)) 100 100 100 100 100 100 100 100 100 5000"
  else
    LUM=4500
    if [ $CYC -eq 0 ]; then D=0; else D=$((240 + (CYC * 97) %% 200)); fi
    if [ $((T - DAY_T0)) -lt $D ]; then AWB="$((300000 + B)) 100 100 100 100 100 100 100 100 100 5000"
    else AWB="$((100000 + B)) 100 100 100 100 100 100 100 100 100 5000"; fi
  fi
  if [ $BOUNCE -eq 1 ]; then   # a scene that wants the other mode at once, in both directions
    if [ "$IC" = 0 ]; then LUM=1000; AWB="$((5000 + B)) 100 100 100 100 100 100 100 100 100 5000"
    else LUM=4500; AWB="$((100000 + B)) 100 100 100 100 100 100 100 100 100 5000"; fi
  fi
  if [ $SUNSET -gt 0 ] && [ $T -ge $SUNSET ]; then LUM=4500; AWB="$((100000 + B)) 100 100 100 100 100 100 100 100 100 5000"
  elif [ $SUNRISE -gt 0 ] && [ $T -ge $SUNRISE ]; then LUM=300; AWB="$((5000 + B)) 100 100 100 100 100 100 100 100 100 5000"; fi
  AE="40 $((LUM * 1125 / 256)) 256 256 256 0 1125"
  printf "%%s\\n" "$AE" > %(d)s/ae; printf "%%s\\n" "$AWB" > %(d)s/awb
  echo "$T|$AE|$AWB" >> %(d)s/trace
  DN_NOW=$T; iter
  read -r IC2 < %(d)s/ircut
  if [ "$IC2" != "$IC" ]; then if [ "$IC2" = 1 ]; then echo "$T day" >> %(d)s/sw; else echo "$T night" >> %(d)s/sw; fi; fi
  T=$((T + %(step)d))
done
"""

    def flap_run(self, conf, secs, sunrise=0, sunset=0, parity=True, step=2, bounce=0):
        """-> (switches [(t - 1000, 'day'|'night')], flap log lines); the same inputs are then replayed by shell and C"""
        self.reset()
        for n in ('sw', 'trace'):
            (self.d / n).unlink(missing_ok=True)
        (self.d / 'daynight.conf').write_text(conf + '\n')
        (self.d / 'harness.sh').write_text(self.FLAP_HARNESS % dict(daemon=str(ROOT / 'scripts/auto-night-daemon.sh'),
                                           d=str(self.d), secs=secs, sunrise=sunrise, sunset=sunset, step=step, bounce=bounce))
        env = dict(self.env, DN_TEST='1', DN_LOG_EVERY='99999999')
        r = subprocess.run(SHELL + [str(self.d / 'harness.sh')], capture_output=True, text=True, env=env, timeout=170)
        self.assertEqual(r.returncode, 0, r.stderr)
        sw = [(int(a) - 1000, b) for a, b in (ln.split() for ln in (self.d / 'sw').read_text().splitlines())] \
            if (self.d / 'sw').exists() else []
        log = (self.d / 'daynight.log').read_text() if (self.d / 'daynight.log').exists() else ''
        flap = [re.sub(r'^\d\d:\d\d \[auto-night\] ', '', ln) for ln in log.splitlines()
                if 'held back' in ln or 'hold reset' in ln]
        if parity:
            sc = Scenario(self.d)
            sc.add('conf', conf)
            for ln in (self.d / 'trace').read_text().splitlines():
                t, ae, awb = ln.split('|')
                sc.add('now', int(t)); sc.add('ae', ae); sc.add('awb', awb); sc.add('night')
            self.compare(sc, 'flap')
        return sw, flap

    FLAP_CONF = 'DAYNIGHT_SOURCE=vendor\nIR_LED_MAX_ON=0\nMIN_SWITCH=180\n'

    def test_flap_evening_switches_drop(self):
        """the field pattern over a 2 h evening: switches to day drop from 6 (3.0.1 behaviour) to at most 3"""
        off, off_log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_BACKOFF=0', 7200, parity=False)
        on, on_log = self.flap_run(self.FLAP_CONF, 7200)
        days_off = [t for t, k in off if k == 'day']
        days_on = [t for t, k in on if k == 'day']
        self.assertEqual(off_log, [])           # the switch off: no hold, no log line
        self.assertGreaterEqual(len(days_off), 5, off)   # 3.0.1 behaviour (the lock holds some of the bounces)
        self.assertLessEqual(len(days_on), 3, on)
        self.assertLessEqual(len(on), 7, on)    # all switches, night ones included
        self.assertTrue(on_log[0].startswith('day held back 15 min after a round trip'), on_log)
        self.assertEqual([k for _, k in on][:2], ['night', 'day'])
        # a night switch is never held back: it follows the AWB dip (day phase 240-440 s) within the MIN_SWITCH wait
        for (t0, k0), (t1, k1) in zip(on, on[1:]):
            if k0 == 'day' and k1 == 'night':
                self.assertLessEqual(t1 - t0, 440 + 15, (t0, t1))

    def test_flap_hold_grows_15_30_60_120_and_is_capped(self):
        sw, log = self.flap_run(self.FLAP_CONF, 6 * 3600, step=6)   # a sample every 6 s: the replay script stays small
        holds = [int(re.search(r'held back (\d+) min', ln).group(1)) for ln in log if 'held back' in ln]
        self.assertEqual(holds[:5], [15, 30, 60, 120, 120], log)
        self.assertEqual(max(holds), 120)
        # a day switch comes no sooner than the hold after the night switch that set it
        n = 0
        for (t0, k0), (t1, k1) in zip(sw, sw[1:]):
            if k0 == 'night' and k1 == 'day':
                if n >= 1:
                    self.assertGreaterEqual(t1 - t0, min(holds[n - 1], 120) * 60, (n, t0, t1, holds))
                n += 1

    def test_flap_real_sunrise_resets_and_switches_to_day_at_once(self):
        """held back (30 min or more), then lum falls to 300 for good: day after 5 min of it, not after the hold"""
        probe, plog = self.flap_run(self.FLAP_CONF, 5400, parity=False)
        self.assertTrue(any('held back 30 min' in ln for ln in plog), plog)
        night_t = [t for t, k in probe if k == 'night'][-1]
        sunrise = night_t + 120         # the last night switch of the probe, the sunrise just after it
        sw, log = self.flap_run(self.FLAP_CONF, sunrise + 900, sunrise=1000 + sunrise)
        day_after = [t for t, k in sw if k == 'day' and t >= sunrise]
        self.assertEqual(len([ln for ln in log if 'hold reset' in ln]), 1, log)
        self.assertTrue(day_after, sw)
        self.assertGreaterEqual(day_after[0] - sunrise, 5 * 60)                    # not before the 5 minutes
        self.assertLessEqual(day_after[0] - sunrise, 5 * 60 + 30, (sunrise, sw))   # then at once

    def test_flap_night_switch_never_delayed(self):
        """a sunset after a sunrise, with the hold engaged before: night after the 3 samples, as with the switch off"""
        sr, ss = 1000 + 3600 * 2, 1000 + 3600 * 2 + 1800
        for conf in (self.FLAP_CONF, self.FLAP_CONF + 'DN_FLAP_BACKOFF=0'):
            sw, _ = self.flap_run(conf, 3 * 3600, sunrise=sr, sunset=ss, parity=False)
            nights = [t for t, k in sw if k == 'night' and t >= ss - 1000]
            self.assertTrue(nights, (conf, sw))
            self.assertLessEqual(nights[0] - (ss - 1000), 12, (conf, sw))

    def test_flap_switch_off_no_hold_and_no_flap_line(self):
        """DN_FLAP_BACKOFF=0: no hold, no flap line, the round trips go on"""
        sw, log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_BACKOFF=0', 3600)
        self.assertEqual(log, [])
        self.assertGreaterEqual(len([1 for _, k in sw if k == 'day']), 3)

    def test_flap_opposite_want_inside_min_switch_both_directions(self):
        """A scene that wants the other mode at once, MIN_SWITCH=180, 1 h. 3.0.1 (measured by the review): 4 switches,
        because a want of the other mode inside MIN_SWITCH started the VENDOR_LOCK lock (900 s) in both directions.
        DN_FLAP_BACKOFF=0 must give exactly that; with the backoff on the lock no longer starts from a wait, the
        backoff holds the day switch instead."""
        off, off_log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_BACKOFF=0', 3600, bounce=1)
        on, on_log = self.flap_run(self.FLAP_CONF, 3600, bounce=1)
        self.assertEqual(off_log, [])
        self.assertEqual(len(off), 4, off)
        self.assertEqual([k for _, k in off], ['night', 'day', 'night', 'day'])
        self.assertLessEqual(len(on), 7, on)
        self.assertTrue(on_log, on)

    def test_flap_leading_zeros_in_the_keys(self):
        """08 is a syntax error and 010 is octal in the shell's $(( )): both are read as decimal, as in C;
        DN_FLAP_BACKOFF=00 is off"""
        sw, log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_WINDOW_MIN=08' + chr(10) + 'DN_FLAP_MAX_MIN=010' + chr(10) + 'DN_DAY_RESET_MIN=05', 3600)
        holds = [int(re.search(r'held back (\d+) min', ln).group(1)) for ln in log if 'held back' in ln]
        self.assertEqual(holds[:2], [8, 10], log)
        self.assertEqual([k for _, k in sw][:2], ['night', 'day'])
        sw, log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_BACKOFF=00', 3600)
        self.assertEqual(log, [])

    def test_flap_max_cap_also_limits_a_running_hold(self):
        """a lowered DN_FLAP_MAX_MIN applies to a hold that is already running"""
        sw, log = self.flap_run(self.FLAP_CONF + 'DN_FLAP_MAX_MIN=20', 3 * 3600, parity=False)
        holds = [int(re.search(r'held back (\d+) min', ln).group(1)) for ln in log if 'held back' in ln]
        self.assertEqual(holds[:3], [15, 20, 20], log)
        n = 0
        for (t0, k0), (t1, k1) in zip(sw, sw[1:]):
            if k0 == 'night' and k1 == 'day':
                if n >= 1: self.assertLessEqual(t1 - t0, 20 * 60 + 300, (t0, t1))
                n += 1

    def test_garbage_and_missing_inputs_fall_back_to_luma(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=ae\nMIN_SWITCH=0\nIR_LED_MAX_ON=0\nAE_NIGHT_ABOVE=abc\nAE_DAY_BELOW=0001\nNIGHT_HOLD=0\n'
               'DAY_HOLD=99999\nLUMA_NIGHT=007\nIR_LED_MODE=nonsense')
        t = 0
        lines = ['', 'x y z', '1 2 3', '40 0100 256 256 256 0', '40 100 256 256 256 0 9 9 9', '40 1234567890 256 256 256 0',
                 '40 100 256 256 256 1', '40 5000 6000 256 256 0 1125', '40 100 256 256 256 0']
        for ln in lines * 3:
            t += 2
            sc.add('now', t)
            sc.add('ae', ln)
            sc.add('luma', '5')
            sc.add('night')
        sc.add('aen', '40 100 256 256 256 0')       # no newline at the end: read fails, the source falls back
        sc.add('night')
        sc.add('rmae')
        sc.add('night')
        self.compare(sc)

    def test_random_series_every_source(self):
        for seed, src in enumerate(['luma', 'ae', 'isp', 'vendor'] * 3):
            rnd = random.Random(seed)
            sc = Scenario(self.d)
            conf = ['DAYNIGHT_SOURCE=' + src, 'MIN_SWITCH=%d' % rnd.choice([0, 20, 60]), 'NIGHT_HOLD=%d' % rnd.choice([2, 6, 10]),
                    'DAY_HOLD=%d' % rnd.choice([4, 20, 60]), 'IR_LED_MAX_ON=%d' % rnd.choice([0, 90, 400]),
                    'IR_LED_REST=%d' % rnd.choice([20, 120]), 'VENDOR_NIGHT_LUM=%d' % rnd.choice([1000, 3584]),
                    'VENDOR_DAY_LUM=%d' % rnd.choice([500, 1536]), 'AE_NIGHT_ABOVE=%d' % rnd.choice([8000, 15000]),
                    'AE_DAY_BELOW=%d' % rnd.choice([1000, 3000, 20000]), 'LUMA_NIGHT=%d' % rnd.choice([30, 40]),
                    'LUMA_DAY=%d' % rnd.choice([80, 100])]
            sc.add('conf', '\n'.join(conf))
            t = rnd.randint(0, 50)
            for n in range(200):
                t += rnd.choice([2, 2, 2, 8, 3])
                sc.add('now', t)
                phase = (n // 25) % 2
                exp = rnd.choice([30, 300, 900]) if phase == 0 else rnd.choice([1124, 1124, 800])
                gain = rnd.choice([256, 600]) if phase == 0 else rnd.choice([6840, 9000, 256])
                sc.add('ae', self.ae(lumi=rnd.choice([30, 40, 50]), exp=exp, a=gain, d=rnd.choice([256, 300]), i=256,
                                     dark=int(phase == 1 and rnd.random() < .9), m=rnd.choice(['', '1125', '2812'])))
                sc.add('luma', str(rnd.choice([10, 20, 35, 45, 90, 120, 200]) if phase == 0 else rnd.choice([5, 15, 60, 110])))
                if n % 3 == 0:
                    sc.add('awb', '%d %d 300 0 0 0 0 0 0 0 5000' % (rnd.choice([0, 2000, 60000]), rnd.choice([0, 3000])))
                sc.add('night')
            self.compare(sc, 'seed %d %s' % (seed, src))

    def test_calibration_log_kept_to_400_lines(self):
        sc = Scenario(self.d)
        sc.add('conf', 'DAYNIGHT_SOURCE=ae\nIR_LED_MAX_ON=0')
        for n in range(1, 900):
            sc.add('now', n * 20)
            sc.add('ae', self.ae())
            sc.add('luma', '77')
            sc.add('awb', '1 2 3 4 5 6 7 8 9 10 11')
            sc.add('night')
        out, calls, log, log1 = self.compare(sc)
        self.assertEqual(len(log.splitlines()), 99)
        self.assertEqual(len(log1.splitlines()), 400)
        self.assertIn('mode=day src=ae luma=77 ae=40 100 256 256 256 0 idx=100 lum=22 awb=1 2 3', log.splitlines()[0].replace('HH:MM ', ''))


# ---------------------------------------------------------------- reset button

class ButtonRig:
    def __init__(self, d, storage='flash'):
        self.d = d
        self.value = d / 'gpio' / 'value'
        self.value.parent.mkdir(exist_ok=True)
        self.value.write_text('1\n')
        (d / 'linux66').write_text('')
        (d / 'storage').write_text(storage + '\n')
        for name, line in (('fc.sh', 'echo "fc $*"'), ('reboot', 'echo reboot'), ('rescue.sh', 'echo "rescue $*"'),
                           ('tracker.sh', 'echo "tracker $*"')):
            (d / name).write_text('#!/bin/sh\n%s >> "%s/bcalls"\n' % (line, d))
            (d / name).chmod(0o755)
        self.env = dict(os.environ, BUTTON_GPIO_DIR=str(d / 'gpio'), BUTTON_L66_FLAG=str(d / 'linux66'),
                        BUTTON_DEV=str(d / 'no-event'), BUTTON_FLASH_CODE=str(d / 'fc.sh'),
                        BUTTON_REBOOT_CMD=str(d / 'reboot'), BUTTON_RESCUE=str(d / 'rescue.sh'),
                        BUTTON_TRACKER=str(d / 'tracker.sh'), TC100_STORAGE_FILE=str(d / 'storage'))

    def calls(self, drop_tracker=True):
        p = self.d / 'bcalls'
        lines = p.read_text().split('\n')[:-1] if p.exists() else []
        lines = [x.replace('rescue start-ap reset button', 'rescue') for x in lines]
        return [x for x in lines if not (drop_tracker and x.startswith('tracker'))]

    def press(self, seconds, scale=1.0):
        self.value.write_text('0\n')
        time.sleep(seconds * scale)
        self.value.write_text('1\n')


@unittest.skipUnless(HAVE_CC, 'needs cc')
class Button(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def replay(self, ticks, storage='flash', extra=None):
        """ticks: a string of 0 (pressed) and 1 (released), one per second"""
        (self.d / 'bcalls').unlink(missing_ok=True)
        rig = ButtonRig(self.d, storage)
        (self.d / 'r.txt').write_text(''.join('button %s\n' % c for c in ticks))
        env = dict(rig.env, **(extra or {}))
        r = subprocess.run([str(self.bin), '-r', str(self.d / 'r.txt')], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(0.3)          # the rescue script runs in the background
        return rig.calls(False), [x for x in r.stdout.splitlines() if x.startswith('log ')]

    def test_hold_durations_tick_by_tick(self):
        calls, logs = self.replay('1' + '0' * 2 + '1')
        self.assertEqual((calls, logs), ([], []))                                            # 2 s: nothing
        calls, logs = self.replay('1' + '0' * 3 + '1' + '0' * 7 + '1')
        self.assertEqual(calls, ['rescue', 'rescue'])                                        # 3 s and 7 s: rescue
        self.assertEqual(logs, ['log button: held 3s: rescue access point', 'log button: held 7s: rescue access point'])
        calls, logs = self.replay('1' + '0' * 8 + '1')
        self.assertEqual(calls, ['tracker intent reset button held 8s', 'reboot'])
        calls, logs = self.replay('1' + '0' * 19 + '1')
        self.assertEqual(calls, ['tracker intent reset button held 19s', 'reboot'])
        calls, logs = self.replay('1' + '0' * 20 + '1')
        self.assertEqual(calls, ['fc clear', 'tracker intent reset button held 20s', 'reboot'])
        self.assertEqual(logs, ['log button: held 20s: back to the built-in code, reboot'])
        calls, logs = self.replay('1' + '0' * 21 + '1', storage='sd')
        self.assertEqual(calls, ['tracker intent reset button held 21s', 'reboot'])
        self.assertEqual(logs, ['log button: held 21s: reboot'])

    def test_stuck_button_never_acts(self):
        self.assertEqual(self.replay('0' * 40)[0], [])                                       # never seen released

    def test_thresholds_from_the_environment(self):
        calls, _ = self.replay('1' + '0' * 5 + '1', extra=dict(BUTTON_REBOOT_SECONDS='5'))
        self.assertEqual(calls, ['tracker intent reset button held 5s', 'reboot'])

    def test_shell_script_and_c_daemon_agree_in_real_time(self):
        """the same presses (1 s, 3 s, 5 s, 8 s) on the same fake GPIO file: scripts/button-watch.sh and the daemon"""
        presses = [1, 3, 5, 8]
        results = {}

        def drive(rig):
            time.sleep(1.5)
            for p in presses:
                rig.press(p + 0.4)         # a little over, as the samples come once a second
                time.sleep(1.6)

        for who in ('shell', 'c'):
            d = self.d / who
            d.mkdir()
            rig = ButtonRig(d)
            env = dict(rig.env)
            if who == 'shell':
                proc = subprocess.Popen(SHELL + [str(ROOT / 'scripts/button-watch.sh')], env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                (d / 'flag').write_text('')
                env.update(SV_BUTTON_FLAG=str(d / 'flag'), SV_NIGHT_FLAG=str(d / 'noflag'), SV_PIDFILE=str(d / 'pid'))
                proc = subprocess.Popen([str(self.bin)], env=env, stdin=subprocess.DEVNULL)
            t = threading.Thread(target=drive, args=(rig,))
            t.start()
            t.join()
            time.sleep(1.5)
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
            results[who] = rig.calls()
        self.assertEqual(results['shell'], results['c'])
        self.assertEqual(results['c'], ['rescue', 'rescue', 'reboot'])


# ---------------------------------------------------------------- the real daemon and its switch

@unittest.skipUnless(HAVE_CC, 'needs cc')
class Daemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.nm = fake_nightmode(self.d)
        (self.d / 'ircut').write_text('1\n')
        self.rig = ButtonRig(self.d)
        self.env = dict(self.rig.env, SV_TICK_DIV='20', SV_NIGHT_FLAG=str(self.d / 'night.flag'),
                        SV_BUTTON_FLAG=str(self.d / 'button.flag'), SV_SOUND_FLAG=str(self.d / 'sound.flag'), SV_PIDFILE=str(self.d / 'sv.pid'),
                        DN_CONSOLE=str(self.d / 'console'), CAM_LUMA=str(self.d / 'luma'), CAM_AE=str(self.d / 'ae'),
                        DN_IRCUT=str(self.d / 'ircut'), DN_NIGHTMODE=str(self.nm), DN_CONF=str(self.d / 'daynight.conf'),
                        DN_RTSPCONF=str(self.d / 'rtspserver.conf'), DN_LOG=str(self.d / 'daynight.log'), TZ='UTC')
        (self.d / 'daynight.conf').write_text('MIN_SWITCH=0\nIR_LED_MAX_ON=0\nDAYNIGHT_SOURCE=luma\n')
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.tmp.cleanup()

    def start(self, env=None):
        self.proc = subprocess.Popen([str(self.bin)], env=dict(self.env, **(env or {})), stdin=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        return self.proc

    def wait_for(self, fn, timeout=30):     # returns as soon as fn() holds; 30 s only matters on a loaded CI runner
        end = time.time() + timeout
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.05)
        return False

    def nm_calls(self):
        p = self.d / 'calls'
        return p.read_text().split() if p.exists() else []

    def test_both_jobs_in_one_process(self):
        (self.d / 'luma').write_text('10\n')
        (self.d / 'night.flag').write_text('')
        (self.d / 'button.flag').write_text('')
        self.start()
        self.assertTrue(self.wait_for(lambda: self.nm_calls() == ['on']))                    # two dark samples: night
        self.assertIn('NIGHT mode', (self.d / 'console').read_text())
        (self.d / 'luma').write_text('200\n')
        self.assertTrue(self.wait_for(lambda: self.nm_calls() == ['on', 'off']))
        self.rig.press(0.3)                                                                  # 3 ticks of 50 ms: rescue
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['rescue']))
        self.rig.press(0.55)                                                                 # 8 ticks: reboot
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['rescue', 'reboot']))
        self.assertEqual(int((self.d / 'sv.pid').read_text()), self.proc.pid)
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(timeout=5), 0)
        self.assertFalse((self.d / 'sv.pid').exists())

    def test_exits_when_the_last_flag_is_removed_and_a_second_instance_leaves(self):
        (self.d / 'night.flag').write_text('')
        self.start()
        self.assertTrue(self.wait_for((self.d / 'sv.pid').exists))
        second = subprocess.run([str(self.bin)], env=self.env, timeout=5)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(int((self.d / 'sv.pid').read_text()), self.proc.pid)               # the first one is still the daemon
        (self.d / 'night.flag').unlink()
        self.assertEqual(self.proc.wait(timeout=5), 0)

    def test_manual_day_night_pauses_the_night_job(self):
        (self.d / 'rtspserver.conf').write_text('daynight=3\n[0]\n')
        (self.d / 'luma').write_text('5\n')
        (self.d / 'night.flag').write_text('')
        self.start()
        time.sleep(1.5)
        self.assertEqual(self.nm_calls(), [])
        (self.d / 'rtspserver.conf').write_text('daynight=2\n[0]\n')
        self.assertTrue(self.wait_for(lambda: self.nm_calls() == ['on']))

    def slow_nightmode(self, body):
        """nightmode.sh that logs its start, runs `body`, then switches and logs its end (in self.d/nmlog)"""
        self.nm.write_text('#!/bin/sh\necho "start $1" >> %s/nmlog\n%s\n'
                           'case "$1" in on) echo 0 > %s/ircut ;; off) echo 1 > %s/ircut ;; esac\n'
                           'echo "end $1" >> %s/nmlog\n' % (self.d, body, self.d, self.d, self.d))
        self.nm.chmod(0o755)

    def nmlog(self):
        p = self.d / 'nmlog'
        return p.read_text().splitlines() if p.exists() else []

    def held(self):
        return [int(m) for m in re.findall(r'reset button held (\d+)s', '\n'.join(self.rig.calls(False)))]

    def test_a_slow_nightmode_does_not_cut_the_button_hold(self):
        """audit 2026-11-24 R2: holds made while nightmode.sh runs are measured tick by tick (the wait for the script
        samples the button): an 8 s hold reboots, a 20 s hold goes back to the built-in code, both before the end of
        the switch. 250 ms ticks (SV_TICK_DIV=4), the presses half a tick over."""
        self.slow_nightmode('sleep 12')
        (self.d / 'luma').write_text('10\n')
        (self.d / 'night.flag').write_text('')
        (self.d / 'button.flag').write_text('')
        self.start(dict(SV_TICK_DIV='4'))
        self.assertTrue(self.wait_for(lambda: self.nmlog() == ['start on']))
        self.rig.press(8.5 * 0.25)
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['reboot'], 5))
        time.sleep(0.5)
        self.rig.press(20.5 * 0.25)
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['reboot', 'fc clear', 'reboot'], 5))
        self.assertEqual(self.nmlog(), ['start on'])                                         # still switching
        held = self.held()
        self.assertEqual(len(held), 2, self.rig.calls(False))
        self.assertIn(held[0], (8, 9))
        self.assertIn(held[1], (20, 21))
        self.assertTrue(self.wait_for(lambda: self.nmlog() == ['start on', 'end on'], 15))
        self.assertIsNone(self.proc.poll())

    def test_a_hung_nightmode_is_killed_and_the_button_still_works(self):
        """a nightmode.sh that never ends is killed after DN_NIGHTMODE_TIMEOUT s and logged, the script only: what it
        started in the background (tc100_rtsp restarted by night-mode, the service watchdog) lives on; the button works
        while it hangs and after"""
        self.slow_nightmode('sleep 100 &\necho $! > %s/sleep.pid\nwait' % self.d)
        (self.d / 'luma').write_text('10\n')
        (self.d / 'night.flag').write_text('')
        (self.d / 'button.flag').write_text('')
        self.start(dict(SV_TICK_DIV='4', DN_NIGHTMODE_TIMEOUT='4'))
        self.assertTrue(self.wait_for(lambda: self.nmlog() == ['start on'] and (self.d / 'sleep.pid').exists()))
        t0 = time.time()
        self.rig.press(3.5 * 0.25)                                                           # rescue, during the hang
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['rescue'], 5))
        self.assertLess(time.time() - t0, 3)
        self.assertTrue(self.wait_for(lambda: 'did not end within 4 s: killed' in (self.d / 'console').read_text(), 10))
        (self.d / 'luma').write_text('200\n')                                                # day already: nothing more to switch
        self.assertEqual(self.nmlog(), ['start on'])                                         # killed before its end
        sleeper = int((self.d / 'sleep.pid').read_text())
        time.sleep(0.5)
        self.assertTrue(proc_alive(sleeper))                                                 # its background child lives on
        os.kill(sleeper, signal.SIGKILL)
        self.rig.press(3.5 * 0.25)
        self.assertTrue(self.wait_for(lambda: self.rig.calls() == ['rescue', 'rescue'], 5))
        self.assertIsNone(self.proc.poll())

    def test_button_job_refused_without_a_gpio_removes_its_flag(self):
        (self.d / 'night.flag').write_text('')
        (self.d / 'button.flag').write_text('')
        self.start(dict(BUTTON_GPIO_DIR=str(self.d / 'nogpio')))
        self.assertTrue(self.wait_for(lambda: not (self.d / 'button.flag').exists()))
        self.assertIsNone(self.proc.poll())                                                  # the night job goes on
        self.proc.terminate()
        self.proc.wait(timeout=5)


    def test_a_new_flag_nonce_restarts_the_night_job(self):
        """audit 2026-11-24 R6: `auto-night-detection restart` removes and re-creates the flag within one tick; the nonce
        sv_start writes in it makes the daemon reset the job (a DN-FLAP hold). An empty flag never restarts it."""
        (self.d / 'night.flag').write_text('')
        self.start()

        def started():                                                                       # the console file is rewritten, not appended
            c = self.d / 'console'
            return c.exists() and 'Daemon started' in c.read_text()
        self.assertTrue(self.wait_for(started))
        (self.d / 'console').unlink()
        time.sleep(2.2)
        self.assertFalse(started())                                                          # empty flag: stable
        (self.d / 'night.flag').write_text('100 5.00\n')                                     # first nonce: the job restarts
        self.assertTrue(self.wait_for(started))                                              # 30 s: a loaded CI runner
        (self.d / 'console').unlink()
        time.sleep(2.2)
        self.assertFalse(started())                                                          # same nonce: nothing
        # a new nonce replacing the flag at once (a rename, as one tick sees it). Not unlink + write: with no flag left the
        # daemon exits on purpose (the service script's sv_start starts it again), and a loaded runner can tick in that gap
        (self.d / 'night.flag.new').write_text('101 9.00\n')
        os.replace(self.d / 'night.flag.new', self.d / 'night.flag')
        self.assertTrue(self.wait_for(started))
        self.assertIsNone(self.proc.poll())
        self.proc.terminate()
        self.proc.wait(timeout=5)

    def test_sv_start_writes_a_nonce_and_it_changes_between_starts(self):
        sup = (ROOT / 'scripts/supervisor.sh').read_text()
        self.assertIn('echo "$$ $_sv_up" >', sup)


# ---------------------------------------------------------------- scripts/supervisor.sh: switch and fallback

@unittest.skipUnless(HAVE_CC, 'needs cc')
class Switch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'run').mkdir()
        self.rig = ButtonRig(self.d)
        (self.d / 'boot.conf').write_text('FOO=1\nSUPERVISOR_IMPL=c\n')
        (self.d / 'daynight.conf').write_text('')
        self.env = dict(self.rig.env, SV_BIN=str(self.bin), SV_RUN=str(self.d / 'run'), SV_BOOTCONF=str(self.d / 'boot.conf'),
                        SV_HK=str(self.d / 'no-housekeeper'), SV_NIGHT_FLAG=str(self.d / 'run/tc100-sv.night'),
                        SV_BUTTON_FLAG=str(self.d / 'run/tc100-sv.button'), SV_SOUND_FLAG=str(self.d / 'run/tc100-sv.sound'),
                        SV_PIDFILE=str(self.d / 'run/tc100-supervisord.pid'),
                        DN_CONSOLE='/dev/null', DN_CONF=str(self.d / 'daynight.conf'), DN_LOG=str(self.d / 'dn.log'),
                        CAM_LUMA=str(self.d / 'luma'), DN_IRCUT=str(self.d / 'ircut'), DN_NIGHTMODE=str(fake_nightmode(self.d)),
                        DN_RTSPCONF=str(self.d / 'rt.conf'))
        (self.d / 'ircut').write_text('1\n')

    def tearDown(self):
        pid = self.d / 'run' / 'tc100-supervisord.pid'
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.tmp.cleanup()

    def sh(self, code):
        return subprocess.run(['sh', '-c', '. %s\n%s' % (shlex.quote(str(ROOT / 'scripts/supervisor.sh')), code)],
                              capture_output=True, text=True, env=self.env, timeout=30)

    def daemon_pid(self):
        return int((self.d / 'run' / 'tc100-supervisord.pid').read_text())

    def alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def test_default_is_the_shell_path(self):
        self.assertIn('\nSUPERVISOR_IMPL=c\n', (ROOT / 'config/boot.conf.dist').read_text())   # C by default since the rc28
        (self.d / 'boot.conf').write_text('FOO=1\n')
        self.assertEqual(self.sh('sv_start night %s x' % (self.d / 'n.pid')).returncode, 1)
        (self.d / 'boot.conf').write_text('SUPERVISOR_IMPL=sh\n')
        self.assertEqual(self.sh('sv_start night %s x' % (self.d / 'n.pid')).returncode, 1)
        (self.d / 'boot.conf').write_text('SUPERVISOR_IMPL=c\n')
        self.env['SV_BIN'] = str(self.d / 'missing')                                         # no binary: shell
        self.assertEqual(self.sh('sv_start night %s x' % (self.d / 'n.pid')).returncode, 1)
        self.assertFalse(any((self.d / 'run').iterdir()))                                    # nothing was started

    def test_two_jobs_one_daemon_and_stop_order(self):
        n, b = self.d / 'n.pid', self.d / 'b.pid'
        self.assertEqual(self.sh('sv_start night %s x' % n).returncode, 0)
        pid = self.daemon_pid()
        self.assertEqual(int(n.read_text()), pid)
        self.assertEqual(self.sh('sv_start button %s y' % b).returncode, 0)
        self.assertEqual(int(b.read_text()), pid)
        self.assertEqual(self.daemon_pid(), pid)                                             # still the same process
        self.sh('sv_stop night %s x' % n)
        self.assertTrue(self.alive(pid))                                                     # the button job still needs it
        self.assertFalse(n.exists())
        self.sh('sv_stop button %s y' % b)
        end = time.time() + 5
        while self.alive(pid) and time.time() < end:
            time.sleep(0.1)
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        self.assertFalse(self.alive(pid) and not self.is_zombie(pid))

    @staticmethod
    def is_zombie(pid):
        try:
            return Path('/proc/%d/stat' % pid).read_text().split(') ')[1][0] == 'Z'
        except (OSError, IndexError):
            return False

    def test_dead_daemon_brings_the_shell_loops_back(self):
        n = self.d / 'n.pid'
        self.assertEqual(self.sh('sv_start night %s x' % n).returncode, 0)
        os.kill(self.daemon_pid(), signal.SIGKILL)
        time.sleep(0.3)
        r = self.sh('sv_start night %s x' % n)
        self.assertEqual(r.returncode, 1)                                                    # the caller starts auto-night-daemon.sh
        self.assertTrue((self.d / 'run' / 'tc100-supervisord.failed').exists())
        self.assertEqual(self.sh('sv_start button %s y' % (self.d / 'b.pid')).returncode, 1)  # for the rest of this boot
        self.assertFalse((self.d / 'run' / 'tc100-sv.night').exists())

    def test_button_without_gpio_falls_back_for_that_job_only(self):
        n = self.d / 'n.pid'
        self.assertEqual(self.sh('sv_start night %s x' % n).returncode, 0)
        self.env['BUTTON_GPIO_DIR'] = str(self.d / 'nogpio')
        # the daemon already runs with the old environment: restart it so the button job sees the missing GPIO
        self.sh('sv_stop night %s x' % n)
        time.sleep(1.2)
        self.assertEqual(self.sh('sv_start night %s x' % n).returncode, 0)
        self.assertEqual(self.sh('sv_start button %s y' % (self.d / 'b.pid')).returncode, 1)
        self.assertTrue(self.alive(self.daemon_pid()))
        self.assertFalse((self.d / 'run' / 'tc100-supervisord.failed').exists())

    def test_control_scripts_use_it_and_keep_the_shell_loop(self):
        an = (ROOT / 'controlscripts/auto-night-detection').read_text()
        ba = (ROOT / 'controlscripts/button-actions').read_text()
        self.assertIn('sv_start night "$PIDFILE" auto-night-detection', an)
        self.assertIn('/bin/sh /mnt/scripts/auto-night-daemon.sh', an)
        self.assertIn('sv_start button "$PIDFILE" button-actions', ba)
        self.assertIn('/bin/sh /mnt/scripts/button-watch.sh', ba)
        for p in ('controlscripts/auto-night-detection', 'controlscripts/button-actions', 'scripts/supervisor.sh',
                  'scripts/housekeeper.sh', 'scripts/service-watchdog.sh'):
            self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / p)]).returncode, 0, p)
        self.assertIn('auto-night-detection) _hk_wpf=', (ROOT / 'scripts/housekeeper.sh').read_text())
        self.assertIn('button-actions)       _wd_pf=', (ROOT / 'scripts/service-watchdog.sh').read_text())

    def test_control_script_start_stop_status(self):
        """controlscripts/auto-night-detection start / status / stop with the C daemon (paths moved to a sandbox)"""
        src = (ROOT / 'controlscripts/auto-night-detection').read_text()
        src = src.replace('/var/run/auto-night-detection.pid', str(self.d / 'run/auto-night-detection.pid'))
        src = src.replace('/mnt/scripts/supervisor.sh', str(ROOT / 'scripts/supervisor.sh'))
        src = src.replace('/mnt/bin/rwconf', 'true').replace('/mnt/scripts/auto-night-daemon.sh', str(ROOT / 'scripts/auto-night-daemon.sh'))
        src = src.replace('[ -f /tmp/linux66 ] && L66=1', 'L66=1')
        cs = self.d / 'an'
        cs.write_text(src)
        env = dict(self.env, SV_RUN=str(self.d / 'run'))
        run = lambda a: subprocess.run(['sh', str(cs), a], capture_output=True, text=True, env=env, timeout=30)
        run('start')
        pid = self.daemon_pid()
        self.assertEqual(run('status').stdout.strip(), 'PID: %d' % pid)
        self.assertEqual(run('health').stdout.strip(), 'ok: running')
        run('stop')
        end = time.time() + 5
        while self.alive(pid) and not self.is_zombie(pid) and time.time() < end:
            time.sleep(0.1)
        self.assertEqual(run('status').stdout.strip(), '')


class Wiring(unittest.TestCase):
    """The switch in the config, the validator, the exchange table, the build and the packaging."""

    def test_validator_and_exchange_row(self):
        ct = ROOT / 'scripts/config-transaction.sh'
        for v, rc in (('c', 0), ('sh', 0), ('', 1), ('C', 1), ('yes', 1), ('c;x', 1)):
            r = subprocess.run(['sh', '-c', '. %s; tc_normalize_and_validate supervisor_impl "$1"' % shlex.quote(str(ct)), 'x', v],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, rc, (v, r.stderr))
        self.assertIn('tc_check_flat "$_tc_file" SUPERVISOR_IMPL supervisor_impl', ct.read_text())
        cgi = (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text().split('\n')
        rows = [i for i, ln in enumerate(cgi) if ln.strip().startswith('row("boot.conf";"flat";"root";"')]
        mine = [i for i, ln in enumerate(cgi) if '"SUPERVISOR_IMPL"' in ln]
        self.assertEqual(len(mine), 1)
        self.assertIn(mine[0] - 1, rows)                              # inside the boot.conf block, next to its neighbours
        self.assertIn('"supervisor_impl";"general";.boot.supervisor_impl', cgi[mine[0]])

    def test_one_authoritative_key(self):
        dist = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertEqual(dist.count('\nSUPERVISOR_IMPL='), 1)
        for p in ('config/daynight.conf.dist',):
            self.assertFalse((ROOT / p).exists() and 'SUPERVISOR_IMPL' in (ROOT / p).read_text())

    def test_built_by_ci_and_packaged(self):
        wf = (ROOT / '.github/workflows/build-kernel-linux66.yml').read_text()
        self.assertIn("- 'src/supervisord/**'", wf)
        self.assertIn('make -C src/supervisord CROSS=arm-linux-gnueabi-', wf)
        self.assertIn('cp src/supervisord/tc100-supervisord $P/', wf)
        bs = (ROOT / 'v3/build-stack.sh').read_text()
        self.assertIn('"$PACK/tc100-supervisord"', bs)
        ci = (ROOT / 'tests/docker/local-ci.sh').read_text()
        self.assertIn('make -C src/supervisord', ci)
        self.assertIn('src/supervisord/tc100-supervisord', ci)
        mk = (ROOT / 'src/supervisord/Makefile').read_text()
        self.assertIn('tc100-supervisord: tc100-supervisord.dbg', mk)

    def test_source_rules(self):
        src = (ROOT / 'src/supervisord/supervisord.c').read_text()
        for bad in ('system(', 'popen(', 'execl(', 'execlp(', 'execvp(', ' stat(', 'fstat(', 'sscanf', 'strtol', 'atoi(', 'math.h'):
            self.assertNotIn(bad, src)
        self.assertEqual(src.count('execv('), 2)                                  # argv vectors only (the second: no #! script)


# ---------------------------------------------------------------- sound detection: shell against C

SD_FILES = {'conf': 'config/sound_detection.conf', 'boot': 'config/boot.conf', 'mqttconf': 'config/mqtt.conf',
            'level': 'run/sound_level', 'up': 'uptime'}


def sd_map(d):
    """the paths of controlscripts/sound-detection, moved under the sandbox d"""
    table = {'/mnt/config/': str(d / 'config') + '/', '/mnt/scripts/': str(d / 'scripts') + '/', '/var/run/': str(d / 'run') + '/',
             '/tmp/': str(d / 'tmp') + '/', '/proc/uptime': str(d / 'uptime')}
    return table


def sd_func(text, name):
    m = re.search(r'^%s\(\)(?: \{)?.*?^\}\n' % name, text, re.M | re.S)
    assert m, name
    return m.group(0)


class SoundScenario:
    """Steps: ('conf', text) ('boot', text) ('mqttconf', text) ('level', text) ('levn', text) ('rmlevel',) ('up', n)
    ('rmstate',) ('iter',)"""

    def __init__(self, d):
        self.d = d
        self.steps = []

    def add(self, *s):
        self.steps.append(s)

    def chunks(self):
        out, cur = [], []
        for s in self.steps:
            if s[0] == 'iter':
                out.append(cur)
                cur = []
            else:
                cur.append(s)
        assert not cur, 'steps after the last iter'
        return out

    def p(self, rel):
        return str(self.d / rel)

    def shell_step(self, s):
        q = shlex.quote
        k = s[0]
        if k in ('conf', 'boot', 'mqttconf', 'level'):
            extra = '; rm -f ' + q(self.p('tmp/sound-detection.loaded')) if k == 'conf' else ''
            return 'printf "%%s\\n" %s > %s%s' % (q(s[1]), q(self.p(SD_FILES[k])), extra)
        if k == 'levn':
            return 'printf "%%s" %s > %s' % (q(s[1]), q(self.p(SD_FILES['level'])))
        if k == 'up':
            return 'echo "%d.55 1.00" > %s' % (s[1], q(self.p('uptime')))
        if k == 'rmlevel':
            return 'rm -f ' + q(self.p('run/sound_level'))
        if k == 'rmstate':
            return 'rm -f ' + q(self.p('tmp/sound-detection.state'))
        raise AssertionError(k)

    def dump_files(self):
        return ['tmp/sound-detection.state', 'run/sound_level.threshold', 'tmp/vox_state', 'tmp/sound_alarm_state']

    def shell(self, controlscript):
        src = Path(controlscript).read_text()
        head = src.split('\nstart()\n')[0]
        cf = (ROOT / 'scripts/common_functions.sh').read_text()
        head = head.replace('. /mnt/scripts/common_functions.sh',
                            sd_func(cf, 'read_kv_config_value') + sd_func(cf, 'publish_mqtt_event'))
        table = sd_map(self.d)
        head = re.sub('|'.join(re.escape(k) for k in table), lambda m: table[m.group(0)], head)
        q = shlex.quote
        code = [head]
        ch = self.chunks()
        for i, steps in enumerate(ch):
            code.append('chunk_%d() {\n:\n%s\n}' % (i, '\n'.join(self.shell_step(s) for s in steps)))
        dump = ['echo "wait=$1"; wait', 'echo @calls; cat %s 2>/dev/null; rm -f %s; echo @end' % (q(self.p('tmp/calls')), q(self.p('tmp/calls')))]
        for f in self.dump_files():
            dump.append('echo "@%s"; cat %s 2>/dev/null' % (f, q(self.p(f))))
        dump.append('echo ---')
        code.append('SD_N=0\nsd_wait() {\n%s\nSD_N=$((SD_N + 1))\nif type chunk_$SD_N >/dev/null 2>&1; then chunk_$SD_N; else exit 0; fi\n}' % '\n'.join(dump))
        code.append('chunk_0\nrun_daemon')
        return '\n'.join(code) + '\n'

    def replay(self):
        out = ['sdreset']
        ch = self.chunks()
        for steps in ch:
            for s in steps:
                k = s[0]
                if k in ('conf', 'boot', 'mqttconf', 'level'):
                    out.append('writeml %s %s' % (self.p(SD_FILES[k]), s[1].replace('\n', '\x01')))
                elif k == 'levn':
                    out.append('writen %s %s' % (self.p(SD_FILES['level']), s[1]))
                elif k == 'up':
                    out.append('write %s %d.55 1.00' % (self.p('uptime'), s[1]))
                elif k == 'rmlevel':
                    out.append('rm ' + self.p('run/sound_level'))
                elif k == 'rmstate':
                    out.append('rm ' + self.p('tmp/sound-detection.state'))
            out += ['sound', 'echo @calls', 'cat ' + self.p('tmp/calls'), 'rm ' + self.p('tmp/calls'), 'echo @end']
            for f in self.dump_files():
                out += ['echo @' + f, 'cat ' + self.p(f)]
            out.append('echo ---')
        return '\n'.join(out) + '\n'


def sd_norm(out):
    """sort the (background) calls of each step"""
    def sort_block(m):
        lines = sorted(x for x in m.group(1).split('\n') if x)
        return '@calls\n' + ''.join(x + '\n' for x in lines) + '@end\n'
    return re.sub(r'@calls\n(.*?)@end\n', sort_block, out, flags=re.S)


@unittest.skipUnless(HAVE_CC, 'needs cc')
class SoundParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.env = dict(os.environ, TZ='UTC', SD_CONF=str(self.d / 'config/sound_detection.conf'),
                        SD_BOOTCONF=str(self.d / 'config/boot.conf'), SD_MQTTCONF=str(self.d / 'config/mqtt.conf'),
                        SD_SCRIPTS=str(self.d / 'scripts'), SD_LOG=str(self.d / 'tmp/log/sound-detection.log'),
                        SD_STATE=str(self.d / 'tmp/sound-detection.state'), SOUND_LEVEL_FILE=str(self.d / 'run/sound_level'),
                        SD_VOX=str(self.d / 'tmp/vox_state'), SD_ALARM=str(self.d / 'tmp/sound_alarm_state'),
                        SD_MOTION=str(self.d / 'tmp/motion_detected'), SD_UPTIME=str(self.d / 'uptime'),
                        BUTTON_L66_FLAG=str(self.d / 'nolinux66'))
        for n in ('config', 'scripts', 'tmp', 'run'):
            (self.d / n).mkdir()
        self.shenv = {k: v for k, v in self.env.items() if k not in ('SD_CONF', 'SD_BOOTCONF', 'SD_MQTTCONF', 'SD_SCRIPTS', 'SD_LOG',
                                                                      'SD_STATE', 'SOUND_LEVEL_FILE', 'SD_VOX', 'SD_ALARM',
                                                                      'SD_MOTION', 'SD_UPTIME')}

    def tearDown(self):
        self.tmp.cleanup()

    def reset(self, x_notify=True):
        for n in ('config', 'scripts', 'tmp', 'run'):
            shutil.rmtree(self.d / n, ignore_errors=True)
            (self.d / n).mkdir()
        (self.d / 'uptime').write_text('100.00 1.00\n')
        for name in ('mqtt-bridge.sh', 'notify.sh'):
            f = self.d / 'scripts' / name
            f.write_text('#!/bin/sh\nfor a in "$@"; do b="$b [$a]"; done\necho "%s$b" >> "%s/tmp/calls"\n' % (name.split('.')[0], self.d))
            f.chmod(0o755 if (x_notify or name != 'notify.sh') else 0o644)

    @staticmethod
    def mask(text):
        return re.sub(r'(?m)^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] ', '[TS] ', text)

    def run_shell(self, sc, env=None, x_notify=True):
        self.reset(x_notify)
        (self.d / 'harness.sh').write_text(sc.shell(str(ROOT / 'controlscripts/sound-detection')))
        r = subprocess.run(SHELL + [str(self.d / 'harness.sh')], capture_output=True, text=True,
                           env=dict(self.shenv, **(env or {})), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.collect_all(r.stdout)

    def run_c(self, sc, env=None, x_notify=True):
        self.reset(x_notify)
        (self.d / 'replay.txt').write_text(sc.replay())
        r = subprocess.run([str(self.bin), '-r', str(self.d / 'replay.txt')], capture_output=True, text=True,
                           env=dict(self.env, **(env or {})), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.collect_all(r.stdout)

    def collect_all(self, out):
        def rd(n):
            p = self.d / n
            return p.read_text() if p.exists() else ''
        # the shell prints "--- " lines the same way; compare the dump, the (masked) log, the rotation and the motion flag
        return (sd_norm(out), self.mask(rd('tmp/log/sound-detection.log')), rd('tmp/log/sound-detection.log.1') != '',
                rd('tmp/log/sound-detection.log.2') != '', (self.d / 'tmp/motion_detected').exists())

    def compare(self, sc, label='', env=None, x_notify=True):
        a, b = self.run_shell(sc, env, x_notify), self.run_c(sc, env, x_notify)
        for i, (x, y) in enumerate(zip(a, b)):
            self.assertEqual(x, y, '%s: part %d differs\nshell:\n%s\nC:\n%s' % (label, i, x, y))
        return a

    CONF = 'ENABLE=1\nTHRESHOLD_DB=-30\nINTERVAL=3\nMIN_LOUD_SECONDS=1'

    def lv(self, ts, events, last_ts=None, db=-20, rms=-40, peak=-25):
        return '%d %d %d %d %d %d' % (ts, rms, peak, events, last_ts if last_ts is not None else ts, db)

    def test_burst_cooldown_and_do_not_replay_past_events(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF)
        sc.add('up', 100)
        sc.add('level', self.lv(1000, 7))
        sc.add('iter')                                           # first reading: past events are not replayed
        sc.add('up', 102)
        sc.add('level', self.lv(1002, 7))
        sc.add('iter')                                           # same events: streak 0
        sc.add('up', 104)
        sc.add('level', self.lv(1004, 8, 1004, -18))
        sc.add('iter')                                           # a loud second: published
        sc.add('up', 106)
        sc.add('level', self.lv(1006, 9, 1006, -17))
        sc.add('iter')                                           # inside the 10 s cooldown: nothing
        sc.add('up', 118)
        sc.add('level', self.lv(1018, 12, 1018, -19))
        sc.add('iter')                                           # delta 3, cooldown over: published again
        out = self.compare(sc, 'burst')
        self.assertEqual(out[0].count('[publish] [event]'), 2)
        self.assertIn('"level_db":-18', out[0])
        self.assertIn('Triggered level=-18dBFS threshold=-30dBFS loud=1s', out[1])
        self.assertIn('notify [sound] [Sound alert: level -18 dBFS (threshold -30 dBFS)] [] [-18]', out[0])

    def test_min_loud_seconds_and_threshold_clamp(self):
        for thr in ('-100', '-91', '-5', '0', '-0', 'abc', '', '-1.5', '7'):
            sc = SoundScenario(self.d)
            sc.add('conf', 'ENABLE=1\nTHRESHOLD_DB=%s\nMIN_LOUD_SECONDS=3\nINTERVAL=0' % thr)
            sc.add('level', self.lv(2000, 1))
            sc.add('iter')
            for i in range(1, 6):
                sc.add('up', 100 + 2 * i)
                sc.add('level', self.lv(2000 + 2 * i, 1 + i, 2000 + 2 * i))
                sc.add('iter')
            out = self.compare(sc, 'thr ' + repr(thr), env={'EVENT_COOLDOWN_SECONDS': '0'})
            self.assertIn('wait=1', out[0])                       # INTERVAL=0 is clamped to 1

    def test_vox_babyphone_and_alarm_tone(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF + '\nVOX_MODE=yes\nVOX_HOLD_SECONDS=4\nALARM_DETECT=on\nALARM_HOLD_SECONDS=7')
        sc.add('level', self.lv(3000, 1))
        sc.add('iter')
        t, ev = 3000, 1
        for i in range(6):
            t += 2
            ev += 1
            sc.add('up', 200 + 2 * i)
            sc.add('level', self.lv(t, ev, t, -15))
            sc.add('iter')
        for i in range(8):                                        # silence: VOX and alarm run out
            sc.add('up', 220 + 2 * i)
            sc.add('level', self.lv(t + 20 + 2 * i, ev, t))
            sc.add('iter')
        out = self.compare(sc, 'vox+alarm', env={'EVENT_COOLDOWN_SECONDS': '0'})
        self.assertIn('[publish] [babyphone/state] [ON] [1]', out[0])
        self.assertIn('[publish] [babyphone/state] [OFF] [1]', out[0])
        self.assertIn('[publish] [alarm/state] [ON] [1]', out[0])
        self.assertIn('[publish] [alarm/state] [OFF] [1]', out[0])
        self.assertIn('Alarm sound pattern detected (loudness: 3s)', out[0])

    def test_disabled_publishes_off_and_waits_five_minutes(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF + '\nVOX_MODE=1\nALARM_DETECT=1')
        sc.add('level', self.lv(4000, 1))
        sc.add('iter')
        sc.add('level', self.lv(4002, 2))
        sc.add('up', 102)
        sc.add('iter')                                            # VOX active
        sc.add('conf', 'ENABLE=0\nTHRESHOLD_DB=-30')
        sc.add('iter')                                            # disabled: OFF states, wait=300
        sc.add('conf', 'ENABLE=true')
        sc.add('iter')                                            # only "1" enables
        out = self.compare(sc, 'disabled', env={'EVENT_COOLDOWN_SECONDS': '0'})
        self.assertEqual(out[0].count('wait=300'), 2)
        self.assertIn('[publish] [babyphone/state] [OFF] [1]', out[0])

    def test_no_reading_stale_meter_and_recovery(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF)
        sc.add('iter')                                            # no level file at all
        sc.add('iter')                                            # warned once only
        sc.add('level', self.lv(5000, 3))
        sc.add('up', 110)
        sc.add('iter')
        sc.add('up', 125)                                         # same timestamp for 15 s: the meter is stale
        sc.add('iter')
        sc.add('level', self.lv(5016, 3))
        sc.add('up', 126)
        sc.add('iter')                                            # fresh again, past events not replayed
        sc.add('level', 'garbage')
        sc.add('iter')
        sc.add('levn', self.lv(5018, 4))                          # no final newline: read still sets the fields
        sc.add('up', 128)
        sc.add('iter')
        sc.add('level', '')
        sc.add('iter')
        out = self.compare(sc, 'stale')
        self.assertEqual(out[1].count('No sound level from the RTSP server'), 4)
        self.assertIn('none', out[0])

    def test_snapshot_event_recording_trigger_and_missing_notify(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF)
        sc.add('boot', '# REC_WHEN=motion\nFOO=1\nREC_WHEN=offline\nREC_WHEN=motion')
        sc.add('mqttconf', 'MQTT_SNAPSHOT_ON_EVENT=1')
        sc.add('level', self.lv(6000, 1))
        sc.add('iter')
        sc.add('level', self.lv(6002, 2))
        sc.add('up', 102)
        sc.add('iter')
        out = self.compare(sc, 'snapshot, first REC_WHEN wins (offline)')
        self.assertIn('mqtt-bridge [snapshot-event] [sound]', out[0])
        self.assertFalse(out[4])
        sc2 = SoundScenario(self.d)
        sc2.add('conf', self.CONF)
        sc2.add('boot', '  # c\nREC_WHEN=motion\n')
        sc2.add('mqttconf', 'MQTT_SNAPSHOT_ON_EVENT=0')
        sc2.add('level', self.lv(6000, 1))
        sc2.add('iter')
        sc2.add('level', self.lv(6002, 2))
        sc2.add('up', 102)
        sc2.add('iter')
        out = self.compare(sc2, 'motion trigger, no snapshot, notify.sh not executable', x_notify=False)
        self.assertTrue(out[4])
        self.assertNotIn('snapshot-event', out[0])
        self.assertNotIn('notify', out[0])

    def test_rec_when_motion_in_the_real_boot_conf(self):
        # audit 2026-11-24 B2: boot.conf was read into 16 KB and REC_WHEN sits past 16 KB in the real file, so a sound
        # event never started a recording with REC_WHEN=motion (the 2-line boot.conf of the test above hid it)
        dist = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertGreater(dist.index('\nREC_WHEN='), 16384)      # keeps this test meaningful
        boot = re.sub(r'(?m)^REC_WHEN=.*$', 'REC_WHEN=motion', dist)
        self.assertNotEqual(boot, dist)
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF)
        sc.add('boot', boot.rstrip('\n'))
        sc.add('mqttconf', 'MQTT_SNAPSHOT_ON_EVENT=0')
        sc.add('level', self.lv(6000, 1))
        sc.add('iter')
        sc.add('level', self.lv(6002, 2))
        sc.add('up', 102)
        sc.add('iter')
        out = self.compare(sc, 'real boot.conf.dist, REC_WHEN=motion', x_notify=False)
        self.assertTrue(out[4])

    def test_settings_buffers_hold_twice_the_largest_dist_file(self):
        src = (ROOT / 'src/supervisord/supervisord.c').read_text()
        cap = int(re.search(r'#define CONF_BUF (\d+)', src).group(1))
        largest = max(p.stat().st_size for p in (ROOT / 'config').glob('*.dist'))
        self.assertGreaterEqual(cap, 2 * largest)
        self.assertIn('static char b[CONF_BUF];', src[src.index('static int sd_rec_motion'):])
        self.assertIn('static char b[CONF_BUF];', src[src.index('static int sd_prefix_line'):])

    def test_log_rotation(self):
        sc = SoundScenario(self.d)
        sc.add('conf', self.CONF)
        sc.add('level', self.lv(7000, 1))
        sc.add('iter')
        for i in range(1, 16):
            sc.add('up', 100 + 2 * i)
            sc.add('level', self.lv(7000 + 2 * i, 1 + i, 7000 + 2 * i, -10 - i))
            sc.add('iter')
        out = self.compare(sc, 'rotation', env={'EVENT_COOLDOWN_SECONDS': '0', 'LOG_MAX_BYTES': '250', 'LOG_BACKUPS': '2'})
        self.assertTrue(out[2] and out[3])
        out = self.compare(sc, 'no backup', env={'EVENT_COOLDOWN_SECONDS': '0', 'LOG_MAX_BYTES': '250', 'LOG_BACKUPS': '0'})
        self.assertFalse(out[2])

    def test_random_series(self):
        rnd = random.Random(20261105)
        for case in range(12):
            sc = SoundScenario(self.d)
            conf = ['ENABLE=1', 'THRESHOLD_DB=%s' % rnd.choice(['-24', '-40', '-3', '-95', 'x']),
                    'INTERVAL=%s' % rnd.choice(['1', '2', '30', '999', '']), 'MIN_LOUD_SECONDS=%s' % rnd.choice(['1', '2', '4', '20']),
                    'VOX_MODE=%s' % rnd.choice(['0', '1', 'on']), 'VOX_HOLD_SECONDS=%s' % rnd.choice(['1', '3', '90']),
                    'ALARM_DETECT=%s' % rnd.choice(['0', '1']), 'ALARM_HOLD_SECONDS=%s' % rnd.choice(['1', '6', '500'])]
            sc.add('conf', '\n'.join(conf))
            t, ev, up = 8000, 1, 300
            for step in range(40):
                up += rnd.choice([0, 1, 2, 3, 11, 12])
                sc.add('up', up)
                r = rnd.random()
                if r < 0.08:
                    sc.add('rmlevel')
                elif r < 0.12:
                    sc.add('conf', '\n'.join(conf).replace('ENABLE=1', 'ENABLE=%s' % rnd.choice(['0', '1'])))
                else:
                    if rnd.random() < 0.7:
                        t += rnd.choice([1, 2, 2, 5])
                    if rnd.random() < 0.6:
                        ev += rnd.choice([1, 1, 2, 3])
                    sc.add('level', self.lv(t, ev, t - rnd.choice([0, 0, 1]), -rnd.choice([10, 20, 35])))
                sc.add('iter')
            self.compare(sc, 'random %d' % case, env={'EVENT_COOLDOWN_SECONDS': rnd.choice(['0', '5', '10'])})


# ---------------------------------------------------------------- sound detection as a job of the real daemon

def sd_rig(d):
    """fake scripts + paths for the sound job of the real daemon; returns the environment"""
    for n in ('config', 'scripts', 'tmp', 'run'):
        (d / n).mkdir(exist_ok=True)
    for name in ('mqtt-bridge.sh', 'notify.sh'):
        f = d / 'scripts' / name
        f.write_text('#!/bin/sh\n%secho "%s $*" >> "%s/tmp/calls"\n' % (
            'exec sleep 100\n' if (name == 'mqtt-bridge.sh' and (d / 'hang').exists()) else '', name.split('.')[0], d))
        f.chmod(0o755)
    (d / 'config/sound_detection.conf').write_text('ENABLE=1\nTHRESHOLD_DB=-30\nINTERVAL=1\nMIN_LOUD_SECONDS=1\n')
    (d / 'uptime').write_text('100.00 1.00\n')
    return dict(os.environ, TZ='UTC', SD_CONF=str(d / 'config/sound_detection.conf'), SD_BOOTCONF=str(d / 'config/boot.conf'),
                SD_MQTTCONF=str(d / 'config/mqtt.conf'), SD_SCRIPTS=str(d / 'scripts'), SD_LOG=str(d / 'tmp/log/sd.log'),
                SD_STATE=str(d / 'tmp/sd.state'), SOUND_LEVEL_FILE=str(d / 'run/sound_level'), SD_VOX=str(d / 'tmp/vox'),
                SD_ALARM=str(d / 'tmp/alarm'), SD_MOTION=str(d / 'tmp/motion'), SD_UPTIME=str(d / 'uptime'),
                EVENT_COOLDOWN_SECONDS='0', SV_TICK_DIV='20', SV_NIGHT_FLAG=str(d / 'night.flag'),
                SV_BUTTON_FLAG=str(d / 'button.flag'), SV_SOUND_FLAG=str(d / 'sound.flag'), SV_PIDFILE=str(d / 'sv.pid'))


@unittest.skipUnless(HAVE_CC, 'needs cc')
class SoundDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.tmp.cleanup()

    def start(self, env):
        self.proc = subprocess.Popen([str(self.bin)], env=env, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def wait_for(self, fn, timeout=30):     # returns as soon as fn() holds; 30 s only matters on a loaded CI runner
        end = time.time() + timeout
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.05)
        return False

    def calls(self):
        p = self.d / 'tmp/calls'
        return p.read_text().splitlines() if p.exists() else []

    def feed(self, n, db=-20):
        # written then renamed, as tc100_rtsp does: the daemon never reads a half-written line
        tmp = self.d / 'run/sound_level.tmp'
        tmp.write_text('%d -40 -25 %d %d %d\n' % (1000 + n, n, 1000 + n, db))
        os.replace(tmp, self.d / 'run/sound_level')

    def test_sound_job_alone_publishes_and_stops_with_its_flag(self):
        env = sd_rig(self.d)
        (self.d / 'sound.flag').write_text('')
        self.feed(1)
        self.start(env)
        self.assertTrue(self.wait_for(lambda: (self.d / 'tmp/sd.state').exists()))
        self.assertEqual((self.d / 'run/sound_level.threshold').read_text(), '-30\n')
        self.assertEqual(int((self.d / 'sv.pid').read_text()), self.proc.pid)
        self.assertEqual(self.calls(), [])                                                   # past events are not replayed
        self.feed(2, -17)
        self.assertTrue(self.wait_for(lambda: any(c.startswith('mqtt-bridge publish event {"type":"sound"') for c in self.calls())))
        self.assertTrue(any('"level_db":-17' in c for c in self.calls()))
        self.assertTrue(self.wait_for(lambda: any(c.startswith('notify sound Sound alert') for c in self.calls())))
        self.assertIn('Triggered level=-17dBFS', (self.d / 'tmp/log/sd.log').read_text())
        (self.d / 'sound.flag').unlink()
        self.assertEqual(self.proc.wait(timeout=5), 0)
        self.assertFalse((self.d / 'sv.pid').exists())

    def test_three_jobs_one_process_and_a_hung_publish_does_not_stop_the_others(self):
        env = sd_rig(self.d)
        (self.d / 'hang').write_text('')
        sd_rig(self.d)                                                                       # rewrite the fake scripts: hanging publish
        fake = fake_nightmode(self.d)
        (self.d / 'ircut').write_text('1\n')
        (self.d / 'luma').write_text('10\n')
        (self.d / 'daynight.conf').write_text('MIN_SWITCH=0\nIR_LED_MAX_ON=0\nDAYNIGHT_SOURCE=luma\n')
        env.update(SD_TIMEOUT='1', DN_CONSOLE=str(self.d / 'console'), CAM_LUMA=str(self.d / 'luma'), DN_IRCUT=str(self.d / 'ircut'),
                   DN_NIGHTMODE=str(fake), DN_CONF=str(self.d / 'daynight.conf'), DN_RTSPCONF=str(self.d / 'rt.conf'),
                   DN_LOG=str(self.d / 'dn.log'), CAM_AE=str(self.d / 'ae'))
        (self.d / 'sound.flag').write_text('')
        (self.d / 'night.flag').write_text('')
        self.feed(1)
        self.start(env)
        self.assertTrue(self.wait_for(lambda: (self.d / 'calls').exists()))                  # night job: dark picture
        self.assertEqual((self.d / 'calls').read_text().split(), ['on'])
        self.feed(2)                                                                         # the publish hangs, is killed after 1 s
        self.assertTrue(self.wait_for(lambda: any(c.startswith('notify sound') for c in self.calls()), 30))
        (self.d / 'luma').write_text('200\n')
        self.assertTrue(self.wait_for(lambda: (self.d / 'calls').read_text().split() == ['on', 'off'], 30))
        (self.d / 'night.flag').unlink()
        time.sleep(0.5)
        self.assertIsNone(self.proc.poll())                                                  # the sound job still needs the daemon
        (self.d / 'sound.flag').unlink()
        self.assertEqual(self.proc.wait(timeout=5), 0)

    def test_disabled_job_idles_and_vox_off_is_published(self):
        env = sd_rig(self.d)
        (self.d / 'config/sound_detection.conf').write_text('ENABLE=0\n')
        (self.d / 'sound.flag').write_text('')
        self.start(env)
        time.sleep(0.5)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.d / 'run/sound_level.threshold').exists())                    # nothing is told to the meter
        self.assertIsNone(self.proc.poll())
        self.proc.terminate()
        self.assertEqual(self.proc.wait(timeout=5), 0)


@unittest.skipUnless(HAVE_CC, 'needs cc')
class SoundSwitch(unittest.TestCase):
    """scripts/supervisor.sh and controlscripts/sound-detection with the sound job"""
    @classmethod
    def setUpClass(cls):
        cls.bin = build()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'run').mkdir()
        self.env = sd_rig(self.d)
        self.env.update(SV_BIN=str(self.bin), SV_RUN=str(self.d / 'run'), SV_BOOTCONF=str(self.d / 'boot.conf'),
                        SV_HK=str(self.d / 'no-housekeeper'), SV_NIGHT_FLAG=str(self.d / 'run/tc100-sv.night'),
                        SV_BUTTON_FLAG=str(self.d / 'run/tc100-sv.button'), SV_SOUND_FLAG=str(self.d / 'run/tc100-sv.sound'),
                        SV_PIDFILE=str(self.d / 'run/tc100-supervisord.pid'), SOUND_LEVEL_FILE=str(self.d / 'run/sound_level'))
        (self.d / 'boot.conf').write_text('SUPERVISOR_IMPL=c\n')
        (self.d / 'run/sound_level').write_text('1001 -40 -25 1 1001 -20\n')

    def tearDown(self):
        pid = self.d / 'run' / 'tc100-supervisord.pid'
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.tmp.cleanup()

    def sh(self, code):
        return subprocess.run(['sh', '-c', '. %s\n%s' % (shlex.quote(str(ROOT / 'scripts/supervisor.sh')), code)],
                              capture_output=True, text=True, env=self.env, timeout=30)

    def daemon_pid(self):
        return int((self.d / 'run' / 'tc100-supervisord.pid').read_text())

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return Path('/proc/%d/stat' % pid).read_text().split(') ')[1][0] != 'Z'
        except (OSError, IndexError):
            return False

    def test_sound_and_night_share_one_daemon_and_stop_order(self):
        s, n = self.d / 's.pid', self.d / 'n.pid'
        self.assertEqual(self.sh('sv_start sound %s sound-detection' % s).returncode, 0)
        pid = self.daemon_pid()
        self.assertEqual(int(s.read_text()), pid)
        self.assertEqual(self.sh('sv_start night %s x' % n).returncode, 0)
        self.assertEqual(self.daemon_pid(), pid)
        self.sh('sv_stop sound %s sound-detection' % s)
        self.assertTrue(self.alive(pid))                                                     # the night job still needs it
        self.assertFalse(s.exists())
        self.sh('sv_stop night %s x' % n)
        end = time.time() + 5
        while self.alive(pid) and time.time() < end:
            time.sleep(0.1)
        self.assertFalse(self.alive(pid))

    def test_dead_daemon_with_a_sound_flag_brings_every_shell_loop_back(self):
        s = self.d / 's.pid'
        self.assertEqual(self.sh('sv_start sound %s sound-detection' % s).returncode, 0)
        os.kill(self.daemon_pid(), signal.SIGKILL)
        time.sleep(0.3)
        self.assertEqual(self.sh('sv_start sound %s sound-detection' % s).returncode, 1)     # run_daemon is started by the caller
        self.assertTrue((self.d / 'run/tc100-supervisord.failed').exists())
        self.assertEqual(self.sh('sv_start night %s x' % (self.d / 'n.pid')).returncode, 1)  # for the rest of this boot
        self.assertFalse((self.d / 'run/tc100-sv.sound').exists())

    def control_script(self, src_text):
        r = {'/var/run/sound-detection.pid': str(self.d / 'run/sound-detection.pid'),
             '/mnt/scripts/common_functions.sh': str(ROOT / 'scripts/common_functions.sh'),
             '/mnt/scripts/supervisor.sh': str(ROOT / 'scripts/supervisor.sh'),
             '/mnt/config/sound_detection.conf': str(self.d / 'config/sound_detection.conf'),
             '/tmp/sound-detection.state': str(self.d / 'tmp/sd.state'), '/tmp/log/sound-detection.log': str(self.d / 'tmp/log/sd.log'),
             '/tmp/sound-detection.fifo': str(self.d / 'tmp/sd.fifo'), '/tmp/sound-detection.loaded': str(self.d / 'tmp/sd.loaded'),
             '/var/run/sound_level': str(self.d / 'run/sound_level')}
        for k, v in r.items():
            src_text = src_text.replace(k, v)
        cs = self.d / 'sd-control'
        cs.write_text(src_text)
        return lambda a: subprocess.run(['sh', str(cs), a], capture_output=True, text=True, env=self.env, timeout=30)

    def test_control_script_start_status_stop_with_the_c_daemon(self):
        run = self.control_script((ROOT / 'controlscripts/sound-detection').read_text())
        self.assertIn('Starting', run('start').stdout)
        pid = self.daemon_pid()
        self.assertEqual(int((self.d / 'run/sound-detection.pid').read_text()), pid)
        self.assertTrue(self.alive(pid))
        self.assertTrue((self.d / 'run/tc100-sv.sound').exists())
        self.assertIn('Already running', run('start').stdout)
        self.assertIn('Running (PID: %d)' % pid, run('status').stdout)
        self.assertEqual(run('health').stdout.strip(), 'ok: running')
        self.assertEqual(run('stop').stdout.strip(), 'Stopped')
        end = time.time() + 5
        while self.alive(pid) and time.time() < end:
            time.sleep(0.1)
        self.assertFalse(self.alive(pid))
        self.assertFalse((self.d / 'run/sound-detection.pid').exists())

    def test_control_script_keeps_the_shell_loop_without_the_binary(self):
        self.env['SV_BIN'] = str(self.d / 'missing')
        run = self.control_script((ROOT / 'controlscripts/sound-detection').read_text())
        subprocess.run(['sh', str(self.d / 'sd-control'), 'start'], env=self.env, timeout=30, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)      # as the boot script starts it
        pid = int((self.d / 'run/sound-detection.pid').read_text())
        try:
            self.assertTrue(self.alive(pid))                                                 # the shell run_daemon
            self.assertFalse((self.d / 'run/tc100-sv.sound').exists())
            self.assertIn('Running (PID: %d)' % pid, run('status').stdout)
            run('stop')
            end = time.time() + 8
            while self.alive(pid) and time.time() < end:
                time.sleep(0.1)
            self.assertFalse(self.alive(pid))
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def test_wiring(self):
        cs = (ROOT / 'controlscripts/sound-detection').read_text()
        self.assertIn('sv_start sound "$PID_FILE" sound-detection', cs)
        self.assertIn('run_daemon >/dev/null 2>&1 &', cs)                                    # the fallback is still there
        self.assertIn('sv_stop sound "$PID_FILE" sound-detection', cs)
        for p in ('controlscripts/sound-detection', 'scripts/supervisor.sh'):
            self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / p)]).returncode, 0, p)
        self.assertIn('sound-detection)      _hk_wpf=', (ROOT / 'scripts/housekeeper.sh').read_text())
        self.assertIn('sound-detection)      _wd_pf=', (ROOT / 'scripts/service-watchdog.sh').read_text())
        self.assertEqual((ROOT / 'config/boot.conf.dist').read_text().count('\nSUPERVISOR_IMPL='), 1)
        self.assertNotIn('SOUND_IMPL', (ROOT / 'config/boot.conf.dist').read_text())          # one switch for all the jobs


if __name__ == '__main__':
    unittest.main()


class ConfReadsStartFromDefaults(unittest.TestCase):
    """2026-11-15: a key removed from daynight.conf kept its last value until a restart (the .24 kept the test's
    IR_LED_MAX_ON=120 after the file was restored: day every 2 minutes all night). Both versions reset first."""

    def test_c_resets_before_parsing(self):
        src = (ROOT / 'src/supervisord/supervisord.c').read_text()
        fn = src[src.index('static void conf_daynight(void)'):]
        fn = fn[:fn.index('\n}\n')]
        reset = fn.index('IR_LED_MAX_ON = 50400; IR_LED_REST = 600;')
        self.assertLess(fn.index('n = slurp(envs("DN_CONF"'), reset)
        self.assertLess(reset, fn.index("/* IFS='=' */"))
        for kv in ('THRESHOLD_NIGHT = 40', 'AWB_DAY_CNT = 200000', 'VENDOR_LOCK = 900', 'DAYNIGHT_SOURCE = SRC_LUMA', 'IR_LED_MODE = 0'):
            self.assertIn(kv, fn[reset - 400:reset + 400])

    def test_shell_value_comes_back_when_the_key_goes(self):
        src = (ROOT / 'scripts/auto-night-daemon.sh').read_text()
        fn = src[src.index('read_daynight() {'):]
        fn = fn[:fn.index('\n}\n') + 3]
        with tempfile.TemporaryDirectory() as t:
            c = Path(t, 'daynight.conf'); r = Path(t, 'rtspserver.conf'); r.write_text('daynight=2\n')
            code = ('DN_CONF=%s; DN_RTSPCONF=%s\n' % (c, r) + fn +
                    '\nprintf "IR_LED_MAX_ON=120\\nAWB_DAY_CNT=5\\n" > %s; read_daynight; echo "$IR_LED_MAX_ON $AWB_DAY_CNT"\n' % c +
                    ': > %s; read_daynight; echo "$IR_LED_MAX_ON $AWB_DAY_CNT"\n' % c)
            out = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, check=True).stdout.split('\n')
            self.assertEqual(out[0], '120 5')
            self.assertEqual(out[1], '50400 200000')
