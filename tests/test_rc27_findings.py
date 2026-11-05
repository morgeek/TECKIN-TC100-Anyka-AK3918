"""rc27 tester findings: every service script answers restart (R5: it did nothing for 15 of them, e.g. telegram-bot
after a new token), and RTSP_PACING_US has no default (R2: HZ=100, usleep(100) sleeps 10 ms in the main loop)."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


class ServiceRestart(unittest.TestCase):
    def test_every_control_script_restarts(self):
        bad = []
        for p in sorted((ROOT / 'controlscripts').iterdir()):
            s = p.read_text(encoding='utf-8')
            inline = re.search(r'^\s*restart\)', s, re.M)
            listed = re.search(r'^\s*(?:case [^\n]*in )?[a-z|]*\brestart\b[a-z|]*\)', s, re.M)
            func = re.search(r'^restart\s*\(\)', s, re.M)
            if not (inline or (listed and func)):
                bad.append(p.name)
        self.assertEqual(bad, [])

    def test_restart_stops_then_starts(self):
        src = (ROOT / 'controlscripts/telegram-bot').read_text(encoding='utf-8')
        disp = src[src.index('restart() {'):]
        with tempfile.TemporaryDirectory() as t:
            log = Path(t, 'log')
            code = 'start() { echo start >> %s; }\nstop() { echo stop >> %s; }\nstatus() { :; }\nhealth() { :; }\nset -- restart\n%s' % (
                log.as_posix(), log.as_posix(), disp)
            subprocess.run(SH + ['-c', code], check=True)
            self.assertEqual(log.read_text().split(), ['stop', 'start'])


class OnvifAdvertisedStream(unittest.TestCase):
    """R6: controlscripts/onvif advertises the frame rate and size tc100_rtsp really sends"""

    def run_block(self, fps0, mainres, scale):
        s = (ROOT / 'controlscripts/onvif').read_text(encoding='utf-8')
        a = s.index('    set -- $(/mnt/bin/rwconf')
        b = s.index('    CODECSTR0=', a)
        with tempfile.TemporaryDirectory() as t:
            param = Path(t, 'main_scale')
            if scale:
                param.write_text('1')
            code = ('rwconf_out() { echo "1920 1080 2 %s 1600 640 360 0 %s 250 554 %s"; }\n' % (fps0, fps0, mainres)
                    + s[a:b].replace('$(/mnt/bin/rwconf', '$(rwconf_out #') + 'echo "$WIDTH0 $HEIGHT0 $FPS0 $FPS1"\n')
            r = subprocess.run(SH + ['-c', code], capture_output=True, text=True,
                               env={'TC100_VI_SCALE_PARAM': param.as_posix(), 'PATH': '/usr/bin:/bin'})
            return r.stdout.split()

    def test_fps_and_size(self):
        self.assertEqual(self.run_block(25, 1080, True), ['1920', '1080', '25', '25'])
        self.assertEqual(self.run_block(16, 1080, True), ['1920', '1080', '15', '15'])
        self.assertEqual(self.run_block(20, 720, True), ['1280', '720', '20', '20'])
        self.assertEqual(self.run_block(20, 720, False), ['1920', '1080', '20', '20'])


class PacingDefault(unittest.TestCase):
    def test_no_pacing_default(self):
        s = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text(encoding='utf-8')
        self.assertNotIn('export RTSP_PACING_US=', s)


if __name__ == '__main__':
    unittest.main()
