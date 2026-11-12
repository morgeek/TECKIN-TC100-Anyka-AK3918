"""DENOISE curve stretch (tc100_rtsp.c nr_stretch), compiled on the host from the source.

Properties checked for every step -50..50 on the tuning file's real curves (day iso16 NR2, NR1 and a flat one):
identity at 0, first and last points kept, decreasing curves stay decreasing, values within the original range,
and the curve gets wider (more smoothing) for a positive step, narrower for a negative one.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

MAIN = r"""
#include <stdio.h>
#include <stdlib.h>
static const unsigned short curves[][17] = {
	{1023, 972, 834, 645, 451, 284, 162, 83, 38, 16, 6, 2, 0, 0, 0, 0, 0},	/* day iso16 NR2 */
	{1023, 940, 727, 475, 261, 121, 47, 15, 4, 1, 0, 0, 0, 0, 0, 0, 0},	/* day iso8 NR2 */
	{1023, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},			/* most sets: off beyond 0 */
	{1023, 1000, 900, 800, 700, 600, 500, 400, 300, 200, 100, 50, 40, 30, 20, 10, 5},
};
int main(void)
{
	unsigned short d[17];
	int c, p, i, bad = 0;

	for (c = 0; c < 4; c++)
		for (p = -50; p <= 50; p++) {
			long area = 0, area0 = 0;

			nr_stretch(d, curves[c], 100 + 2 * p);
			for (i = 0; i < 17; i++) {
				area += d[i]; area0 += curves[c][i];
				if (p == 0 && d[i] != curves[c][i]) { printf("identity c%d i%d\n", c, i); bad = 1; }
				if (d[i] > 1023 || (i && d[i] > d[i - 1])) { printf("monotone c%d p%d i%d\n", c, p, i); bad = 1; }
			}
			if (d[0] != curves[c][0] || d[16] != curves[c][16]) { printf("ends c%d p%d\n", c, p); bad = 1; }
			if ((p > 0 && area < area0) || (p < 0 && area > area0)) { printf("direction c%d p%d\n", c, p); bad = 1; }
		}
	puts(bad ? "FAIL" : "OK");
	return bad;
}
"""


@unittest.skipUnless(shutil.which("gcc"), "needs gcc")
class NrStretch(unittest.TestCase):
    def test_properties(self):
        src = (ROOT / "src/tc100rtsp/tc100_rtsp.c").read_text(encoding="utf-8")
        fn = re.search(r"static void nr_stretch\(.*?\n\}\n", src, re.S).group(0)
        with tempfile.TemporaryDirectory() as t:
            c = Path(t) / "t.c"
            c.write_text(fn + MAIN)
            flags = ["-O1", "-Wall", "-Werror", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
            r = subprocess.run(["gcc", *flags, "-o", str(Path(t) / "t"), str(c)], capture_output=True, text=True)
            if r.returncode:     # a host without the sanitizer runtimes: plain build
                r = subprocess.run(["gcc", "-O1", "-Wall", "-Werror", "-o", str(Path(t) / "t"), str(c)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = subprocess.run([str(Path(t) / "t")], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("OK", out.stdout)


if __name__ == "__main__":
    unittest.main()
