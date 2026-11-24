"""Item 19: motion from the encoder's P frame sizes (tc100_rtsp md_enc_frame, RTSP_MD_ENC=1), compiled alone: calm
frames teach the mean, 3 frames in a row well above it are motion, keyframes and the off switches are ignored, the
sensitivity moves the threshold. R1 (audit 2026-11-24): a bigger budget per picture (capture rate down, ABR step up,
a reopened encoder) starts the mean again with a warm-up that never triggers; a smaller one (idle -> full rate on
motion) scales the mean in CBR, keeps it in VBR, and keeps detecting the person who walked in."""
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
static void reset(void)
{
	md_enc_base = 0; md_enc_hits = 0; md_motion = 0; md_enc_warm = 0; md_enc_wend = 0; md_enc_bud = 0; md_tlast = -100;
}
static void run(const char *name, const uint32_t *sz, int n, int idr_at)
{
	reset();
	for (int i = 0; i < n; i++) md_enc_frame(sz[i], i == idr_at, i * 0.066);
	printf("%s motion=%d\n", name, md_motion);
}
/* n P frames from t0, dt apart, from size a to size b (linear), + a small wobble; returns the time after them */
static double feed(int n, double t0, double dt, uint32_t a, uint32_t b)
{
	for (int i = 0; i < n; i++) {
		uint32_t s = n > 1 ? a + (uint32_t)(((int64_t)b - a) * i / (n - 1)) : a;

		md_enc_frame(s + (uint32_t)(i % 5) * (s / 50), 0, t0 + i * dt);
	}
	return t0 + n * dt;
}
int main(void)
{
	uint32_t calm[60], walk[60], blip[60], key[60];
	double t, ts;

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

	/* 1. budget x6 in CBR (idle rate 25 -> 4 fps, 10 pictures a second here): the rate control takes ~8 pictures to
	 * fill it; 80 pictures at the new size; then someone walks in (x5 the new size). r = 0: nothing follows the
	 * budget (before R1): stuck. r = 1: md_enc_track */
	for (int r = 0; r < 2; r++) {
		int i, at_step = -1, motion_step;

		reset(); md_enc_track(2500, 1);
		t = feed(60, 0, 0.1, 2000, 2600);
		if (r) md_enc_track(15000, 1);
		for (i = 0; i < 80; i++) {
			md_enc_frame((uint32_t)(i < 8 ? 2000 + i * 1600 : 15000 + (i % 7) * 100), 0, t + i * 0.1);
			if (md_motion && at_step < 0) at_step = i;
		}
		motion_step = md_motion; md_motion = 0;
		feed(6, t + 8.0, 0.1, 80000, 80000);
		printf("%s motion=%d\n", r ? "step_restart" : "step_stuck", motion_step);
		printf("%s motion=%d\n", r ? "walk_after_restart" : "walk_stuck", md_motion);
		printf("%s first=%d\n", r ? "step_restart" : "step_stuck", at_step);
	}

	/* 2. IDLE_FPS in CBR: 5 fps, calm 10000; someone walks in (60000): motion, the rate goes to 25 fps (budget / 5).
	 * The rate control brings the walking pictures down to 12000 in 8 pictures; the walk goes on 2 s, then 2 s calm
	 * (2000), then a second walk. r = 1: md_enc_track (budget smaller: CBR scale + hold); r = 0: a restart (the first
	 * R1 version): the warm-up learnt the walk and missed the rest of it and the second one */
	for (int r = 0; r < 2; r++) {
		double t1, t2, t3;

		reset(); md_enc_track(40000, 1);
		t = feed(30, 0, 0.2, 10000, 10000);
		t = feed(6, t, 0.2, 60000, 60000);
		printf("%s first_walk=%d\n", r ? "idle_track" : "idle_restart", md_motion);
		ts = t;
		if (r) md_enc_track(8000, 1); else md_enc_restart();
		t = feed(8, t, 0.04, 60000, 12000);
		t1 = feed(50, t, 0.04, 12000, 12000);
		printf("%s through=%d base=%u\n", r ? "idle_track" : "idle_restart", md_tlast > t1 - 0.2, md_enc_base >> 4);
		t2 = feed(50, t1, 0.04, 2000, 2000);
		t3 = feed(6, t2, 0.04, 12000, 12000);
		printf("%s second=%d\n", r ? "idle_track" : "idle_restart", md_tlast >= t2);
		(void)ts; (void)t3;
	}

	/* 3. the same rate change on a calm scene (it came back to full rate for a viewer): the first pictures at the new
	 * rate keep the idle size (5 x the scaled mean): the hold keeps them from counting as motion */
	reset(); md_enc_track(40000, 1);
	t = feed(30, 0, 0.2, 10000, 10000);
	md_enc_track(8000, 1);
	t = feed(8, t, 0.04, 10000, 2000);
	t = feed(60, t, 0.04, 2000, 2000);
	printf("calm_up motion=%d base=%u\n", md_motion, md_enc_base >> 4);

	/* 4. VBR: a smaller budget leaves the mean as it is (a calm picture is under the ceiling) */
	reset(); md_enc_track(8000, 0);
	t = feed(60, 0, 0.1, 2000, 2000);
	{
		uint32_t b0 = md_enc_base;

		md_enc_track(3000, 0);
		t = feed(60, t, 0.04, 2000, 2000);
		printf("vbr_down kept=%d motion=%d\n", md_enc_base >> 4 >= (b0 >> 4) - 50 && md_enc_base >> 4 <= (b0 >> 4) + 50, md_motion);
	}

	/* 5. warm-up length: at least MD_ENC_WARM_N P frames and MD_ENC_WARM_S. At 1 fps the frames decide (6 s), at
	 * 25 fps the time (1.5 s) */
	reset(); md_enc_track(2000, 1);
	t = feed(20, 0, 1.0, 2000, 2000);
	md_enc_track(4000, 1);
	t = feed(1 + MD_ENC_WARM_N, t, 1.0, 2000, 2000);	/* the seed + the warm-up */
	t = feed(3, t, 1.0, 30000, 30000);
	printf("warm1fps motion=%d\n", md_motion);
	reset(); md_enc_track(2000, 1);
	t = feed(60, 0, 0.04, 2000, 2000);
	md_enc_track(4000, 1);
	t = feed(1 + MD_ENC_WARM_N, t, 0.04, 2000, 2000);
	ts = t;
	t = feed(6, t, 0.04, 2000, 2000);	/* still inside the 1.5 s */
	printf("warm25fps_early motion=%d\n", md_motion);
	t = feed(40, t, 0.04, 2000, 2000);
	t = feed(3, t, 0.04, 30000, 30000);
	printf("warm25fps_late motion=%d\n", md_motion);
	(void)ts;

	/* 6. motion inside a warm-up does not trigger */
	reset();
	feed(60, 0, 0.1, 2000, 2000);
	md_enc_restart();
	md_enc_frame(2000, 0, 6.0);
	feed(MD_ENC_WARM_N, 6.1, 0.1, 30000, 30000);
	printf("warm motion=%d\n", md_motion);
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class MdEnc(unittest.TestCase):
    def test_detector(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        block = src[src.index('#define MD_ENC_WARM_N'):src.index('/* ---- local recording (rec.c)')]
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'm.c').write_text(HARNESS.replace('@BLOCK@', block))
            subprocess.run(['gcc', '-Wall', '-o', str(Path(t, 'm')), str(Path(t, 'm.c'))], check=True)
            out = subprocess.run([str(Path(t, 'm'))], capture_output=True, text=True).stdout
        res = dict(re.findall(r'^(\w+) motion=(\d)', out, re.M))
        self.assertEqual(res, {'calm': '0', 'walk': '1', 'blip': '0', 'key': '0', 'small60': '0', 'small100': '1',
                               'off': '0', 'mdoff': '0',
                               # R1: without following the budget the bigger frames are "motion" for good; with
                               # it, none, and a real walk after the warm-up is still seen
                               'step_stuck': '1', 'walk_stuck': '1', 'step_restart': '0', 'walk_after_restart': '1',
                               'calm_up': '0', 'warm1fps': '1', 'warm25fps_early': '0', 'warm25fps_late': '1',
                               'warm': '0'}, out)
        self.assertIn('step_restart first=-1', out)
        self.assertRegex(out, r'step_stuck first=[0-9]')
        # idle -> full rate while someone walks: still detected through the change and again 2 s later; the mean
        # is not taught the walk (the first R1 version's restart was: it missed both)
        self.assertIn('idle_track first_walk=1', out)
        self.assertIn('idle_track through=1', out)
        self.assertIn('idle_track second=1', out)
        self.assertIn('idle_restart through=0', out)
        self.assertIn('idle_restart second=0', out)
        base = int(re.search(r'idle_track through=1 base=(\d+)', out).group(1))
        self.assertLess(base, 3000, out)                        # about the new calm size (2000), not the walk's
        self.assertRegex(out, r'calm_up motion=0 base=(1[5-9]\d\d|2[0-4]\d\d)\n')
        self.assertIn('vbr_down kept=1 motion=0', out)

    def test_wiring(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('if (!k) md_enc_frame(len, idr, t_frame);', src)
        self.assertIn("md_enc_on = me && me[0] == '1';", src)
        # R1: the main free encoder's budget per picture is followed at every picture (capture rate, ABR, reopen)
        self.assertIn('#define MD_ENC_WARM_N 6', src)
        self.assertIn('#define MD_ENC_WARM_S 1.5', src)
        self.assertIn('if (!k) md_enc_track((uint32_t)fe->rc.budget, !fe->rc.vbr);', src)
        self.assertEqual(src.count('md_enc_restart();'), 2)     # md_enc_budget (bigger) and the smart floor
        self.assertIn('if (was && !fe->still && !k && !moving) md_enc_restart();', src)
        self.assertNotIn('md_enc_restart', src[src.index('static void abr_tick('):src.index('static void abr_tick(') + 1500])


if __name__ == '__main__':
    unittest.main()
