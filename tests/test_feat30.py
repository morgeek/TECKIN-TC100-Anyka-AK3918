"""Host tests of the 3.0 features: day/night from the ISP exposure, frame rate setting, idle frame rate (its decision
function is tested in src/tc100rtsp/test_util.c, run by test_tc100rtsp.py), logs kept across reboots, Memory Guard
defaults and their migration. Camera-side scripts run in busybox ash when it is installed (the CI image has it).
Run: python3 -m unittest tests/test_feat30.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']


def sh(code, env=None, timeout=20):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(SH + ['-c', code], capture_output=True, text=True, timeout=timeout, env=e)


def state_text(path):
    """A CGI's text; state.cgi's helpers shared with statusline.cgi live in statelib.cgi."""
    t = (ROOT / path).read_text()
    if path.endswith('cgi-bin/state.cgi'):
        t += '\n' + (ROOT / 'www/cgi-bin/statelib.cgi').read_text()
    return t


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', state_text(path), re.M | re.S)
    if not m:
        raise AssertionError((path, name))
    return m.group(0)


class DayNightFromExposure(unittest.TestCase):
    """scripts/auto-night-daemon.sh: the ae and isp sources, with hysteresis and hold times."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'ircut').write_text('1\n')
        nm = self.d / 'nightmode.sh'
        nm.write_text('#!/bin/sh\ncase "$1" in on) echo 0 > %s/ircut ;; off) echo 1 > %s/ircut ;; esac\n'
                      'echo "$1" >> %s/calls\n' % (self.d, self.d, self.d))
        nm.chmod(0o755)
        self.env = dict(DN_TEST='1', DN_CONSOLE='/dev/null', CAM_AE=str(self.d / 'ae'), CAM_LUMA=str(self.d / 'luma'),
                        DN_IRCUT=str(self.d / 'ircut'), DN_NIGHTMODE=str(nm),
                        DN_CONF=str(self.d / 'daynight.conf'), DN_RTSPCONF=str(self.d / 'rtspserver.conf'))
        self.daemon = str(ROOT / 'scripts/auto-night-daemon.sh')

    def tearDown(self):
        self.tmp.cleanup()

    def feed(self, source, samples, pre=''):
        """samples: (time, 'lumi exp a d isp dark'); returns the (time, action) list"""
        code = '. %s\nDAYNIGHT_SOURCE=%s\n%s\n' % (self.daemon, source, pre)
        code += 'NIGHTMODE() { :; }\n'
        for t, line in samples:
            code += 'echo "%s" > "$CAM_AE"\n' % line
            code += 'before=$(cat "$DN_IRCUT"); dn_step_ae %d; echo "%d $before $(cat "$DN_IRCUT")"\n' % (t, t)
        r = sh(code, self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = []
        for ln in r.stdout.split('\n'):
            p = ln.split()
            if len(p) == 3:
                out.append((int(p[0]), p[1], p[2]))
        return out

    def test_index_formula(self):
        r = sh('. %s\ndn_index 50 1000 256 256 256 0 && echo $DN_IDX\ndn_index 50 1000 512 256 256 0 && echo $DN_IDX\n'
               'dn_index 50 1000 512 512 512 0 && echo $DN_IDX\ndn_index 50 abc 1 1 1 0 || echo bad\n' % self.daemon, self.env)
        self.assertEqual(r.stdout.split(), ['1000', '2000', '8000', 'bad'])

    def test_night_after_hold_then_day_needs_a_clearly_lower_index_for_the_day_hold(self):
        pre = 'AE_NIGHT_ABOVE=4000; AE_DAY_BELOW=1000; NIGHT_HOLD=10; DAY_HOLD=60'
        dark = '50 5000 256 256 256 0'
        s = [(100 + 2 * i, dark) for i in range(5)]            # 100..108: not yet
        s += [(110, dark)]                                       # 10 s of dark: night
        self.assertEqual([c for c in self.feed('ae', s, pre) if c[1] != c[2]], [(110, '1', '0')])
        (self.d / 'ircut').write_text('1\n')
        # night, the IR LEDs light the scene (index 800), then a brightening spike resets the day hold
        lit = '50 800 256 256 256 0'
        mid = '50 2000 256 256 256 0'     # between the thresholds: neither dark nor bright
        s = [(100, '50 9000 256 256 256 0'), (110, '50 9000 256 256 256 0')]   # -> night at 110
        s += [(120 + 2 * i, lit) for i in range(10)]             # 120..138 bright
        s += [(140, mid)]                                        # resets the timer
        s += [(142 + 2 * i, lit) for i in range(28)]             # 142..196
        s += [(198, lit), (200, lit), (202, lit)]                # 142 + 60 = 202: day
        sw = [c for c in self.feed('ae', s, pre) if c[1] != c[2]]
        self.assertEqual(sw, [(110, '1', '0'), (202, '0', '1')])

    def test_a_dip_below_the_night_threshold_cancels_the_night(self):
        pre = 'AE_NIGHT_ABOVE=4000; AE_DAY_BELOW=1000; NIGHT_HOLD=10; DAY_HOLD=60'
        s = [(100, '50 5000 256 256 256 0'), (104, '50 5000 256 256 256 0'), (106, '50 3000 256 256 256 0'),
             (108, '50 5000 256 256 256 0'), (116, '50 5000 256 256 256 0'), (118, '50 5000 256 256 256 0')]
        self.assertEqual([c for c in self.feed('ae', s, pre) if c[1] != c[2]], [(118, '1', '0')])

    def test_gains_count(self):
        pre = 'AE_NIGHT_ABOVE=4000; AE_DAY_BELOW=1000; NIGHT_HOLD=2; DAY_HOLD=2'
        s = [(10, '50 1000 256 256 256 0'), (13, '50 1000 256 256 256 0')]          # exposure alone: bright
        self.assertEqual([c for c in self.feed('ae', s, pre) if c[1] != c[2]], [])
        s = [(10, '50 1000 1024 1024 256 0'), (13, '50 1000 1024 1024 256 0')]     # x16 total gain: 16000, dark
        self.assertEqual([c for c in self.feed('ae', s, pre) if c[1] != c[2]], [(13, '1', '0')])

    def test_isp_dark_flag_with_holds(self):
        pre = 'NIGHT_HOLD=10; DAY_HOLD=60'
        s = [(100, '50 1 256 256 256 1'), (105, '50 1 256 256 256 1'), (110, '50 1 256 256 256 1'),
             (120, '50 1 256 256 256 0'), (179, '50 1 256 256 256 0'), (180, '50 1 256 256 256 0')]
        sw = [c for c in self.feed('isp', s, pre) if c[1] != c[2]]
        self.assertEqual(sw, [(110, '1', '0'), (180, '0', '1')])

    def test_flapping_flag_never_switches(self):
        pre = 'NIGHT_HOLD=10; DAY_HOLD=60'
        s = [(100 + 4 * i, '50 1 256 256 256 %d' % (i % 2)) for i in range(40)]
        self.assertEqual([c for c in self.feed('isp', s, pre) if c[1] != c[2]], [])

    def test_default_thresholds_separate_the_measured_night(self):
        """rc7 night 2 on IPCAM2: exposure 1124 lines, analogue gain 6840, IR LEDs on or off (R9-02)"""
        s = [(100, '9 1124 6840 256 256 0'), (112, '9 1124 6840 256 256 0')]
        self.assertEqual([c for c in self.feed('ae', s) if c[1] != c[2]], [(112, '1', '0')])

    def test_calibration_log_every_interval_with_the_index(self):
        (self.d / 'ae').write_text('9 1124 6840 256 256 0\n')
        (self.d / 'luma').write_text('47\n')
        (self.d / 'ircut').write_text('0\n')
        log = self.d / 'dn.log'
        r = sh('. %s\nDN_LOG_EVERY=300\nDN_NOW=1000; dn_log\nDN_NOW=1100; dn_log\nDN_NOW=1300; dn_log\n'
               'rm -f "$CAM_AE"; DN_NOW=1700; dn_log\n' % self.daemon, dict(self.env, DN_LOG=str(log)))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 3, lines)                 # 1100 is within 300 s of 1000
        self.assertTrue(lines[0].endswith('mode=night src=luma luma=47 ae=9 1124 6840 256 256 0 idx=30031'), lines[0])
        self.assertTrue(lines[2].endswith('ae=- idx=-'), lines[2])

    def test_unusable_exposure_file_falls_back(self):
        r = sh('. %s\nrm -f "$CAM_AE"; dn_step_ae 5; echo rc=$?\necho "1 2 3" > "$CAM_AE"; dn_step_ae 5; echo rc=$?\n'
               'echo "a b c d e f" > "$CAM_AE"; dn_step_ae 5; echo rc=$?\n' % self.daemon, self.env)
        self.assertEqual(r.stdout.split(), ['rc=1', 'rc=1', 'rc=1'])

    def test_config_is_read_and_validated(self):
        (self.d / 'daynight.conf').write_text('LUMA_NIGHT=30\nLUMA_DAY=90\nDAYNIGHT_SOURCE=ae\nAE_NIGHT_ABOVE=7000\n'
                                              'AE_DAY_BELOW=9000\nNIGHT_HOLD=0\nDAY_HOLD=abc\n')
        (self.d / 'rtspserver.conf').write_text('daynight=2\n[0]\nfps=15\n')
        r = sh('. %s\nread_daynight\necho "$THRESHOLD_NIGHT $THRESHOLD_DAY $DAYNIGHT_SOURCE $AE_NIGHT_ABOVE $AE_DAY_BELOW '
               '$NIGHT_HOLD $DAY_HOLD $DN_MODE"\n' % self.daemon, self.env)
        # day below night is not allowed: it becomes half of it; bad hold times keep their defaults
        self.assertEqual(r.stdout.split(), ['30', '90', 'ae', '7000', '3500', '10', '60', '2'])
        (self.d / 'daynight.conf').write_text('DAYNIGHT_SOURCE=weird\n')
        r = sh('. %s\nread_daynight\necho "$DAYNIGHT_SOURCE"\n' % self.daemon, self.env)
        self.assertEqual(r.stdout.strip(), 'luma')

    def test_luma_source_unchanged(self):
        (self.d / 'luma').write_text('20\n')
        code = '. %s\nTHRESHOLD_NIGHT=40; THRESHOLD_DAY=100\ndn_step_luma; cat "$DN_IRCUT"\ndn_step_luma; cat "$DN_IRCUT"\n' % self.daemon
        r = sh(code, self.env)
        self.assertEqual(r.stdout.split(), ['1', '0'])          # two samples in a row
        (self.d / 'luma').write_text('150\n')
        code = '. %s\nTHRESHOLD_NIGHT=40; THRESHOLD_DAY=100\ndn_step_luma; cat "$DN_IRCUT"\ndn_step_luma; cat "$DN_IRCUT"\n' % self.daemon
        r = sh(code, self.env)
        self.assertEqual(r.stdout.split(), ['0', '1'])

    def test_state_cgi_reading(self):
        src = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        a = src.index('  daynight)')
        b = src.index('  lumawb)', a)
        (self.d / 'ae').write_text('60 1000 512 256 256 1\n')
        (self.d / 'luma').write_text('77\n')
        (self.d / 'daynight.conf').write_text('DAYNIGHT_SOURCE=isp\nAE_NIGHT_ABOVE=5000\n')
        (self.d / 'rtspserver.conf').write_text('daynight=2\n')
        body = src[a:b].replace('/mnt/config/daynight.conf', str(self.d / 'daynight.conf')) \
                       .replace('/mnt/config/rtspserver.conf', str(self.d / 'rtspserver.conf')) \
                       .replace('/tmp/cam_ae', str(self.d / 'ae')).replace('/tmp/cam_luma', str(self.d / 'luma')) \
                       .replace('/var/run/ircut', str(self.d / 'ircut'))
        helpers = '\n'.join(function('www/cgi-bin/state.cgi', n) for n in ('load_conf_file', 'get_cfg', 'sanitize_int', 'cfg_int'))
        r = sh(helpers + '\ncase daynight in\n' + body + '\nesac')
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual((j['source'], j['index'], j['dark_flag'], j['luma'], j['ae_available'], j['ae_night_above'],
                          j['ae_day_below'], j['night'], j['auto']), ('isp', 2000, 1, 77, 1, 5000, 3000, 0, 1))


class FrameRateSetting(unittest.TestCase):
    def fps_opt(self, value):
        text = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text()
        line = next(l for l in text.split('\n') if l.startswith('fps_opt()'))
        r = sh(line + '\nfps_opt "$1"\n'.replace('"$1"', "'%s'" % value))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_launcher_passes_only_valid_rates(self):
        for v in ('10', '12', '15', '20', '25'):
            self.assertEqual(self.fps_opt(v), '-f ' + v)
        for v in ('', '16', '5', '0', '30', '15x', '-1', '1e1', '010', '25 ', 'abc'):
            self.assertEqual(self.fps_opt(v), '', v)

    def test_launcher_uses_it_and_default_stays_15(self):
        text = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text()
        self.assertIn('ENCOPT="$ENCOPT $(fps_opt "$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 fps', text)
        c = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text()
        self.assertIn('fps = 15,', c)
        dist = (ROOT / 'config/rtspserver.conf.dist').read_text()
        self.assertRegex(dist, r'(?s)\[0\].*?\nfps=15\n.*?\[1\]')

    def test_state_reports_a_valid_rate_for_both_streams(self):
        helpers = '\n'.join(function('www/cgi-bin/state.cgi', n) for n in ('get_cfg', 'sanitize_int', 'cfg_int', 'read_rtsp_stream_summary', 'codec_name', 'codec_name_to'))
        for conf, want in ((20, '20 20'), (16, '15 15'), (25, '25 25'), (7, '15 15')):
            r = sh(helpers + '\nC_0_fps=%d; C_1_fps=8\nread_rtsp_stream_summary\necho "$fps0 $fps1"\n' % conf)
            self.assertEqual(r.stdout.strip().split('\n')[-1], want, (conf, r.stderr))

    def test_video_settings_write_one_rate(self):
        t = (ROOT / 'scripts/action.d/video.sh').read_text()
        a = t.index('    set_video_params)')
        b = t.index('    isp_pro)')
        arm = t[a:b]
        self.assertIn('case "${F_fps0}" in 10|12|15|20|25)', arm)
        self.assertIn('0 fps "$fps" \\', arm)
        self.assertIn('1 fps "$fps" \\', arm)
        # the part that picks the rate
        sel = arm[arm.index('_fps_old='):arm.index('if [ "$stream_idx"')]
        for form, old, want in (('25', '15', '25'), ('', '20', '20'), ('13', '12', '12'), ('', '', '15'), ('', '16', '15'), ('20', '', '20')):
            r = sh('rwconf_out="%s"\n_fps_old="$rwconf_out"\nF_fps0="%s"\n%s\necho $fps\n' % (old, form,
                   '\n'.join(l for l in sel.split('\n') if not l.strip().startswith('_fps_old='))))
            self.assertEqual(r.stdout.strip(), want, (form, old, r.stderr))


class IdleFrameRateWiring(unittest.TestCase):
    def test_switch_and_setting_are_wired(self):
        c = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text()
        self.assertIn('"IDLE_FPS"', c)
        self.assertIn('"IDLE_AFTER"', c)
        self.assertIn('idle_fps_now(', c)
        boot = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('\nIDLE_FPS=0\n', boot)          # off by default
        self.assertIn('IDLE_AFTER=10', boot)
        arm = (ROOT / 'scripts/action.d/stream.sh').read_text()
        self.assertIn('rewrite_config /mnt/config/boot.conf IDLE_FPS', arm)
        self.assertIn('0 24 0', arm)


class LogPersist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        (d / 'sd').mkdir()
        (d / 'rtsp').mkdir()
        (d / 'ram').mkdir()
        (d / 'mounts').write_text('tmpfs / tmpfs rw 0 0\n/dev/mmcblk0p1 %s vfat rw 0 0\n' % (d / 'sd'))
        (d / 'dmesg').write_text('kernel line\n' * 50)
        (d / 'messages').write_text('syslog line\n' * 30)
        (d / 'rtsp.log').write_text('rtsp line\n' * 40)
        (d / 'ram' / 'memory-guard.log').write_text('guard line\n')
        (d / 'boot.conf').write_text('LOG_PERSIST=1\n')
        self.env = dict(LP_SD=str(d / 'sd'), LP_MOUNTS=str(d / 'mounts'), LP_PAUSE=str(d / 'pause'), LP_HEALTH=str(d / 'health'),
                        LP_BOOTCONF=str(d / 'boot.conf'), LP_STATE=str(d / 'state'), LP_LOCK=str(d / 'lock'),
                        LP_MIN_FREE_KB='0', LP_DMESG_FILE=str(d / 'dmesg'), LP_SYSLOG=str(d / 'messages'),
                        LP_RTSPLOG=str(d / 'rtsp.log'), LP_OTHER_DIRS=str(d / 'ram'))
        self.script = str(ROOT / 'scripts/log-persist.sh')

    def tearDown(self):
        self.tmp.cleanup()

    def lp(self, *args, **env):
        e = dict(self.env)
        e.update(env)
        return sh(self.script_cmd(args), e)

    def script_cmd(self, args):
        return '%s %s %s' % (' '.join(SH), self.script, ' '.join("'%s'" % a for a in args))

    def boots(self):
        return sorted(p.name for p in (self.d / 'sd' / 'logs').glob('boot-*')) if (self.d / 'sd' / 'logs').exists() else []

    def new_boot(self):
        (self.d / 'state').unlink()

    def test_save_writes_the_logs_of_this_boot(self):
        r = self.lp('save', 'test')
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.d / 'sd' / 'logs' / 'boot-0001'
        self.assertEqual(sorted(p.name for p in b.iterdir()), ['dmesg.log', 'meta.txt', 'other.log', 'syslog.log', 'tc100_rtsp.log'])
        self.assertEqual((b / 'dmesg.log').read_text(), 'kernel line\n' * 50)
        self.assertIn('guard line', (b / 'other.log').read_text())
        self.assertIn('why=test', (b / 'meta.txt').read_text())
        self.assertEqual((self.d / 'sd' / 'logs' / '.bootcount').read_text().strip(), '0001')

    def test_counter_with_leading_zeros_is_decimal(self):
        # F-05 on IPCAM2: 0008 was read as octal by ash, no folder after the 8th boot
        logs = self.d / 'sd' / 'logs'
        for old, new in (('0007', '0008'), ('0008', '0009'), ('0009', '0010'), ('0099', '0100'), ('0000', '0001')):
            logs.mkdir(parents=True, exist_ok=True)
            (logs / '.bootcount').write_text(old + '\n')
            if (self.d / 'state').exists():
                self.new_boot()
            r = self.lp('save')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((logs / '.bootcount').read_text().strip(), new)
            self.assertTrue((logs / ('boot-' + new)).is_dir(), self.boots())

    def test_second_save_of_the_same_boot_reuses_the_folder_and_skips_unchanged_files(self):
        self.lp('save')
        b = self.d / 'sd' / 'logs' / 'boot-0001'
        m1 = (b / 'dmesg.log').stat().st_mtime_ns
        time.sleep(0.05)
        (self.d / 'rtsp.log').write_text('rtsp line\n' * 40 + 'new\n')
        self.lp('save')
        self.assertEqual(self.boots(), ['boot-0001'])
        self.assertEqual((b / 'dmesg.log').stat().st_mtime_ns, m1)          # unchanged: not rewritten
        self.assertIn('new', (b / 'tc100_rtsp.log').read_text())

    def test_keeps_the_last_five_boots(self):
        for _ in range(8):
            self.lp('save')
            self.new_boot()
        self.assertEqual(self.boots(), ['boot-0004', 'boot-0005', 'boot-0006', 'boot-0007', 'boot-0008'])

    def test_files_are_capped(self):
        (self.d / 'dmesg').write_text('x' * 5000 + 'END\n')
        r = self.lp('save', LP_FILECAP='1000', LP_OTHERCAP='500')
        self.assertEqual(r.returncode, 0, r.stderr)
        b = self.d / 'sd' / 'logs' / 'boot-0001'
        self.assertEqual((b / 'dmesg.log').stat().st_size, 1000)
        self.assertTrue((b / 'dmesg.log').read_text().endswith('END\n'))      # the tail is kept
        self.assertLessEqual((b / 'other.log').stat().st_size, 500)

    def test_a_boot_stays_under_its_cap(self):
        big = 'y' * 90 + '\n'
        for n in ('dmesg', 'messages', 'rtsp.log'):
            (self.d / n).write_text(big * 20000)                         # 1.8 MB each
        (self.d / 'ram' / 'other.log').write_text(big * 5000)
        self.lp('save')
        b = self.d / 'sd' / 'logs' / 'boot-0001'
        total = sum(p.stat().st_size for p in b.iterdir())
        self.assertLessEqual(total, 2097152)
        self.assertLessEqual((b / 'dmesg.log').stat().st_size, 400000)

    def test_nothing_is_written_when_it_should_not(self):
        (self.d / 'pause').write_text('')                                    # recording paused / card being ejected
        self.lp('save')
        self.assertEqual(self.boots(), [])
        (self.d / 'pause').unlink()
        (self.d / 'health').write_text('state=readonly\n')                    # card not healthy
        self.lp('save')
        self.assertEqual(self.boots(), [])
        (self.d / 'health').write_text('state=ok\n')
        (self.d / 'boot.conf').write_text('LOG_PERSIST=0\n')                  # switched off
        self.lp('save')
        self.assertEqual(self.boots(), [])
        (self.d / 'boot.conf').write_text('LOG_PERSIST=1\n')
        (self.d / 'mounts').write_text('tmpfs / tmpfs rw 0 0\n')               # no card mounted
        self.lp('save')
        self.assertEqual(self.boots(), [])
        (self.d / 'mounts').write_text('x %s vfat rw 0 0\n' % (self.d / 'sd'))
        self.lp('save')
        self.assertEqual(self.boots(), ['boot-0001'])                         # and back to normal

    def test_not_enough_free_space(self):
        self.lp('save', LP_MIN_FREE_KB='999999999')
        self.assertEqual(self.boots(), [])

    def test_shutdown_saves_with_a_reason_and_a_dead_lock_is_taken_over(self):
        (self.d / 'lock').mkdir()
        (self.d / 'lock' / 'pid').write_text('999999\n')
        self.lp('shutdown', 'web UI: reboot')
        b = self.d / 'sd' / 'logs' / 'boot-0001'
        self.assertIn('why=shutdown: web UI: reboot', (b / 'meta.txt').read_text())
        self.assertFalse((self.d / 'lock').exists())

    def test_list_and_cat(self):
        self.lp('save')
        self.new_boot()
        self.lp('save', 'second')
        j = json.loads(self.lp('list').stdout)
        self.assertEqual([x['boot'] for x in j], ['boot-0002', 'boot-0001'])        # newest first
        self.assertEqual([x['current'] for x in j], [1, 0])
        self.assertIn('dmesg.log', [f['name'] for f in j[1]['files']])
        r = self.lp('cat', 'boot-0001', 'syslog.log')
        self.assertEqual(r.stdout, 'syslog line\n' * 30)
        for bad in (('boot-0001', '../boot.conf'), ('../x', 'dmesg.log'), ('boot-1', 'dmesg.log'), ('boot-0001', '.hidden'),
                    ('boot-0001', 'a b')):
            self.assertNotEqual(self.lp('cat', *bad).returncode, 0, bad)

    def test_reboot_tracker_and_autorun_call_it(self):
        t = (ROOT / 'scripts/reboot-tracker.sh').read_text()
        self.assertIn('log-persist.sh', t)
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('log-persist.sh run', a)
        self.assertIn('"$BC_LOG_PERSIST" != 0', a)
        self.assertIn('\nLOG_PERSIST=1\n', (ROOT / 'config/boot.conf.dist').read_text())

    def test_reboot_tracker_intent_saves_first(self):
        (self.d / 'rt').mkdir()
        fake = self.d / 'fake-persist.sh'
        fake.write_text('echo "$@" > %s/called\n' % self.d)
        r = sh('%s %s intent "web UI: test"' % (' '.join(SH), ROOT / 'scripts/reboot-tracker.sh'),
               dict(REBOOT_TRACKER_DIR=str(self.d / 'rt'), REBOOT_TRACKER_MARK=str(self.d / 'ram' / 'm'),
                    LOG_PERSIST_SH=str(fake)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.d / 'called').read_text().strip(), 'shutdown web UI: test')
        self.assertTrue((self.d / 'rt' / '.reboot-intent').exists())


class MemoryGuardDefaults(unittest.TestCase):
    def run_migration(self, conf):
        with tempfile.TemporaryDirectory() as d:
            bc = Path(d) / 'boot.conf'
            bc.write_text(conf)
            code = function('scripts/common_functions.sh', 'rewrite_config') + '\n' + function('controlscripts/memory-guard', 'mg_migrate_defaults')
            code += '\nget_now_ts() { echo 1; }\nLOGPATH=%s/mg.log; CONFIGPATH=%s\nmg_migrate_defaults\nmg_migrate_defaults\n' % (d, d)
            r = sh(code, dict(MEM_GUARD_BOOTCONF=str(bc)))
            self.assertEqual(r.returncode, 0, r.stderr)
            return bc.read_text()

    OLD = ('MEM_GUARD_ENABLE=1\nMEM_GUARD_WARN_KB=8192\nMEM_GUARD_CRITICAL_KB=4096\nMEM_GUARD_EMERGENCY_KB=2048\n'
           'MEM_GUARD_SOFT_SERVICES="network-monitor auto-night-detection"\nMEM_GUARD_CRITICAL_SERVICES="ftp-server telnet-server motion-detection"\n')

    def test_exact_old_defaults_are_moved(self):
        out = self.run_migration(self.OLD)
        self.assertIn('MEM_GUARD_WARN_KB=6144\n', out)
        self.assertIn('MEM_GUARD_CRITICAL_KB=3072\n', out)
        self.assertIn('MEM_GUARD_SOFT_SERVICES="network-monitor"\n', out)
        self.assertIn('MEM_GUARD_ENABLE=1\n', out)
        self.assertIn('MEM_GUARD_CRITICAL_SERVICES="ftp-server telnet-server motion-detection"\n', out)

    def test_chosen_values_are_left_alone(self):
        for conf in (self.OLD.replace('8192', '7000'), self.OLD.replace('4096', '4000'), self.OLD.replace('8192', '10000').replace('4096', '5000'),
                     self.OLD.replace('8192', '6144').replace('4096', '3072')):
            self.assertEqual(self.run_migration(conf), conf)

    def test_custom_soft_services_survive_the_migration(self):
        conf = self.OLD.replace('"network-monitor auto-night-detection"', '"network-monitor"')
        out = self.run_migration(conf.replace('"network-monitor"', '"network-monitor syslog-forward"'))
        self.assertIn('MEM_GUARD_WARN_KB=6144\n', out)
        self.assertIn('MEM_GUARD_SOFT_SERVICES="network-monitor syslog-forward"\n', out)

    def test_defaults_everywhere(self):
        boot = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('\nMEM_GUARD_WARN_KB=6144\n', boot)
        self.assertIn('\nMEM_GUARD_CRITICAL_KB=3072\n', boot)
        self.assertIn('\nMEM_GUARD_SOFT_SERVICES="network-monitor"\n', boot)
        mg = (ROOT / 'controlscripts/memory-guard').read_text()
        self.assertIn('MEM_GUARD_WARN_KB:-6144', mg)
        self.assertIn('MEM_GUARD_CRITICAL_KB:-3072', mg)
        self.assertNotIn('_auto_warn', mg)
        self.assertIn('6144', (ROOT / 'www/cgi-bin/state.cgi').read_text())
        self.assertIn('6144', (ROOT / 'scripts/action.d/video.sh').read_text())


class Rc9SocWiring(unittest.TestCase):
    """3.0.1-rc9 (test queue R9-00 to R9-03): pool default, 3D-NR switch, anti-flicker field and its use."""

    def test_pool_default_and_nr3d_off_by_default(self):
        p15 = (ROOT / 'patches/kernel-6.6/series/0015-misc-ak39_venc-encoder-pool-from-a-reusable-CMA-area.patch').read_text(encoding='utf-8')
        self.assertIn('+static char *pool = "9600K";', p15)
        p6 = (ROOT / 'patches/kernel-6.6/series/0006-media-anyka-isp-add-ISP-video-input-and-sensor-drive.patch').read_text(encoding='utf-8', errors='replace')
        self.assertIn('+static int nr3d;\n+module_param(nr3d, int, 0444);', p6)
        # reserved at probe only when asked, never at stream start any more
        self.assertIn('+	if (nr3d)\n+		alloc_ref(vi);', p6)
        prog = p6[p6.index('+static void program_ref('):]
        prog = prog[:prog.index('\n+}\n')]
        self.assertNotIn('dma_alloc', prog)

    def test_anti_flicker_field_and_server(self):
        html = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        m = re.search(r'<select name="isp_power_hz" id="isp_power_hz">(.*?)</select>', html)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r'value="(\d*)"', m.group(1)), ['', '50', '60'])
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('"POWER_HZ"', src)
        self.assertIn('a[8] = (unsigned int)((rate + p_hz) / (2 * p_hz))', src)
        # 28125 sensor lines a second: one lamp pulse is 281 lines at 50 Hz, 234 at 60 Hz
        self.assertEqual(((28125 + 50) // 100, (28125 + 60) // 120), (281, 234))


if __name__ == '__main__':
    unittest.main()
