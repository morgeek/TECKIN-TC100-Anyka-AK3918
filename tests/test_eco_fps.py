"""Item 31: IDLE_WHEN chooses when the lower idle rate applies: still (motion detection, as before), unwatched (no RTSP
client playing, no live viewer), night (night mode); a recent event always gives the full rate."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class Wiring(unittest.TestCase):
    def test_server_condition(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('int ok = idle_when == IDLE_UNWATCHED ? np[0] + np[1] == 0 && live_count() == 0 :', src)
        self.assertIn('idle_when == IDLE_NIGHT ? idle_night : md_on;', src)
        self.assertIn('w = !strcmp(v, "unwatched") ? IDLE_UNWATCHED : !strcmp(v, "night") ? IDLE_NIGHT : IDLE_STILL;', src)
        self.assertIn('idle_night = bw;', src)

    def test_settings_and_command(self):
        self.assertIn('<select name="rtsp_idle_when" id="rtsp_idle_when"><option value="still">', text('www/settings.html'))
        s = text('scripts/action.d/stream.sh')
        self.assertIn('case "${F_rtsp_idle_when}" in unwatched|night) _rs_w="${F_rtsp_idle_when}" ;; *) _rs_w=still ;; esac', s)
        self.assertIn('"idle_when":"%s"', s)
        self.assertIn('IDLE_WHEN=still', text('config/boot.conf.dist'))


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class Rule(unittest.TestCase):
    def test_idle_fps_now(self):
        prog = '#include <stdio.h>\n#include "util.h"\nint main(void) {\n' \
               ' printf("%d %d %d %d %d\\n", idle_fps_now(15, 5, 10, 1, 0, 120, 100), idle_fps_now(15, 5, 10, 0, 0, 120, 100),' \
               ' idle_fps_now(15, 5, 10, 1, 0, 105, 100), idle_fps_now(15, 5, 10, 1, 1, 120, 100), idle_fps_now(15, 0, 10, 1, 0, 120, 100));\n' \
               ' return 0; }\n'
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'p.c').write_text(prog)
            subprocess.run(['gcc', '-I', str(ROOT / 'src/tc100rtsp'), '-o', str(Path(t, 'p')), str(Path(t, 'p.c')), '-lm'], check=True)
            out = subprocess.run([str(Path(t, 'p'))], capture_output=True, text=True).stdout.split()
        # condition holds & quiet: idle; condition false: full; recent event: full; continuous recording: full; off
        self.assertEqual(out, ['5', '15', '15', '15', '15'])


if __name__ == '__main__':
    unittest.main()
