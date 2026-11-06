"""Item 18: tc100_rtsp's automatic bit rate (RTSP_ABR=1). The regulation (abr_tick) is compiled alone with a fake
ak_venc_set_br: down 30 % on skipped frames, back up a tenth of the setting after 30 s calm, bounds, a client gone,
a refusal turning it off."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <stdio.h>
#define LOG(...) printf(__VA_ARGS__)
struct strm { void *enc; };
static struct strm S[2];
static int (*p_set_br)(void *, int);
static int refuse;
static int fake_br(void *h, int k) { (void)h; printf("SET %d\n", k); return refuse ? -1 : 0; }
@BLOCK@
int main(void)
{
	unsigned long seq[] = { 0, 0, 5, 5, 5, 5, 5, 5, 5, 5, 20, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
				2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2 };	/* 36 calm ticks: 1120 back to 2000 */
	unsigned i;

	abr_on = 1; abr_base = 2000; abr_min = 600; S[0].enc = (void *)1; p_set_br = fake_br;
	for (i = 0; i < sizeof seq / sizeof *seq; i++) { abr_tick(seq[i]); printf("CUR %d\n", abr_cur); }
	refuse = 1; abr_tick(100); printf("ON %d\n", abr_on);
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class Abr(unittest.TestCase):
    def test_regulation(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        block = src[src.index('static int abr_on, abr_cur'):src.index('/* RTSP_PROFILE=1: kernel (system) CPU time')]
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'a.c').write_text(HARNESS.replace('@BLOCK@', block))
            subprocess.run(['gcc', '-Wall', '-o', str(Path(t, 'a')), str(Path(t, 'a.c'))], check=True)
            out = subprocess.run([str(Path(t, 'a'))], capture_output=True, text=True).stdout
        cur = [int(x) for x in re.findall(r'^CUR (\d+)', out, re.M)]
        sets = [int(x) for x in re.findall(r'^SET (\d+)', out, re.M)]
        self.assertEqual(cur[:2], [2000, 2000])          # opened at the setting, nothing skipped
        self.assertEqual(cur[2], 1400)                   # 5 frames skipped: -30 %
        self.assertEqual(cur[3:8], [1400] * 5)           # calm, but not yet 30 s
        self.assertEqual(cur[8], 1600)                   # 6 calm ticks: + a tenth of the setting
        self.assertEqual(cur[10], 1120)                  # 15 more skipped: -30 %
        self.assertEqual(cur[11], 1120)                  # the count went down (a client left): not a skip
        self.assertEqual(max(cur), 2000)
        self.assertEqual(cur[-1], 2000)                  # back to the setting, never above
        self.assertTrue(all(600 <= c <= 2000 for c in cur))
        self.assertEqual(sets[0], 1400)
        self.assertIn('ON 0', out)                       # a refusal turns the regulation off
        self.assertIn('regulation off', out)

    def test_wiring(self):
        src = (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text(encoding='utf-8')
        self.assertIn('p_set_br = dlsym(m, "ak_venc_set_br");', src)
        self.assertIn("{ const char *ab = getenv(\"RTSP_ABR\"); abr_on = ab && ab[0] == '1'; }", src)
        # the regulation runs once per STAT line (every 5 s), right after it (the STAT line grew with the sender thread)
        stat = src.index('LOG("STAT cap %lu')
        self.assertIn('rec_active(), pp_us / 1000, sub_us / 1000', src[stat:stat + 600])
        self.assertLess(src.index('abr_tick(dr);', stat) - stat, 900)


if __name__ == '__main__':
    unittest.main()
