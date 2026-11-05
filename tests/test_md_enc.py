"""Item 19: motion from the encoder's P frame sizes (tc100_rtsp md_enc_frame, RTSP_MD_ENC=1), compiled alone: calm
frames teach the mean, 3 frames in a row well above it are motion, keyframes and the off switches are ignored, the
sensitivity moves the threshold."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int md_on = 1, md_sens = 60, md_motion, priv_on;
static double md_tlast;
static void wfile(const char *f, const char *s, int n) { (void)f; (void)n; printf("REC %c\n", s[0]); }
@BLOCK@
static void run(const char *name, const uint32_t *sz, int n, int idr_at)
{
	md_enc_base = 0; md_enc_hits = 0; md_motion = 0;
	for (int i = 0; i < n; i++) md_enc_frame(sz[i], i == idr_at, i * 0.066);
	printf("%s motion=%d\n", name, md_motion);
}
int main(void)
{
	uint32_t calm[60], walk[60], blip[60], key[60];
	for (int i = 0; i < 60; i++) { calm[i] = 2000 + (i % 7) * 100; walk[i] = calm[i]; blip[i] = calm[i]; key[i] = calm[i]; }
	for (int i = 40; i < 46; i++) walk[i] = 20000;		/* someone walks in: P frames x10 */
	blip[40] = 20000; blip[41] = 20000;			/* two big frames only */
	key[40] = 60000;					/* a keyframe alone */
	md_enc_on = 1;
	run("calm", calm, 60, -1);
	run("walk", walk, 60, -1);
	run("blip", blip, 60, -1);
	run("key", key, 60, 40);
	for (int i = 40; i < 46; i++) walk[i] = 5000;		/* x2.3 */
	md_sens = 60; run("small60", walk, 60, -1);
	md_sens = 100; run("small100", walk, 60, -1);
	md_enc_on = 0; md_sens = 60; for (int i = 40; i < 46; i++) walk[i] = 20000; run("off", walk, 60, -1);
	md_enc_on = 1; md_on = 0; run("mdoff", walk, 60, -1);
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class MdEnc(unittest.TestCase):
    def test_detector(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        block = src[src.index('static int md_enc_on, md_enc_hits;'):src.index('/* ---- local recording (rec.c)')]
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'm.c').write_text(HARNESS.replace('@BLOCK@', block))
            subprocess.run(['gcc', '-Wall', '-o', str(Path(t, 'm')), str(Path(t, 'm.c'))], check=True)
            out = subprocess.run([str(Path(t, 'm'))], capture_output=True, text=True).stdout
        res = dict(re.findall(r'^(\w+) motion=(\d)', out, re.M))
        self.assertEqual(res, {'calm': '0', 'walk': '1', 'blip': '0', 'key': '0', 'small60': '0', 'small100': '1',
                               'off': '0', 'mdoff': '0'})

    def test_wiring(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('if (!k) md_enc_frame(len, idr, t_frame);', src)
        self.assertIn("md_enc_on = me && me[0] == '1';", src)


if __name__ == '__main__':
    unittest.main()
