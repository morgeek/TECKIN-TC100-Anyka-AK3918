"""Item 19: motion from the encoder's P frame sizes (tc100_rtsp md_enc_frame, RTSP_MD_ENC=1), compiled alone: calm
frames teach the mean, 3 frames in a row well above it are motion, keyframes and the off switches are ignored, the
sensitivity moves the threshold. R1 (audit 2026-11-24): after a new budget per picture (capture rate, ABR step, a new
main encoder) the mean starts again and its warm-up never triggers."""
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
	md_on = 1;
	/* R1: 60 calm frames, then the budget per picture x6 (CBR, idle rate 25 -> 4 fps): the rate control takes
	 * ~8 pictures to fill it; 80 frames at the new size; then someone walks in (x5 the new size) */
	for (int r = 0; r < 2; r++) {
		int i, at_step = -1, motion_step = 0;

		md_enc_base = 0; md_enc_hits = 0; md_motion = 0; md_enc_warm = 0;
		for (i = 0; i < 60; i++) md_enc_frame(2000 + (i % 7) * 100, 0, i * 0.1);
		if (r) md_enc_restart();	/* what the capture rate / ABR hook does; r = 0: no restart (before R1) */
		for (i = 0; i < 80; i++) {
			uint32_t sz = (uint32_t)(i < 8 ? 2000 + i * 1600 : 15000 + (i % 7) * 100);

			md_enc_frame(sz, 0, 6.0 + i * 0.1);
			if (md_motion && at_step < 0) at_step = i;
		}
		motion_step = md_motion; md_motion = 0;
		for (i = 0; i < 6; i++) md_enc_frame(80000, 0, 14.0 + i * 0.1);
		printf("%s motion=%d\n", r ? "step_restart" : "step_stuck", motion_step);
		printf("%s motion=%d\n", r ? "walk_after_restart" : "walk_stuck", md_motion);
		printf("%s first=%d\n", r ? "step_restart" : "step_stuck", at_step);
	}
	/* a restart in the middle of motion: the warm-up frames are not motion, the mean then keeps learning calm ones */
	md_enc_base = 0; md_enc_hits = 0; md_motion = 0; md_enc_warm = 0;
	for (int i = 0; i < 60; i++) md_enc_frame(2000, 0, i * 0.1);
	md_enc_restart();
	for (int i = 0; i < MD_ENC_WARM; i++) md_enc_frame(i == 0 ? 2000 : 30000, 0, 6.0 + i * 0.1);
	printf("warm motion=%d\n", md_motion);
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class MdEnc(unittest.TestCase):
    def test_detector(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        block = src[src.index('#define MD_ENC_WARM'):src.index('/* ---- local recording (rec.c)')]
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'm.c').write_text(HARNESS.replace('@BLOCK@', block))
            subprocess.run(['gcc', '-Wall', '-o', str(Path(t, 'm')), str(Path(t, 'm.c'))], check=True)
            out = subprocess.run([str(Path(t, 'm'))], capture_output=True, text=True).stdout
        res = dict(re.findall(r'^(\w+) motion=(\d)', out, re.M))
        self.assertEqual(res, {'calm': '0', 'walk': '1', 'blip': '0', 'key': '0', 'small60': '0', 'small100': '1',
                               'off': '0', 'mdoff': '0',
                               # R1: without the restart the bigger frames are "motion" for good; with it, none,
                               # and a real walk after the warm-up is still seen
                               'step_stuck': '1', 'walk_stuck': '1', 'step_restart': '0', 'walk_after_restart': '1',
                               'warm': '0'}, out)
        self.assertIn('step_restart first=-1', out)
        self.assertRegex(out, r'step_stuck first=[0-9]')

    def test_wiring(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('if (!k) md_enc_frame(len, idr, t_frame);', src)
        self.assertIn("md_enc_on = me && me[0] == '1';", src)
        # R1: the mean starts again on a new capture rate of the main free encoder, an ABR step and a main (re)open
        self.assertIn('#define MD_ENC_WARM 16', src)
        rate = src[src.index('if (fe->fps_now != was_fps) {'):][:400]
        self.assertIn('if (!k) md_enc_restart();', rate)
        self.assertIn('if (r == 0) { abr_cur = want; md_enc_restart(); }', src)
        self.assertIn('if (s == &S[0]) { enc_gen++; md_enc_restart(); }', src)
        self.assertIn('if (was && !fe->still && !k && !moving) md_enc_restart();', src)


if __name__ == '__main__':
    unittest.main()
