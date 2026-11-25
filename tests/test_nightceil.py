"""NIGHT-CEIL (2026-11-25): tc100_rtsp's nightceil.csv, compiled alone with a fake clock and a fake main encoder.
A switch row 5 s after the start and after each black-and-white change (entered=start / switch), a sample row every
10 min of one mode (mean bit rate, min / max total gain), a stop row; rows wait in RAM and are appended at most once an
hour, at once after a switch row and at the stop; the file keeps its last rows; the directory follows memwatch.sh;
RTSP_NIGHTCEIL_LOG=0 writes nothing. Measurement only: no encoder or ISP call."""
from pathlib import Path
import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/tc100rtsp/tc100_rtsp.c'

HEAD = r'''
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "rc.h"
#define LOG(...) printf(__VA_ARGS__)
static time_t fake_now = 1000;
static time_t mono_t(void) { return fake_now; }
static int atoi_(const char *s) { return atoi(s); }
struct fe_enc { struct rc rc; int fps_now; };
struct strm { void *enc; };
static struct strm S[2];
static int free_enc = 1, bw_want, nr_now, sharp_now = 5, p_tune = 1, p_con = -3, cap_fps = 25;
static int cap_fps_now(void) { return cap_fps; }
'''

MAIN = r'''
static int lines(const char *f)
{
	FILE *p = fopen(f, "r");
	int n = 0, c;

	if (!p) return -1;
	while ((c = fgetc(p)) != EOF) n += c == '\n';
	fclose(p);
	return n;
}
static void ticks(int n, unsigned long bytes, int g0, int g1)	/* n STAT ticks of 5 s, AE reads in between */
{
	for (int i = 0; i < n; i++) {
		fake_now += 2; nc_ae_note(g0 + (g1 - g0) * i / (n > 1 ? n - 1 : 1), 40, 2812);
		fake_now += 3; nc_tick(5, 50, bytes);
	}
}
int main(int argc, char **argv)
{
	static struct fe_enc fe;
	char f[300];
	const char *d;
	int sd;

	(void)argc;
	snprintf(f, sizeof f, "%s/nightceil.csv", argv[1]);
	rc_init(&fe.rc, 2000, 25, 22, 48, 30);
	rc_set_vbr(&fe.rc, 1); rc_set_vbr_qp(&fe.rc, 33); fe.fps_now = 25;
	S[0].enc = &fe;
	ticks(3, 1000, 1, 1);
	printf("before_start lines=%d\n", lines(f));		/* no frame yet: nothing */
	nc_mark(0);						/* the first picture: the start, by day */
	nc_ae_note(2, 120, 900);
	ticks(1, 1000000, 2, 2);				/* 5 s: the switch row (start), written at once */
	printf("start lines=%d\n", lines(f));
	ticks(119, 1000000, 2, 6);				/* 10 min with the start row: a sample row, kept in RAM */
	printf("sample lines=%d\n", lines(f));
	bw_want = 1; cap_fps = 10; fe.fps_now = 10; rc_set_rate(&fe.rc, 0, 10);
	nc_mark(1);						/* the evening switch of a running server */
	ticks(1, 1000000, 26, 26);
	printf("switch lines=%d\n", lines(f));			/* the switch row and the waiting sample row */
	ticks(119, 1000000, 20, 30);				/* the rest of the first 10 min of night: a sample */
	printf("night_sample lines=%d\n", lines(f));
	ticks(601, 1000000, 26, 26);				/* 50 min more: an hour since the last append */
	printf("hour lines=%d\n", lines(f));
	ticks(719, 500000, 26, 26);				/* windows end on the hour again */
	ticks(120 * 60, 500000, 26, 26);			/* 10 h: 60 sample rows (the cap) */
	ticks(20, 500000, 26, 26);				/* 100 s into a window */
	nc_stop();
	printf("stop lines=%d\n", lines(f));
	setenv("RTSP_NIGHTCEIL_DIR", "", 1);
	setenv("RTSP_NIGHTCEIL_MOUNTS", argv[2], 1);
	d = nc_dir(&sd); printf("dir_rw %s %d\n", d, sd);
	setenv("RTSP_NIGHTCEIL_MOUNTS", argv[3], 1);
	d = nc_dir(&sd); printf("dir_ro %s %d\n", d, sd);
	setenv("RTSP_NIGHTCEIL_MOUNTS", "/nonexistent", 1);
	d = nc_dir(&sd); printf("dir_none %s %d\n", d, sd);
	return 0;
}
'''


def block(src):
    return src[src.index('/* ---- NIGHT-CEIL (2026-11-25)'):src.index('/* Smart mode of the free encoder')]


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class NightCeilLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        (t / 'n.c').write_text(HEAD + block(SRC.read_text(encoding='utf-8')) + MAIN)
        subprocess.run(['gcc', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-parameter', '-I', str(ROOT / 'src/h265enc'),
                        '-o', str(t / 'n'), str(t / 'n.c')], check=True)
        (t / 'mounts_rw').write_text('/dev/root / squashfs ro 0 0\n/dev/mmcblk0p1 /mnt/sd vfat rw,relatime,fmask=0022 0 0\n')
        (t / 'mounts_ro').write_text('/dev/mmcblk0p1 /mnt/sd vfat ro,relatime 0 0\ntmpfs /mnt/log tmpfs rw 0 0\n')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_harness(self, rows='30', log=None):
        t = Path(self.tmp.name)
        d = Path(tempfile.mkdtemp(dir=t))
        env = dict(os.environ, RTSP_NIGHTCEIL_DIR=str(d / 'logs'), RTSP_NIGHTCEIL_ROWS=rows)
        if log is not None:
            env['RTSP_NIGHTCEIL_LOG'] = log
        out = subprocess.run([str(t / 'n'), str(d / 'logs'), str(t / 'mounts_rw'), str(t / 'mounts_ro')], env=env,
                             capture_output=True, text=True, check=True).stdout
        f = d / 'logs' / 'nightceil.csv'
        return out, (f.read_text() if f.exists() else None)

    def test_rows_buffering_and_columns(self):
        out, text = self.run_harness(rows='2016')
        counts = dict(re.findall(r'^(\w+) lines=(-?\d+)', out, re.M))
        self.assertEqual(counts['before_start'], '-1', out)       # no picture yet: no file
        self.assertEqual(counts['start'], '2', out)               # header + the start row, at once
        self.assertEqual(counts['sample'], '2', out)              # the sample row waits in RAM
        self.assertEqual(counts['switch'], '4', out)              # a switch row appends at once (with the waiting one)
        self.assertEqual(counts['night_sample'], '4', out)
        self.assertEqual(counts['hour'], '10', out)               # an hour after the last append: 6 samples more
        rows = list(csv.DictReader(io.StringIO(text)))
        hdr = text.splitlines()[0].split(',')
        self.assertEqual(hdr, ['timestamp', 'uptime_s', 'kind', 'bw', 'entered', 'gain', 'gain_min', 'gain_max', 'exp_lines',
                               'lumi', 'nr', 'sharp', 'contrast', 'nr3d', 'nr3d_overflow', 'cap_fps', 'fps_now', 'budget',
                               'vbr', 'vbr_qp', 'kbps_set', 'window_s', 'main_frames', 'main_bytes', 'main_kbps'])
        for line in text.splitlines()[1:]:
            self.assertEqual(len(line.split(',')), len(hdr), line)
        start, s1, sw, s2 = rows[0], rows[1], rows[2], rows[3]
        self.assertEqual((start['kind'], start['entered'], start['bw']), ('switch', 'start', '0'))
        self.assertEqual((start['window_s'], start['main_bytes'], start['main_kbps']), ('5', '1000000', '1600'))
        self.assertEqual((start['gain'], start['exp_lines'], start['lumi']), ('2', '2812', '40'))
        self.assertEqual((start['nr'], start['sharp'], start['contrast'], start['cap_fps']), ('0', '5', '-3', '25'))
        self.assertEqual((start['fps_now'], start['budget'], start['vbr'], start['vbr_qp'], start['kbps_set']),
                         ('25', '10000', '1', '33', '2000'))
        self.assertEqual((s1['kind'], s1['entered'], s1['window_s'], s1['main_kbps']), ('sample', 'start', '600', '1600'))
        self.assertEqual((s1['gain_min'], s1['gain_max']), ('2', '6'))      # over the 10 min
        self.assertEqual((sw['kind'], sw['entered'], sw['bw'], sw['gain']), ('switch', 'switch', '1', '26'))
        self.assertEqual((sw['cap_fps'], sw['fps_now'], sw['budget']), ('10', '10', '25000'))
        self.assertEqual((s2['kind'], s2['entered'], s2['bw'], s2['gain_min'], s2['gain_max']), ('sample', 'switch', '1', '20', '30'))
        self.assertEqual(int(sw['uptime_s']) - int(s1['uptime_s']), 5)    # the window started again at the switch
        self.assertEqual(int(s2['uptime_s']) - int(sw['uptime_s']), 595)
        self.assertEqual(rows[-1]['kind'], 'stop')
        self.assertEqual((rows[-1]['window_s'], rows[-1]['main_kbps']), ('100', '800'))
        for r in rows:
            self.assertTrue(r['timestamp'].isdigit() and r['uptime_s'].isdigit(), r)

    def test_cap_keeps_the_header_and_the_last_rows(self):
        out, text = self.run_harness(rows='30')
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith('timestamp,uptime_s,kind,'))
        self.assertEqual(sum(1 for ln in lines if ln.startswith('timestamp')), 1)
        self.assertLessEqual(len(lines) - 1, 30 + 25)
        self.assertGreaterEqual(len(lines) - 1, 30)
        self.assertTrue(lines[-1].split(',')[2] == 'stop')
        ups = [int(ln.split(',')[1]) for ln in lines[1:]]
        self.assertEqual(ups, sorted(ups))                         # the oldest went, in order
        full, _ = self.run_harness(rows='2016')
        self.assertIn('stop lines=', full)

    def test_switched_off(self):
        out, text = self.run_harness(log='0')
        self.assertIsNone(text)
        self.assertIn('stop lines=-1', out)

    def test_directory_follows_memwatch(self):
        out, _ = self.run_harness()
        self.assertIn('dir_rw /mnt/sd/logs 1', out)
        self.assertIn('dir_ro /mnt/log 0', out)
        self.assertIn('dir_none /mnt/log 0', out)


class NightCeilWiring(unittest.TestCase):
    def test_hooks(self):
        src = SRC.read_text(encoding='utf-8')
        self.assertIn('style_switch(bw); nc_mark(1); }', src)                          # every black-and-white change
        self.assertIn('if (nc_first) { nc_first = 0; nc_mark(0); }', src)                # the start
        stat = src.index('LOG("STAT cap %lu')
        self.assertIn('nc_tick((long)(tn.tv_sec - tl.tv_sec), S[0].nfr, S[0].nbytes);', src[stat:stat + 1400])
        self.assertIn('nc_ae_note(ae_gain(&r), r.lumi, r.exp_time);', src)
        self.assertLess(src.index('nc_stop();'), src.index('return exit_code;\n}'))
        # the same total gain as low light
        self.assertIn('g = ae_gain(r);', src)
        self.assertIn('return (int)(((long long)r->isp_d_gain * (((long long)r->a_gain * r->d_gain) >> 8)) >> 16);', src)
        # measurement only: the block calls no encoder or ISP setter
        b = block(src)
        for call in ('ioctl(', 'p_set_br', 'fe_set_', 'rc_set_', 'md_enc_'):
            self.assertNotIn(call, b[:b.index('/* ---- NIGHT-CEIL, the night setting') if '/* ---- NIGHT-CEIL, the night setting' in b else len(b)])
        self.assertIn('nc_on = !(e && e[0] == \'0\')', b)                                 # on unless RTSP_NIGHTCEIL_LOG=0


if __name__ == '__main__':
    unittest.main()
