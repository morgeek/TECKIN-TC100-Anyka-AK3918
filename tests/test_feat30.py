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
        sw = [c for c in self.feed('ae', s, pre + '; MIN_SWITCH=60') if c[1] != c[2]]
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

    def test_minimum_time_between_two_switches(self):
        """Item 21: MIN_SWITCH (180 s by default, 60 with override) between two switches, whatever the source; 0 = none"""
        dark, light = '50 1 256 256 256 1', '50 1 256 256 256 0'
        s = [(100, dark), (101, dark), (110, light), (111, light), (150, light), (161, light), (162, light)]
        sw = [c for c in self.feed('isp', s, 'NIGHT_HOLD=1; DAY_HOLD=1; MIN_SWITCH=60') if c[1] != c[2]]
        self.assertEqual(sw, [(101, '1', '0'), (161, '0', '1')])      # day wanted at 111, allowed 60 s after 101
        sw = [c for c in self.feed('isp', s, 'NIGHT_HOLD=1; DAY_HOLD=1; MIN_SWITCH=0') if c[1] != c[2]]
        (self.d / 'ircut').write_text('1\n')
        self.assertEqual(sw, [(101, '1', '0'), (111, '0', '1')])

    def test_isp_dark_flag_with_holds(self):
        pre = 'NIGHT_HOLD=10; DAY_HOLD=60; MIN_SWITCH=60'
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
        self.assertTrue(lines[0].endswith('mode=night src=luma luma=47 ae=9 1124 6840 256 256 0 idx=30031 lum=30368 awb=-'), lines[0])
        self.assertTrue(lines[2].endswith('ae=- idx=- lum=- awb=-'), lines[2])

    def vendor(self, samples, awb, cut='1', pre=''):
        """samples: (time, cam_ae line); awb: cam_awb line or None; returns the ircut value after each sample"""
        if awb is not None:
            (self.d / 'awb').write_text(awb + '\n')
        (self.d / 'ircut').write_text(cut + '\n')
        code = '. %s\n%s\n' % (self.daemon, pre)
        for t, line in samples:
            code += 'echo "%s" > "$CAM_AE"; dn_step_vendor %d; cat "$DN_IRCUT"\n' % (line, t)
        r = sh(code, dict(self.env, CAM_AWB=str(self.d / 'awb')))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def test_vendor_metric_divides_by_the_picture_brightness(self):
        """R12-03: stock metric exp * gain / exp_max * 40 / lumi (vendor-re-findings.md)"""
        r = sh('. %s\ndn_vendor_lum 50 1124 6840 256 256 0 1125 && echo $DN_LUM\n'
               'dn_vendor_lum 9 1124 6840 256 256 0 1125 && echo $DN_LUM\n'
               'dn_vendor_lum 50 1124 6840 256 256 0 && echo $DN_LUM\n' % self.daemon, self.env)
        self.assertEqual(r.stdout.split(), ['5466', '30368', '5466'])   # dim day room, IR night, no 7th field = 1125

    def test_vendor_daylight_counts_keep_the_day(self):
        dark = '9 1124 6840 256 256 0 1125'
        s = [(100, dark), (102, dark), (104, dark)]
        self.assertEqual(self.vendor(s, '400000 0 0 0 0 0 0 0 0 0 3'), ['1', '1', '1'])     # white balance sees daylight
        self.assertEqual(self.vendor(s, '100 100 0 0 0 0 0 0 0 0 3'), ['1', '1', '0'])      # 3 samples: night

    def test_vendor_day_needs_visible_light(self):
        lit = '60 300 256 256 256 0 2812'
        s = [(100, lit), (102, lit), (104, lit)]
        self.assertEqual(self.vendor(s, '1000 900 800 700 600 0 0 0 0 0 3', cut='0'), ['0', '0', '0'])   # IR only
        self.assertEqual(self.vendor(s, '20000 900 800 700 600 0 0 0 0 0 3', cut='0'), ['0', '0', '1'])

    def test_vendor_switch_back_within_15_s_locks(self):
        dark, lit = '9 1124 6840 256 256 0 1125', '60 300 256 256 256 0 2812'
        s = [(100, dark), (102, dark), (104, dark),            # night at 104
             (106, lit), (108, lit), (110, lit),               # back to day 6 s later: locked instead
             (112, lit), (114, lit), (116, lit)]               # still locked (same scene)
        out = self.vendor(s, '20000 0 0 0 0 0 0 0 0 0 3', pre='AWB_DAY_CNT=300000')
        self.assertEqual(out, ['1', '1', '0', '0', '0', '0', '0', '0', '0'])

    def test_frozen_white_balance_counts_are_ignored(self):
        """R11-02: the same 10 counts for 3 samples are stale: no daylight veto, visible light assumed"""
        (self.d / 'awb').write_text('400000 0 0 0 0 0 0 0 0 0 5\n')
        r = sh('. %s\nfor i in 1 2 3; do dn_awb; echo "$DN_AWB_DAY$DN_AWB_VIS"; done\n' % self.daemon,
               dict(self.env, CAM_AWB=str(self.d / 'awb')))
        self.assertEqual(r.stdout.split(), ['11', '11', '01'])   # daylight seen twice, then stale: no veto

    def test_ir_led_protection(self):
        (self.d / 'ircut').write_text('0\n')
        r = sh('. %s\nIR_LED_MAX_ON=100; IR_LED_REST=50\n'
               'DN_NOW=1000; dn_ir_guard; echo "a$? $(cat $DN_IRCUT)"\n'
               'DN_NOW=1100; dn_ir_guard; echo "b$? $(cat $DN_IRCUT)"\n'
               'DN_NOW=1120; dn_ir_guard; echo "c$? $(cat $DN_IRCUT)"\n'
               'DN_NOW=1160; dn_ir_guard; echo "d$? $(cat $DN_IRCUT)"\n' % self.daemon, self.env)
        self.assertEqual(r.stdout.split('\n')[:4], ['a1 0', 'b0 1', 'c0 1', 'd1 1'])   # 100 s of night, 50 s rest

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
        self.assertIn('MEM_GUARD_SOFT_SERVICES=""\n', out)
        self.assertIn('MEM_GUARD_ENABLE=1\n', out)
        self.assertIn('MEM_GUARD_CRITICAL_SERVICES="ftp-server telnet-server motion-detection"\n', out)

    def test_chosen_values_are_left_alone(self):
        base = self.OLD.replace('network-monitor ', '')   # the removed service's name is dropped on purpose
        for conf in (base.replace('8192', '7000'), base.replace('4096', '4000'), base.replace('8192', '10000').replace('4096', '5000'),
                     base.replace('8192', '6144').replace('4096', '3072')):
            self.assertEqual(self.run_migration(conf), conf)

    def test_custom_soft_services_survive_the_migration(self):
        conf = self.OLD.replace('"network-monitor auto-night-detection"', '"network-monitor syslog-forward"')
        out = self.run_migration(conf)
        self.assertIn('MEM_GUARD_WARN_KB=6144\n', out)
        self.assertIn('MEM_GUARD_SOFT_SERVICES="syslog-forward"\n', out)

    def test_removed_network_monitor_name_is_dropped(self):
        conf = self.OLD.replace('8192', '7000').replace('"network-monitor auto-night-detection"', '"network-monitor syslog-forward"')
        out = self.run_migration(conf)
        self.assertIn('MEM_GUARD_WARN_KB=7000\n', out)
        self.assertIn('MEM_GUARD_SOFT_SERVICES="syslog-forward"\n', out)
        self.assertNotIn('network-monitor', out)

    def test_defaults_everywhere(self):
        boot = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('\nMEM_GUARD_WARN_KB=6144\n', boot)
        self.assertIn('\nMEM_GUARD_CRITICAL_KB=3072\n', boot)
        self.assertIn('\nMEM_GUARD_SOFT_SERVICES=""\n', boot)
        self.assertNotIn('network-monitor', boot)
        mg = (ROOT / 'controlscripts/memory-guard').read_text()
        self.assertIn('MEM_GUARD_WARN_KB:-6144', mg)
        self.assertIn('MEM_GUARD_CRITICAL_KB:-3072', mg)
        self.assertNotIn('_auto_warn', mg)
        self.assertIn('6144', (ROOT / 'www/cgi-bin/state.cgi').read_text())
        self.assertIn('6144', (ROOT / 'scripts/action.d/video.sh').read_text())


class WifiRecover(unittest.TestCase):
    """scripts/wifi-recover.sh (W-NET: the Wi-Fi chip failed to power on after warm reboots, no wlan0)"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        for p in ('class/net', 'class/gpio/gpio523', 'usb'):
            (self.d / p).mkdir(parents=True)
        (self.d / 'class/gpio/export').write_text('')
        (self.d / 'usb/authorized').write_text('1\n')
        self.env = dict(WR_SYS=str(self.d), WR_DEV=str(self.d / 'usb'), WR_WAIT='1', WR_APPLY=str(self.d / 'apply'),
                        WR_BOOTCONF=str(self.d / 'boot.conf'), WR_CONSOLE=str(self.d / 'console'),
                        WR_LOCK=str(self.d / 'lock'), WR_LAST=str(self.d / 'last'))
        self.script = str(ROOT / 'scripts/wifi-recover.sh')

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_done_when_wlan0_is_there(self):
        (self.d / 'class/net/wlan0').mkdir()
        r = sh('sh %s run; echo rc=$?' % self.script, self.env)
        self.assertIn('rc=0', r.stdout)
        self.assertFalse((self.d / 'console').exists())

    def test_probe_then_power_cycle_then_gives_up(self):
        r = sh('sh %s run; echo rc=$?' % self.script, self.env, timeout=30)
        self.assertIn('rc=1', r.stdout)
        log = (self.d / 'console').read_text()
        self.assertIn('probing the Wi-Fi chip again', log)
        self.assertIn('power cycle of the Wi-Fi chip (GPIO 523)', log)
        self.assertIn('not recovered', log)
        self.assertEqual((self.d / 'class/gpio/gpio523/value').read_text().strip(), '1')   # power back on
        self.assertEqual((self.d / 'usb/authorized').read_text().strip(), '1')
        # a second call right away is spaced out (net-guard calls it every minute)
        (self.d / 'console').unlink()
        r = sh('sh %s run; echo rc=$?' % self.script, self.env)
        self.assertIn('rc=0', r.stdout)
        self.assertFalse((self.d / 'console').exists())

    def test_gpio_can_be_left_alone(self):
        (self.d / 'boot.conf').write_text('WIFI_POWER_GPIO=0\n')
        sh('sh %s run' % self.script, self.env, timeout=30)
        self.assertNotIn('power cycle', (self.d / 'console').read_text())
        self.assertFalse((self.d / 'class/gpio/gpio523/value').exists())

    def test_wired_into_boot_and_net_guard(self):
        self.assertIn('sh /mnt/scripts/wifi-recover.sh run', (ROOT / 'v3/autorun-linux66.sh').read_text())
        self.assertIn('wifi-recover.sh}" run', (ROOT / 'scripts/net-guard.sh').read_text())
        self.assertIn('wifi_power_fail=', (ROOT / 'scripts/log-persist.sh').read_text())


class Rc9SocWiring(unittest.TestCase):
    """3.0.1-rc9 (test queue R9-00 to R9-03): pool default, 3D-NR switch, anti-flicker field and its use."""

    def test_pool_default_and_nr3d_off_by_default(self):
        p15 = (ROOT / 'patches/kernel-6.6/series/0015-misc-ak39_venc-encoder-pool-from-a-reusable-CMA-area.patch').read_text(encoding='utf-8')
        self.assertIn('+static char *pool = "9600K";', p15)
        p6 = (ROOT / 'patches/kernel-6.6/series/0006-media-anyka-isp-add-ISP-video-input-and-sensor-drive.patch').read_text(encoding='utf-8', errors='replace')
        self.assertIn('+static int nr3d;\n', p6)
        self.assertIn('module_param_cb(nr3d, &nr3d_ops, &nr3d, 0644);', p6)   # writable since [nr3d], default 0
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

    def test_camera_default_anti_flicker_is_shown(self):
        """rc10: the empty choice is the tuning file's step (50 Hz on IPCAM2), not "Off" (R9-03)"""
        html = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        self.assertIn('<option value="">Camera default</option>', html)
        self.assertIn('id="isp_power_hz_base"', html)
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('POWER_HZ_BASE=%d', src)
        self.assertIn('POWER_HZ_BASE', (ROOT / 'scripts/isp-tune.sh').read_text())
        self.assertIn('"Camera default: " + hb + " Hz."', (ROOT / 'www/scripts/index.bundle.min.js').read_text(encoding='utf-8'))

    def test_settings_saved_before_a_deliberate_reboot(self):
        """rc11: cfg-persist flush from reboot-tracker intent (R10-01 lost a setting changed 35 s before)"""
        rt = (ROOT / 'scripts/reboot-tracker.sh').read_text()
        self.assertIn('sh "$_cp" flush', rt)
        self.assertLess(rt.index('flush'), rt.index('log-persist.sh'))
        cp = (ROOT / 'v3/linux66-sd/cfg-persist').read_text()
        flush = cp[cp.index('flush)'):cp.index('saved)')]
        self.assertIn('[ "$(signature)" = "$(cat /tmp/cfg-persist.sig)" ] && exit 0', flush)

    def test_awb_state_alone_never_triggers_a_flash_save(self):
        """awb.state (white balance gains, rewritten every few minutes) is in the slot but not in the change signature"""
        cp = (ROOT / 'v3/linux66-sd/cfg-persist').read_text(encoding='utf-8')
        helpers = cp[:cp.index('\ncase "$1" in')]
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / 'config'
            cfg.mkdir()
            (cfg / 'boot.conf').write_text('A=1\n')
            (cfg / 'awb.state').write_text('r=256\nb=256\n')
            lib = Path(d) / 'lib.sh'
            lib.write_text(helpers)
            env = dict(CFG=str(cfg), DEFAULTS=str(Path(d) / 'none'))

            def run(cmd):
                r = sh('. %s; %s' % (lib, cmd), env)
                self.assertEqual(r.returncode, 0, r.stderr)
                return r.stdout.strip()
            sig = run('signature')
            (cfg / 'awb.state').write_text('r=300\nb=210\n')
            self.assertEqual(run('signature'), sig)
            self.assertIn('config/awb.state', run('cd "$(dirname $CFG)"; list'))   # still stored in every slot
            (cfg / 'boot.conf').write_text('A=2\n')
            self.assertNotEqual(run('signature'), sig)
        self.assertIn('*/awb.state) continue ;;', cp)

    def test_smart_mode_wiring(self):
        """rc11: ak_venc_set_smart_config only when RTSP_SMART is 1 or 2 and VBR is on (R11-01)"""
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('p_smart = dlsym(m, "ak_venc_set_smart_config");', src)
        f = src[src.index('static void smart_apply('):]
        f = f[:f.index('\n}\n')]
        self.assertIn('env_int(ks, 0, 0, 2)', f)
        self.assertIn('if (!s->pa.rc_vbr)', f)
        self.assertGreaterEqual(src.count('smart_apply('), 5)   # definition + every encoder open

    def test_rc12_settings_are_wired_page_to_server(self):
        """every rc12 switch has a field, a save path, a read-back in state.cgi and reaches tc100_rtsp or the daemon"""
        html = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        self.assertNotIn('id="smart0"', html)   # R11-01: smart mode stops the server on this camera, not on the page
        for f in ('vbr0', 'dn_vendor_night', 'dn_vendor_day', 'dn_ir_max_h', 'dn_nightstyle', 'dn_lowlight', 'dn_live_lum'):
            self.assertIn('id="%s"' % f, html)
        self.assertIn('<option value="vendor">', html)
        video = (ROOT / 'scripts/action.d/video.sh').read_text()
        for k in ('F_vbr0', 'F_smart0', 'F_dn_vendor_night', 'F_dn_vendor_day', 'F_dn_ir_max_h', 'F_dn_nightstyle', 'F_dn_lowlight',
                  'VENDOR_NIGHT_LUM=%s', 'IR_LED_MAX_ON=%s', 'NIGHT_STYLE=%s', 'LOWLIGHT_FPS=%s'):
            self.assertIn(k, video)
        state = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        for k in ('"vbr":%s', '"smart":%s', '"vendor_lum":%s', '"night_style":%s', '"lowlight_fps":%s', 'ae|isp|vendor'):
            self.assertIn(k, state)
        bundle = (ROOT / 'www/scripts/index.bundle.min.js').read_text(encoding='utf-8')
        for k in ("setVal('vbr0'", 'put("dn_vendor_night"', 'chk("dn_nightstyle"', 'set("dn_live_lum"'):
            self.assertIn(k, bundle)
        launch = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text()
        for k in ('RTSP_VBR_CONFIG=1', 'RTSP_SMART_CONFIG=$2', 'export RTSP_NIGHTSTYLE=1', 'export RTSP_LOWLIGHT_FPS=1'):
            self.assertIn(k, launch)
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        for k in ('getenv("RTSP_NIGHTSTYLE")', 'getenv("RTSP_LOWLIGHT_FPS")', 'ISP_SET_TUNING_STYLE', 'style_switch(bw)'):
            self.assertIn(k, src)
        daemon = (ROOT / 'scripts/auto-night-daemon.sh').read_text()
        self.assertIn('VENDOR_NIGHT_LUM|VENDOR_DAY_LUM|AWB_DAY_CNT|AWB_NIGHT_CNT|VENDOR_LOCK|IR_LED_MAX_ON|IR_LED_REST)', daemon)

    def test_speaker_amplifier_active_low(self):
        """R12-04: the stock kernel plays with GPIO 14 low; the amplifier is off at rest"""
        dts = (ROOT / 'patches/kernel-6.6/series/0009-ARM-dts-anyka-add-TECKIN-TC100-board.patch').read_text(encoding='utf-8')
        self.assertIn('+		speak-gpios-en = <0>;', dts)
        codec = (ROOT / 'patches/kernel-6.6/series/0007-ASoC-arm-add-AK39-codec-and-PCM-driver.patch').read_text(encoding='utf-8', errors='replace')
        self.assertIn('+module_param(spk_active, int, 0444);', codec)
        self.assertNotIn('ak39_codec_speak_on(codec, !plug_in)', codec)

    def test_manual_daynight_is_said(self):
        """rc10: daynight=3 kept the automatic switching off without a word (R9-02)"""
        self.assertIn('not started: manual day/night mode (daynight=3)', (ROOT / 'v3/autorun-linux66.sh').read_text())
        d = Path(tempfile.mkdtemp())
        (d / 'rtspserver.conf').write_text('daynight=3\n')
        cs = (ROOT / 'controlscripts/auto-night-detection').read_text().replace('/mnt/config/rtspserver.conf', str(d / 'rtspserver.conf'))
        cs = cs.replace('L66=0; [ -f /tmp/linux66 ] && L66=1', 'L66=1').replace('PIDFILE="/var/run/', 'PIDFILE="%s/' % d)
        (d / 'cs').write_text(cs)
        r = sh('sh %s health' % (d / 'cs'))
        self.assertEqual(r.stdout.strip(), 'ok: manual day/night mode (daynight=3), automatic switching off', r.stderr)
        (d / 'rtspserver.conf').write_text('daynight=2\n')
        self.assertEqual(sh('sh %s health' % (d / 'cs')).stdout.strip(), 'warn: stopped')
        shutil.rmtree(d)


class AutoInstall(unittest.TestCase):
    """3.0.1-rc17 (test queue R17-01): the card installs to the flash by itself, after the checks, with a way back."""

    def setUp(self):
        self.ai = (ROOT / 'v3/install/auto-install.sh').read_text(encoding='utf-8')
        self.rs = (ROOT / 'v3/install/restore-stock.sh').read_text(encoding='utf-8')
        self.ar = (ROOT / 'v3/autorun-linux66.sh').read_text(encoding='utf-8')

    def test_checks_come_before_the_flash_write(self):
        body = self.ai[self.ai.index('first_install || exit 0'):]
        run = body.index('install66.sh run')
        for gate in ('restore-stock.sh --check', 'install66.sh check', 'pidof tc100_rtsp', 'find /tmp/cam_luma -newer'):
            self.assertLess(body.index(gate), run, gate)
        # tried once per card, marked before anything is written (no loop if the camera restarts in the middle)
        self.assertLess(body.index('date > "$K/auto-install.tried"'), run)
        self.assertLess(body.index('ESSAI.txt TRIAL.txt'), run)

    def test_never_over_a_flash_that_holds_3_0_nor_in_flash_mode(self):
        self.assertIn('fd377a585a00', self.ai)      # the xz magic U-Boot's flashcheck looks for
        self.assertIn('first_install() { [ -f "$K/stage1.done" ] && ! flash_has_30', self.ai)
        self.assertIn('[ -f /tmp/linux66 ] && [ ! -f /tmp/flashmode ] || exit 1', self.ai)
        self.assertIn('[ -f /tmp/linux66 ] && [ ! -f /tmp/flashmode ] || fail', self.rs)

    def test_restore_is_asked_for_and_runs_once(self):
        i = self.ai.index('RESTAURER.txt RESTORE.txt); then')
        self.assertLess(self.ai.index('mv -f "$C/$r" "$C/${r%.txt}.done"', i), self.ai.index('restore-stock.sh >>', i))
        self.assertIn('c66.img.off', self.ai)

    def test_backup_must_be_this_cameras(self):
        # U-Boot (boot, 0..0x39000) and mac (0x239000, one sector) of the copy against the flash, md5 required
        self.assertIn('for p in boot:0:57 mac:569:1; do', self.rs)
        self.assertEqual((0x39000 // 4096, 0x239000 // 4096), (57, 569))
        self.assertIn('fail "$F.md5 not found', self.rs)
        self.assertIn('[ -n "$CHECK" ] && {', self.rs)
        self.assertLess(self.rs.index('[ -n "$CHECK" ] && {'), self.rs.index('FLASHW_ALLOW='))

    def test_autorun_wiring(self):
        self.assertIn('auto-install.sh pending', self.ar)
        self.assertIn('[ $AUTO_INSTALL = 1 ] || ( sleep 3; sh /mnt/scripts/speaker-play.sh', self.ar)
        self.assertIn('[ $AUTO_INSTALL = 1 ] && ( sleep 20; exec sh /mnt/v3/install/auto-install.sh )', self.ar)
        self.assertIn('sh -n', sh('sh -n %s && echo "sh -n"' % (ROOT / 'v3/install/auto-install.sh')).stdout)

    def test_old_tint_and_saturation_reset_once(self):
        i = self.ar.index('1a2.')
        blk = self.ar[i:self.ar.index(': > /mnt/config/.migrated-3.0.1', i)]
        for k in ('HUE 0', 'SATURATION 0', 'boot.conf ISP_TUNE 0'):
            self.assertIn(k, blk)
        self.assertIn('[ ! -f /mnt/config/.migrated-3.0.1 ]', blk)


class FirstBatchEnhancements(unittest.TestCase):
    """Low-risk user-space enhancements: ALSA -D hw:0, persistent SSH keys, behind-glass IR_LED_MODE, and global AWB."""

    def test_alsa_uses_hw0_device_not_card_alias(self):
        for rel in ('scripts/speaker-play.sh', 'scripts/action.d/audio.sh', 'v3/linux66-sd/rtsp-launch.sh'):
            txt = (ROOT / rel).read_text(encoding='utf-8')
            self.assertIn('-D hw:0', txt, rel)
            self.assertNotIn('-c 0', txt, rel)

    def test_ssh_authorized_keys_and_host_key_persistence(self):
        s50 = (ROOT / 'v3/S50dropbear-linux66').read_text(encoding='utf-8')
        ssh = (ROOT / 'controlscripts/ssh-server').read_text(encoding='utf-8')
        cp = (ROOT / 'v3/linux66-sd/cfg-persist').read_text(encoding='utf-8')
        for txt in (s50, ssh, cp):
            self.assertIn('authorized_keys', txt)
            self.assertIn('/root/.ssh/authorized_keys', txt)
            self.assertIn('dropbear_ed25519_host_key', txt)
        self.assertIn('sync_ssh()', cp)
        for rel in ('v3/S50dropbear-linux66', 'controlscripts/ssh-server', 'v3/linux66-sd/cfg-persist'):
            self.assertEqual(sh('sh -n %s' % (ROOT / rel)).returncode, 0, rel)

    def test_behind_glass_ir_led_mode(self):
        d = Path(tempfile.mkdtemp())
        try:
            daemon = ROOT / 'scripts/auto-night-daemon.sh'
            (d / 'daynight.conf').write_text('IR_LED_MODE=off\nIR_LED_MAX_ON=100\n')
            (d / 'rtspserver.conf').write_text('daynight=2\n')
            (d / 'ircut').write_text('0\n')
            env = {
                'DN_TEST': '1',
                'DN_CONSOLE': '/dev/null',
                'DN_CONF': str(d / 'daynight.conf'),
                'DN_RTSPCONF': str(d / 'rtspserver.conf'),
                'DN_IRCUT': str(d / 'ircut'),
            }
            r = sh('. %s\nread_daynight\necho "mode=$IR_LED_MODE"\nDN_NOW=1000; dn_ir_guard; echo "guard=$?"\n' % daemon, env)
            self.assertEqual(r.stdout.split(), ['mode=off', 'guard=1'])
            nm = (ROOT / 'controlscripts/night-mode').read_text(encoding='utf-8')
            self.assertIn('IR_LED_MODE', nm)
            self.assertIn('if [ "$(ir_led_mode)" = "off" ]; then ir_led off; else ir_led on; fi', nm)
            self.assertEqual(sh('sh -n %s' % (ROOT / 'controlscripts/night-mode')).returncode, 0)
            self.assertEqual(sh('sh -n %s' % (ROOT / 'scripts/action.d/video.sh')).returncode, 0)
        finally:
            shutil.rmtree(d)

    def test_global_awb_clamp_and_state_in_rtsp(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        for token in ('awb_max = 1536', 'RTSP_AWB_MAX', 'RTSP_AWB_GREY', 'RTSP_AWB_STATE',
                      '/mnt/config/awb.state', 'rex=%d bex=%d u=%d v=%d'):
            self.assertIn(token, src)



class Lot1B(unittest.TestCase):
    """Remote diagnostics without a serial console: mDNS name, Wi-Fi quality over time, SD card errors."""

    def test_mdns_packet_code(self):
        d = Path(tempfile.mkdtemp())
        try:
            b = d / 'test_mdns'
            subprocess.run(['cc', '-Wall', '-Wextra', '-o', str(b), str(ROOT / 'src/mdnsd/test_mdns.c')], check=True)
            r = subprocess.run([str(b)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('mdns: ok', r.stdout)
        finally:
            shutil.rmtree(d)

    def test_mdns_daemon_is_freestanding_answer_only_and_off_by_default(self):
        src = (ROOT / 'src/mdnsd/mdnsd.c').read_text()
        self.assertEqual(re.findall(r'#include\s+(\S+)', src), ['"mdns_pkt.h"'])
        self.assertIn('(src.addr & mask) != (ip & mask)', src)      # same subnet only
        # DNS-SD and the TXT information only when asked (-s / -v, item 38): off by default
        self.assertIn('int s, on = 1, ttl = 255, loop = 0, svcs = 0, info = 0;', src)
        self.assertIn("grep -q '^MDNS_SERVICES=1' /mnt/config/boot.conf", (ROOT / 'controlscripts/mdns').read_text())
        self.assertTrue((ROOT / 'config/autostart/mdns').exists())  # enabled by default in 3.0.1-rc23
        cs = (ROOT / 'controlscripts/mdns').read_text()
        self.assertIn('/mnt/tc100test/tc100-mdnsd', cs)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'controlscripts/mdns')).returncode, 0)
        self.assertIn('src/mdnsd/mdnsd.c -o $P/tc100-mdnsd', (ROOT / '.github/workflows/build-kernel-linux66.yml').read_text())
        self.assertIn('"$PACK/tc100-mdnsd"', (ROOT / 'v3/build-stack.sh').read_text())
        self.assertIn(' mdns"', (ROOT / 'www/cgi-bin/scripts.cgi').read_text())
        self.assertIn('mdns)            _pf_file="/var/run/mdns.pid"', (ROOT / 'scripts/health-probe.sh').read_text())

    def test_wifi_quality_samples_and_hour_summary(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / 'wireless').write_text('Inter-| sta-|   Quality        |   Discarded packets\n'
                                        ' face | tus | link level noise |  nwid  crypt\n'
                                        ' wlan0: 0000   44.  -66.  -256        0      0\n')
            (d / 'st').write_text('Station aa:bb (on wlan0)\n\ttx retries:\t100\n\ttx failed:\t5\n')
            (d / 'ping').write_text('3 packets transmitted, 2 packets received, 33% packet loss\n')
            env = dict(WQ_LOG=str(d / 'log'), WQ_SUM=str(d / 'sum'), WQ_STATE=str(d / 'prev'),
                       WQ_WIRELESS=str(d / 'wireless'), WQ_STATION=str(d / 'st'), WQ_PING=str(d / 'ping'))
            script = ROOT / 'scripts/wifi-quality.sh'
            r = sh('WQ_NOW=1000 sh %s sample' % script, env)
            self.assertEqual(r.returncode, 0, r.stderr)
            (d / 'st').write_text('Station aa:bb (on wlan0)\n\ttx retries:\t130\n\ttx failed:\t7\n')
            (d / 'wireless').write_text(' wlan0: 0000   30.  -80.  -256        0      0\n')
            (d / 'ping').write_text('3 packets transmitted, 3 packets received, 0% packet loss\n')
            sh('WQ_NOW=1060 sh %s sample' % script, env)
            lines = (d / 'log').read_text().split('\n')
            self.assertEqual(lines[:2], ['1000 -66 0 0 33', '1060 -80 30 2 0'])   # first sample: no deltas yet
            summ = dict(l.split('=') for l in (d / 'sum').read_text().split())
            self.assertEqual((summ['rssi'], summ['rssi_min_1h'], summ['rssi_avg_1h'], summ['loss_pct_1h'],
                              summ['retries_1h'], summ['failed_1h'], summ['samples_1h']),
                             ('-80', '-80', '-73', '17', '30', '2', '2'))
            # no router answer at all: loss is null, the summary still comes out; the driver's -256 is no reading
            (d / 'ping').write_text('')
            (d / 'wireless').write_text(' wlan0: 0000   0.  -256.  -256        0      0\n')
            sh('WQ_NOW=5000 sh %s sample' % script, env)
            summ = dict(l.split('=') for l in (d / 'sum').read_text().split())
            self.assertEqual((summ['samples_1h'], summ['loss_pct_1h']), ('1', 'null'))
            self.assertEqual((summ['rssi'], summ['rssi_min_1h']), ('null', 'null'))
        finally:
            shutil.rmtree(d)

    def test_wifi_quality_is_off_by_default_and_reaches_mqtt(self):
        self.assertIn('\nWIFI_QUALITY=1\n', (ROOT / 'config/boot.conf.dist').read_text())   # on by default since the rc28
        ar = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('on "$BC_WIFI_QUALITY"', ar)
        self.assertIn('job add wifi-quality bg 60 30', ar)
        mq = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        for k in ('"wifi_loss_pct":%s', '"wifi_tx_retries":%s', '"wifi_rssi_min":%s', 'value_json.diag.wifi_loss_pct'):
            self.assertIn(k, mq)

    def test_sd_health_counts_kernel_errors_and_keeps_the_state(self):
        s = (ROOT / 'v3/linux66-sd/sdinfo-sd.sh').read_text()
        self.assertIn("printf 'state=%s\\nerrors=%s\\nreadonly=%s\\n'", s)
        self.assertIn('errors) _hb_err=', (ROOT / 'scripts/reboot-tracker.sh').read_text())
        self.assertIn('kernel error(s) since boot', (ROOT / 'www/cgi-bin/disk.cgi').read_text())


class Lot2BabyphoneAndTamper(unittest.TestCase):
    """Lot 2: Babyphone / Vox mode and Camera Tamper / Occlusion detection."""

    def test_vox_mode_in_sound_detection(self):
        sd = (ROOT / 'controlscripts/sound-detection').read_text()
        self.assertIn('VOX_MODE) vox_mode="$_lc_v" ;;', sd)
        self.assertIn('VOX_HOLD_SECONDS) vox_hold="$_lc_v" ;;', sd)
        self.assertIn('babyphone/state "ON"', sd)
        self.assertIn('babyphone/state "OFF"', sd)
        conf = (ROOT / 'config/sound_detection.conf.dist').read_text()
        self.assertIn('VOX_MODE=0', conf)
        self.assertIn('VOX_HOLD_SECONDS=5', conf)

    def test_tamper_detection_script_and_transition_guard(self):
        script = ROOT / 'scripts/tamper-detect.sh'
        self.assertTrue(script.is_file())
        s = script.read_text()
        self.assertIn('TAMPER_CONF="/mnt/config/tamper.conf"', s)
        self.assertIn('nightmode.last', s)
        self.assertIn('tamper/state "ON"', s)
        self.assertIn('tamper/state "OFF"', s)
        self.assertEqual(sh('sh -n %s' % script).returncode, 0)
        self.assertIn('\nENABLE=0\n', (ROOT / 'config/tamper.conf.dist').read_text())
        self.assertNotIn('TAMPER_DETECT', (ROOT / 'config/boot.conf.dist').read_text())
        self.assertIn('job add tamper-detect bg 2 5', (ROOT / 'v3/autorun-linux66.sh').read_text())

    def test_mqtt_discovery_for_babyphone_and_tamper(self):
        mq = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        self.assertIn('binary_sensor/${node_id}/babyphone/config', mq)
        self.assertIn('binary_sensor/${node_id}/tamper/config', mq)
        self.assertIn('"dev_cla":"sound"', mq)
        self.assertIn('"dev_cla":"problem"', mq)

    def test_sound_db_in_statelib(self):
        lib = (ROOT / 'www/cgi-bin/statelib.cgi').read_text()
        self.assertIn(r'\"sound_db\":$sound_db_json', lib)
        self.assertIn('/var/run/sound_level', lib)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'www/cgi-bin/statelib.cgi')).returncode, 0)


class Lot4NotificationsAndMetrics(unittest.TestCase):
    """Lot 4: Webhook / Ntfy / Telegram notification dispatcher and Prometheus exporter."""

    def test_notify_conf_dist_and_defaults(self):
        conf = (ROOT / 'config/notify.conf.dist').read_text()
        self.assertIn('WEBHOOK_ENABLE=0', conf)
        self.assertIn('NTFY_ENABLE=0', conf)
        self.assertIn('TELEGRAM_NOTIFY_ENABLE=0', conf)
        self.assertIn('NOTIFY_EVENTS="motion sound tamper"', conf)

    def test_notify_script_syntax_and_providers(self):
        script = ROOT / 'scripts/notify.sh'
        self.assertTrue(script.exists())
        self.assertEqual(sh('sh -n %s' % script).returncode, 0)
        s = script.read_text()
        self.assertIn('NTFY_ENABLE', s)
        self.assertIn('WEBHOOK_ENABLE', s)
        self.assertIn('TELEGRAM_NOTIFY_ENABLE', s)
        self.assertIn('NOTIFY_COOLDOWN_SECONDS', s)

    def test_event_scripts_wire_notify(self):
        motion = (ROOT / 'scripts/motion-event.sh').read_text()
        sound = (ROOT / 'controlscripts/sound-detection').read_text()
        tamper = (ROOT / 'scripts/tamper-detect.sh').read_text()

        self.assertIn('/mnt/scripts/notify.sh motion', motion)
        self.assertIn('/mnt/scripts/notify.sh sound', sound)
        self.assertIn('/mnt/scripts/notify.sh tamper', tamper)

    def test_metrics_cgi_exporter(self):
        cgi = ROOT / 'www/cgi-bin/metrics.cgi'
        self.assertTrue(cgi.exists())
        self.assertEqual(sh('sh -n %s' % cgi).returncode, 0)
        r = sh('sh %s' % cgi)
        self.assertEqual(r.returncode, 0)
        self.assertIn('version=0.0.4', r.stdout)
        self.assertIn('tc100_uptime_seconds', r.stdout)
        self.assertIn('tc100_memory_total_bytes', r.stdout)
        self.assertIn('tc100_wifi_link_quality', r.stdout)
        self.assertIn('tc100_rtsp_viewers_active', r.stdout)
        self.assertIn('tc100_motion_active', r.stdout)
        self.assertIn('tc100_tamper_active', r.stdout)
        self.assertIn('tc100_audio_level_dbfs', r.stdout)

    def test_mqtt_bridge_camera_snapshot_image(self):
        mq = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        self.assertIn('snapshot/image', mq)
        self.assertIn('mqtt_publish_file', mq)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'scripts/mqtt-bridge.sh')).returncode, 0)


class Lot2BestShotAndZones(unittest.TestCase):
    """Lot 2 completion: Best-shot selection, named motion zones, pre-roll RAM config."""

    def test_motion_conf_best_shot_default(self):
        conf = (ROOT / 'config/motion.conf.dist').read_text()
        self.assertIn('motion_best_shot=0', conf)

    def test_detection_on_best_shot_logic(self):
        script = ROOT / 'scripts/detectionOn.sh'
        s = script.read_text()
        self.assertIn('motion_best_shot', s)
        self.assertIn('_best_size', s)
        self.assertEqual(sh('sh -n %s' % script).returncode, 0)

    def test_action_detection_named_zones(self):
        det = (ROOT / 'scripts/action.d/detection.sh').read_text()
        self.assertIn('MDZ${_mz_k}_NAME', det)
        self.assertIn('names', det)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'scripts/action.d/detection.sh')).returncode, 0)

    def test_boot_conf_rec_ring_kb_pre_roll(self):
        boot = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('REC_RING_KB=1024', boot)


class Lot3AudioAndSounds(unittest.TestCase):
    """Lot 3: Built-in sound library, siren/chime playback via API/MQTT, and smoke alarm detection."""

    def test_sound_files_exist(self):
        # 2026-11-06 (owner): siren and the startup sound only; chime, alert, startup_2, startup_complete removed
        for name in ('siren.pcm', 'startup.pcm'):
            p = ROOT / 'sounds' / name
            self.assertTrue(p.exists(), name)
            self.assertGreater(p.stat().st_size, 1000)

    def test_action_play_sound_endpoint(self):
        act = (ROOT / 'scripts/action.d/audio.sh').read_text()
        self.assertIn('play_sound)', act)
        self.assertIn('/mnt/scripts/speaker-play.sh', act)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'scripts/action.d/audio.sh')).returncode, 0)

    def test_mqtt_bridge_audio_commands_and_buttons(self):
        mq = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        self.assertIn('play_sound|chime|siren|alarm)', mq)
        self.assertIn('publish_discovery_config "${discovery_prefix}/button/${node_id}/chime/config" ""', mq)   # removed
        for gone in ('chime', 'alert', 'startup_2', 'startup_complete'):
            self.assertFalse((ROOT / 'sounds' / (gone + '.pcm')).exists(), gone)
        self.assertIn('button/${node_id}/siren/config', mq)
        self.assertIn('binary_sensor/${node_id}/alarm/config', mq)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'scripts/mqtt-bridge.sh')).returncode, 0)

    def test_alarm_detection_logic_and_config(self):
        conf = (ROOT / 'config/sound_detection.conf.dist').read_text()
        self.assertIn('ALARM_DETECT=0', conf)
        self.assertIn('ALARM_HOLD_SECONDS=15', conf)
        sd = (ROOT / 'controlscripts/sound-detection').read_text()
        self.assertIn('alarm_detect', sd)
        self.assertIn('sound_alarm_state', sd)
        self.assertIn('alarm/state "ON"', sd)
        self.assertEqual(sh('sh -n %s' % (ROOT / 'controlscripts/sound-detection')).returncode, 0)


class Lot5MultiViewAndTools(unittest.TestCase):
    """Lot 5: Web UI Multi-View 2x2 grid viewer and top navigation integration."""

    def test_multiview_html_exists_and_structure(self):
        mv_path = ROOT / 'www/multiview.html'
        self.assertTrue(mv_path.exists())
        html = mv_path.read_text()
        self.assertIn('mv-grid', html)
        self.assertIn('mv-card', html)
        self.assertIn('mv_img_1', html)
        self.assertIn('mv_img_4', html)
        self.assertIn('/cgi-bin/currentpic.cgi', html)
        self.assertIn('toggleMultiViewConfig', html)
        self.assertIn('saveMultiViewConfig', html)
        self.assertIn('refreshMultiView', html)

    def test_index_html_multiview_nav_item(self):
        index_html = (ROOT / 'www/index.html').read_text()
        self.assertIn('id="multiview_nav"', index_html)
        self.assertIn('data-target="multiview.html"', index_html)
        self.assertIn('Multi-View', index_html)

    def test_sd_diagnostic_and_repair_scripts(self):
        diag_path = ROOT / 'scripts/sd-diag.sh'
        self.assertTrue(diag_path.exists())
        self.assertEqual(sh('sh -n %s' % diag_path).returncode, 0)
        storage_sh = (ROOT / 'scripts/action.d/storage.sh').read_text()
        self.assertIn('sd_card_check)', storage_sh)
        self.assertIn('sd_card_repair)', storage_sh)
        settings_html = (ROOT / 'www/settings.html').read_text()
        self.assertIn('id="btnSdCheck"', settings_html)
        self.assertIn('id="btnSdRepair"', settings_html)

    def test_motion_heatmap_script_and_webui(self):
        hm_path = ROOT / 'scripts/motion-heatmap.sh'
        self.assertTrue(hm_path.exists())
        self.assertEqual(sh('sh -n %s' % hm_path).returncode, 0)
        action_sh = (ROOT / 'scripts/action.d/detection.sh').read_text()
        self.assertIn('motion_heatmap)', action_sh)
        action_cgi = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        self.assertIn('motion_heatmap|', action_cgi)
        det_on = (ROOT / 'scripts/detectionOn.sh').read_text()
        self.assertIn('motion-heatmap.sh record', det_on)
        settings_html = (ROOT / 'www/settings.html').read_text()
        self.assertIn('id="motion_heatmap_bar"', settings_html)

    def test_duplicate_services_are_gone(self):
        # WebDAV (a second httpd on 8080 for /DCIM) and network-monitor (net-guard is the one network watcher) were removed.
        for gone in ('controlscripts/webdav', 'config/webdav.conf.dist', 'controlscripts/network-monitor',
                     'scripts/network-monitor.sh', 'config/netmon.conf.dist'):
            self.assertFalse((ROOT / gone).exists(), gone)
        for f in ('www/cgi-bin/scripts.cgi', 'scripts/health-probe.sh', 'www/cgi-bin/health.cgi', 'scripts/mqtt-bridge.sh',
                  'scripts/health-snapshot.sh', 'www/cgi-bin/action.cgi', 'scripts/action.d/system.sh', 'scripts/net-guard.sh'):
            text = (ROOT / f).read_text()
            self.assertNotIn('webdav', text, f)
            self.assertNotIn('network-monitor', text, f)


class EventsSettingsActions(unittest.TestCase):
    """scripts/action.d/events.sh: Alerts, sound options and tamper from the web page; notify.conf is sourced by a
    shell script, so nothing that a shell would interpret may reach it."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / 'notify.conf').write_text((ROOT / 'config/notify.conf.dist').read_text())
        (self.d / 'tamper.conf').write_text((ROOT / 'config/tamper.conf.dist').read_text())

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_cmd(self, cmd, **fields):
        helpers = '\n'.join([function('scripts/common_functions.sh', 'rewrite_config'),
                             function('scripts/common_functions.sh', 'read_kv_config_value'),
                             function('www/cgi-bin/action.cgi', 'normalize_bool'),
                             function('www/cgi-bin/action.cgi', 'sanitize_int_range'),
                             function('www/cgi-bin/func.cgi', 'json_escape')])
        helpers += ('\ninstall_config() { :; }\njson_body_ok() { echo "OK $1"; }\njson_body_err() { echo "ERR $2"; }\n')
        body = (ROOT / 'scripts/action.d/events.sh').read_text().replace('/mnt/config', str(self.d)) \
            .replace('/mnt/scripts/housekeeper.sh', '/nonexistent')
        env = {'F_cmd': cmd}
        env.update({'F_' + k: v for k, v in fields.items()})
        r = subprocess.run(SH + ['-c', helpers + '\n' + body], capture_output=True, text=True, timeout=20,
                           env=dict(os.environ, **env))
        return r.stdout

    def test_notify_values_are_checked_before_the_file(self):
        before = (self.d / 'notify.conf').read_text()
        for bad in ({'webhook_url': 'http://x/$(reboot)'}, {'webhook_url': 'http://x/"a'}, {'ntfy_topic': 'a b'},
                    {'ntfy_topic': 'a;b'}, {'ntfy_auth': 'Bearer `id`'}, {'webhook_url': 'ftp://x'}):
            self.assertIn('ERR', self.run_cmd('set_notify_config', **bad), bad)
            self.assertEqual((self.d / 'notify.conf').read_text(), before, bad)

    def test_notify_saved_and_sourceable(self):
        out = self.run_cmd('set_notify_config', ntfy_enable='on', ntfy_url='https://ntfy.example.org/', ntfy_topic='cam_1',
                           ntfy_priority='high', ntfy_auth='Bearer tk_abc', notify_event_motion='on',
                           notify_event_tamper='on', notify_cooldown='30', notify_attach_snapshot='on')
        self.assertIn('OK', out)
        r = sh('. %s; echo "$NTFY_ENABLE|$NTFY_URL|$NTFY_TOPIC|$NTFY_PRIORITY|$NTFY_AUTH|$NOTIFY_EVENTS|$NOTIFY_COOLDOWN_SECONDS|$WEBHOOK_ENABLE"'
               % (self.d / 'notify.conf'))
        self.assertEqual(r.stdout.strip(), '1|https://ntfy.example.org|cam_1|high|Bearer tk_abc|motion tamper|30|0')
        self.run_cmd('set_notify_config', ntfy_enable='on', ntfy_topic='cam_1', ntfy_auth='')   # empty keeps the token
        self.assertIn('NTFY_AUTH="Bearer tk_abc"', (self.d / 'notify.conf').read_text())
        info = json.loads(self.run_cmd('events_info'))
        self.assertEqual((info['notify']['ntfy_topic'], info['notify']['ntfy_auth_set']), ('cam_1', 1))
        self.assertNotIn('tk_abc', json.dumps(info))                                            # never sent back

    def test_tamper_and_sound_options(self):
        self.assertIn('OK', self.run_cmd('set_tamper_config', tamper_enable='on', tamper_hold='500', tamper_drop_pct='40'))
        t = (self.d / 'tamper.conf').read_text()
        self.assertIn('\nENABLE=1\n', '\n' + t)
        self.assertIn('TAMPER_HOLD_SEC=120', t)        # out of range: clamped
        self.assertIn('TAMPER_JPEG_DROP_PCT=40', t)
        (self.d / 'sound_detection.conf').write_text('ENABLE=1\n')
        self.assertIn('OK', self.run_cmd('set_sound_options', vox_mode='on', vox_hold='20', alarm_detect='on'))
        s = (self.d / 'sound_detection.conf').read_text()
        for k in ('VOX_MODE=1', 'VOX_HOLD_SECONDS=20', 'ALARM_DETECT=1', 'ALARM_HOLD_SECONDS=15', 'MIN_LOUD_SECONDS=1'):
            self.assertIn(k, s)


class OneSwitchPerService(unittest.TestCase):
    """scripts/service-switch.sh: one settings key per service; migrate-switches.sh keeps what a camera did."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.c = self.d / 'config'
        (self.c / 'autostart').mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.d)

    def sw(self, code):
        return sh('SW_CONF_DIR=%s; . %s; %s' % (self.c, ROOT / 'scripts/service-switch.sh', code))

    def test_key_is_read_and_written(self):
        (self.c / 'boot.conf').write_text('A=1\nREC_LOCAL=0\n')
        self.assertNotEqual(self.sw('svc_on recording').returncode, 0)
        self.assertEqual(self.sw('svc_set recording 1; svc_on recording').returncode, 0)
        self.assertIn('\nREC_LOCAL=1\n', (self.c / 'boot.conf').read_text())
        self.assertEqual(self.sw('svc_on wifi-rescue').returncode, 0)           # missing key: on by default
        self.assertEqual(self.sw('svc_set mqtt-bridge 1; svc_on mqtt-bridge').returncode, 0)
        self.assertIn('MQTT_ENABLE=1', (self.c / 'mqtt.conf').read_text())       # created when missing
        self.assertNotEqual(self.sw('svc_switch ssh-server').returncode, 0)     # autostart file stays its switch

    def test_migration_keeps_what_the_camera_did(self):
        (self.c / 'boot.conf').write_text('TAMPER_DETECT=1\nTAMPER_HOLD_SEC=3\nTAMPER_LUMA_MIN=15\nX=1\n')
        (self.c / 'tamper.conf').write_text('ENABLE=0\nTAMPER_HOLD_SEC=6\n')
        (self.c / 'motion.conf').write_text('motion_trigger_led=true\nsend_telegram=true\n')
        (self.c / 'autostart' / 'recording').write_text('x')
        env = dict(MS_CONF_DIR=str(self.c), MS_SWITCH=str(ROOT / 'scripts/service-switch.sh'))
        r = sh('sh %s' % (ROOT / 'scripts/migrate-switches.sh'), env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('TELEGRAM_NOTIFY_ENABLE=1', (self.c / 'notify.conf').read_text())
        self.assertNotIn('send_telegram', (self.c / 'motion.conf').read_text())
        self.assertIn('ENABLE=0', (self.c / 'tamper.conf').read_text())         # both were needed: off
        boot = (self.c / 'boot.conf').read_text()
        self.assertNotIn('TAMPER_', boot)
        self.assertIn('REC_LOCAL=1', boot)
        self.assertFalse((self.c / 'autostart' / 'recording').exists())
        (self.c / 'boot.conf').write_text('TAMPER_DETECT=1\n')                  # once only
        sh('sh %s' % (ROOT / 'scripts/migrate-switches.sh'), env)
        self.assertEqual((self.c / 'boot.conf').read_text(), 'TAMPER_DETECT=1\n')

    def test_boot_and_services_page_use_the_key(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('for n in sound-detection syslog-forward memory-guard wifi-rescue telegram-bot whep; do', a)
        self.assertIn('svc_switch $n && continue', a)
        self.assertNotIn('autostart/recording', a)
        self.assertNotIn('[ "$PROFILE" = frigate_ha ] && case', a)
        s = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        self.assertIn('if svc_switch "$script"; then svc_set "$script" 0;', s)
        for gone in ('send_telegram', 'TELEGRAM_MOTION_SNAPSHOT'):
            self.assertNotIn(gone, (ROOT / 'scripts/detectionOn.sh').read_text() + (ROOT / 'scripts/motion-event.sh').read_text())

    def test_net_guard_waits_two_rescue_cycles(self):
        conf = self.d / 'boot.conf'
        conf.write_text('NET_GUARD_MIN=15\nWIFI_RESCUE_AFTER_MIN=10\nWIFI_RESCUE_MANUAL_MIN=15\n')
        env = dict(NG_BOOT_CONF=str(conf), NG_STATE=str(self.d / 'st'), NG_PERSIST=str(self.d / 'p'),
                   NG_UPTIME='100', NG_WR_PID=str(self.d / 'wr.pid'))
        ng = ROOT / 'scripts/net-guard.sh'
        self.assertIn('limit_s=900 ', sh('sh %s status' % ng, env).stdout)
        r = sh('sleep 5 & echo $! > %s; sh %s status' % (self.d / 'wr.pid', ng), env)
        self.assertIn('limit_s=3000 ', r.stdout)


class BootGuard(unittest.TestCase):
    """v3/linux66-sd/boot-guard: safe mode after 3 runs in a row shorter than 5 minutes (flash mode only)."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / 'cfg').mkdir()
        (self.d / 'flashmode').write_text('')
        (self.d / 'uptime').write_text('20.00 10.00\n')
        (self.d / 'persist.sh').write_text('echo "$CFG" >> %s\n' % (self.d / 'saves'))
        self.env = dict(BG_CFG=str(self.d / 'cfg'), BG_FLASHMODE=str(self.d / 'flashmode'),
                        BG_FLAG=str(self.d / 'safemode'), BG_MOTD=str(self.d / 'motd'),
                        BG_UPTIME=str(self.d / 'uptime'), BG_OK_S='3600', BG_NO_TIMER='1',
                        BG_PERSIST='sh %s' % (self.d / 'persist.sh'))

    def tearDown(self):
        shutil.rmtree(self.d)

    def bg(self, cmd):
        r = sh('sh %s %s' % (ROOT / 'v3/linux66-sd/boot-guard', cmd), self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def count(self):
        return (self.d / 'cfg' / '.boot-guard').read_text().strip()

    def saves(self):
        p = self.d / 'saves'
        return len(p.read_text().split()) if p.exists() else 0

    def test_three_short_runs_then_safe_mode_and_cap(self):
        for n in (1, 2, 3):
            self.bg('start')
            self.assertEqual(self.count(), str(n))
            self.assertFalse((self.d / 'safemode').exists(), n)
        self.bg('start')
        self.assertTrue((self.d / 'safemode').exists())
        self.assertIn('SAFE MODE', (self.d / 'motd').read_text())
        self.assertEqual((self.count(), self.saves()), ('4', 4))
        self.bg('start')            # a loop that goes on: count stays at 4, the flash is not written again
        self.assertEqual((self.count(), self.saves()), ('4', 4))
        self.assertTrue((self.d / 'safemode').exists())

    def test_ok_only_after_the_delay_and_clear(self):
        self.bg('start'); self.bg('start')
        self.bg('ok')               # uptime 20 s < 3600 s: nothing
        self.assertEqual(self.count(), '2')
        (self.d / 'uptime').write_text('3700.00 10.00\n')
        self.bg('ok')
        self.assertEqual((self.count(), self.saves()), ('0', 3))
        self.bg('ok')               # unchanged: no flash write
        self.assertEqual(self.saves(), 3)
        self.bg('start')
        self.bg('clear')
        self.assertEqual((self.count(), self.saves()), ('0', 5))

    def test_off_in_sd_mode_and_with_boot_guard_0(self):
        (self.d / 'cfg' / 'boot.conf').write_text('BOOT_GUARD=0\n')
        for _ in range(5):
            self.bg('start')
        self.assertFalse((self.d / 'safemode').exists())
        self.assertFalse((self.d / 'cfg' / '.boot-guard').exists())
        (self.d / 'cfg' / 'boot.conf').write_text('BOOT_GUARD=1\n')
        (self.d / 'flashmode').unlink()
        for _ in range(5):
            self.bg('start')
        self.assertFalse((self.d / 'safemode').exists())
        self.assertEqual(self.saves(), 0)

    def test_autorun_safe_mode_and_owner_reboots(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertLess(a.index('boot-guard start'), a.index('rtsp-launch.sh'))
        self.assertLess(a.index('reboot-tracker.sh boot'), a.index('boot-guard start'))
        for step in ('elif [ -x $TB/tc100_rtsp ]', '"$SAFE" = 0 ] && [ -f $CS/mqtt-bridge', '"$SAFE" = 0 ] && [ -f $CS/onvif',
                     'ssh-server|telnet-server|button-actions) ;;', '[ "$SAFE" = 1 ] && [ "$n" != wifi-rescue ]'):
            self.assertIn(step, a)
        rt = (ROOT / 'scripts/reboot-tracker.sh').read_text()
        self.assertIn('"web UI"*|"reset button"*)', rt)
        self.assertIn('LOGDIR=/mnt/config/log', rt)
        self.assertIn('\nBOOT_GUARD=1\n', (ROOT / 'config/boot.conf.dist').read_text())

    def test_reboot_tracker_flash_mode_dirs(self):
        (self.d / 'fm').write_text('')
        code = ('REBOOT_TRACKER_FLASHMODE=%s; . %s >/dev/null 2>&1; echo "$LOGDIR $HEARTBEAT $IMPORTANT $KEEP"'
                % (self.d / 'fm', ROOT / 'scripts/reboot-tracker.sh'))
        out = sh(code).stdout.split()
        self.assertEqual(out[0], '/mnt/config/log')
        self.assertFalse(out[1].startswith('/mnt/config'))
        self.assertFalse(out[2].startswith('/mnt/config'))
        self.assertEqual(out[3], '30')


if __name__ == '__main__':
    unittest.main()
