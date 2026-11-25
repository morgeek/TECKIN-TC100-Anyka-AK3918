"""NIGHT-CEIL (2026-11-25): tc100_rtsp's nightceil.csv, compiled alone with a fake clock and a fake main encoder.
A switch row 5 s after the start and after each black-and-white change (entered=start / switch), a sample row every
10 min of one mode (mean bit rate, min / max total gain), a stop row; rows wait in RAM and are appended at most once an
hour, at once after a switch row and at the stop; the file keeps its last rows; the directory follows memwatch.sh;
RTSP_NIGHTCEIL_LOG=0 writes nothing. Measurement only: no encoder or ISP call.
The night setting (RTSP_NIGHT_VBR_QP_ADD, RTSP_NIGHT_KBPS, night_enc_sync) with abr_tick and a fake encoder: the night
QP and the night ceiling applied at night, again on a new encoder, restored by day; the ceiling and ABR give the lower
of the two; with both keys at 0 the run is the same, call for call, as one without night_enc_sync."""
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
static int (*p_set_br)(void *, int);
static int n_sets, n_qps, n_restarts;
static void md_enc_restart(void) { n_restarts++; printf("MDRESTART\n"); }
static void fe_set_vbr_qp(struct fe_enc *e, int qp) { rc_set_vbr_qp(&e->rc, qp); n_qps++; printf("QPSET %d\n", e->rc.vbr_qp); }
static int fake_br(void *h, int k) { struct fe_enc *e = h; rc_set_rate(&e->rc, k, 0); n_sets++; printf("SET %d\n", k); return 0; }
'''

NIGHT_MAIN = r'''
static struct fe_enc fe0, fe1;
static int use_sync = 1;
static void open_enc(struct fe_enc *e, int vbr)
{
	memset(e, 0, sizeof *e);
	rc_init(&e->rc, 2000, 25, 22, 48, 30);	/* -b 2000, 25 fps */
	rc_set_vbr(&e->rc, vbr); if (vbr) rc_set_vbr_qp(&e->rc, 33);
	e->fps_now = 25;
	S[0].enc = e; enc_gen++;
}
static void fps(int f) { struct fe_enc *e = S[0].enc; rc_set_rate(&e->rc, 0, f); e->fps_now = f; }
static void sync_(void) { if (use_sync) night_enc_sync(); }
static void step(const char *name)
{
	struct fe_enc *e = S[0].enc;

	printf("STEP %s qp=%d kbps=%d budget=%ld abr=%d cap=%d sets=%d qps=%d restarts=%d\n", name, e->rc.vbr_qp, e->rc.kbps,
	       (long)e->rc.budget, abr_cur, night_kbps_now, n_sets, n_qps, n_restarts);
}
int main(int argc, char **argv)
{
	int vbr = argc > 2 ? atoi(argv[2]) : 1;

	use_sync = argc > 1 ? atoi(argv[1]) : 1;
	p_set_br = fake_br; abr_on = 1; abr_base = 2000; abr_min = 500;
	open_enc(&fe0, vbr);
	sync_(); step("day0");
	abr_tick(0); sync_(); step("abr_sync");
	bw_want = 1; fps(10); sync_(); step("night");
	sync_(); sync_(); step("night_again");
	abr_tick(5); sync_(); step("abr_down");
	for (int i = 0; i < 6; i++) { abr_tick(5); sync_(); }
	step("abr_up");
	open_enc(&fe1, vbr); fps(10); sync_(); step("reopen");
	abr_tick(5); sync_(); step("abr_resync");
	abr_tick(9); sync_(); step("abr_down2");
	bw_want = 0; fps(25); sync_(); step("day");
	sync_(); step("day_again");
	bw_want = 1; fps(10); sync_(); step("night2");
	bw_want = 0; fps(25); sync_(); step("day2");
	return 0;
}
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


def abr_block(src):
    return src[src.index('static int abr_on, abr_cur'):src.index('/* RTSP_PROFILE=1: kernel (system) CPU time')]


def build(t, name, main):
    src = SRC.read_text(encoding='utf-8')
    (t / (name + '.c')).write_text(HEAD + abr_block(src) + block(src) + main)
    subprocess.run(['gcc', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-unused-variable',
                    '-I', str(ROOT / 'src/h265enc'), '-o', str(t / name), str(t / (name + '.c'))], check=True)


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class NightCeilLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        build(t, 'n', MAIN)
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
                               'vbr', 'vbr_qp', 'kbps_set', 'night_qp_add', 'night_kbps', 'window_s', 'main_frames',
                               'main_bytes', 'main_kbps'])
        for line in text.splitlines()[1:]:
            self.assertEqual(len(line.split(',')), len(hdr), line)
        start, s1, sw, s2 = rows[0], rows[1], rows[2], rows[3]
        self.assertEqual((start['kind'], start['entered'], start['bw']), ('switch', 'start', '0'))
        self.assertEqual((start['window_s'], start['main_bytes'], start['main_kbps']), ('5', '1000000', '1600'))
        self.assertEqual((start['gain'], start['exp_lines'], start['lumi']), ('2', '2812', '40'))
        self.assertEqual((start['nr'], start['sharp'], start['contrast'], start['cap_fps']), ('0', '5', '-3', '25'))
        self.assertEqual((start['fps_now'], start['budget'], start['vbr'], start['vbr_qp'], start['kbps_set']),
                         ('25', '10000', '1', '33', '2000'))
        self.assertEqual((start['night_qp_add'], start['night_kbps']), ('0', '0'))     # no night setting in force
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


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class NightSetting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        build(Path(cls.tmp.name), 's', NIGHT_MAIN)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_s(self, qp=None, kbps=None, sync='1', vbr='1'):
        env = {k: v for k, v in os.environ.items() if not k.startswith('RTSP_NIGHT')}
        if qp is not None:
            env['RTSP_NIGHT_VBR_QP_ADD'] = qp
        if kbps is not None:
            env['RTSP_NIGHT_KBPS'] = kbps
        out = subprocess.run([str(Path(self.tmp.name) / 's'), sync, vbr], env=env, capture_output=True, text=True,
                             check=True).stdout
        steps = {}
        for name, rest in re.findall(r'^STEP (\w+) (.*)$', out, re.M):
            steps[name] = {a: int(b) for a, b in (kv.split('=') for kv in rest.split())}
        return out, steps

    def test_both_keys_at_0_change_nothing(self):
        ref, _ = self.run_s(sync='0')                     # night_enc_sync never called: today's behaviour
        for qp, kbps in ((None, None), ('0', '0'), ('0', None), (None, '0'), ('-2', '-5')):
            out, st = self.run_s(qp, kbps)
            self.assertEqual(out, ref, (qp, kbps))       # call for call, log line for log line
            self.assertNotIn('night setting', out)
            self.assertNotIn('MDRESTART', out)
            self.assertNotIn('QPSET', out)
            self.assertEqual(st['night']['qp'], 33)
            self.assertEqual(st['night']['budget'], 2000 * 125 // 10)   # R1 alone: 25000 bytes at 10 fps
        out, _ = self.run_s('0', '0', vbr='0')
        self.assertEqual(out, self.run_s(sync='0', vbr='0')[0])

    def test_night_qp_applied_at_night_and_restored_by_day(self):
        out, st = self.run_s(qp='3')
        self.assertEqual(st['day0']['qp'], 33)
        self.assertEqual(st['night']['qp'], 36)
        self.assertEqual(st['night']['restarts'], 1)                 # md_enc_restart at the change
        self.assertEqual(st['night_again']['qps'], st['night']['qps'])   # nothing more while the mode stays
        self.assertEqual(st['reopen']['qp'], 36)                     # a new encoder at night gets it too
        self.assertEqual(st['reopen']['restarts'], 2)
        self.assertEqual(st['day']['qp'], 33)                        # the configured value by day
        self.assertEqual(st['day']['restarts'], 3)
        self.assertEqual(st['day_again']['qps'], st['day']['qps'])
        self.assertEqual((st['night2']['qp'], st['day2']['qp']), (36, 33))
        self.assertEqual(st['day2']['sets'], self.run_s(sync='0')[1]['day2']['sets'])   # only ABR's rate calls ...
        self.assertEqual(st['abr_down']['kbps'], 1400)               # ... ABR as before
        self.assertIn('night setting (night): VBR quality QP 33 -> 36 (RTSP_NIGHT_VBR_QP_ADD=3)', out)
        self.assertIn('night setting (night, new main encoder): VBR quality QP 33 -> 36', out)
        self.assertIn('night setting (day): VBR quality QP 36 -> 33', out)
        _, big = self.run_s(qp='99')                                  # clamped to 6
        self.assertEqual(big['night']['qp'], 39)
        out, cbr = self.run_s(qp='3', vbr='0')                       # CBR: the quality QP is not used
        self.assertIn('VBR quality QP unchanged (CBR)', out)
        self.assertEqual(cbr['night']['qps'], 0)
        self.assertEqual(cbr['night']['restarts'], 0)

    def test_night_ceiling_applied_and_restored_with_abr(self):
        out, st = self.run_s(kbps='900')
        self.assertEqual((st['day0']['kbps'], st['day0']['cap']), (2000, 0))
        self.assertEqual((st['night']['kbps'], st['night']['cap']), (900, 900))
        self.assertEqual(st['night']['budget'], 900 * 125 // 10)       # R1: the ceiling over the 10 fps in use
        self.assertEqual(st['night']['restarts'], 1)
        self.assertEqual(st['night']['qp'], 33)                        # no QP change without RTSP_NIGHT_VBR_QP_ADD
        self.assertEqual(st['night_again']['sets'], st['night']['sets'])
        self.assertEqual((st['abr_down']['abr'], st['abr_down']['kbps']), (1400, 900))   # ABR above the ceiling: ceiling
        self.assertEqual((st['abr_up']['abr'], st['abr_up']['kbps']), (1600, 900))
        self.assertEqual((st['reopen']['kbps'], st['reopen']['cap']), (900, 900))        # a new encoder gets it too
        self.assertEqual((st['abr_resync']['abr'], st['abr_resync']['kbps']), (2000, 900))
        self.assertEqual(st['abr_down2']['kbps'], 900)
        self.assertEqual((st['day']['kbps'], st['day']['cap']), (1400, 0))   # by day: ABR's rate again
        self.assertEqual(st['day']['budget'], 1400 * 125 // 25)
        self.assertEqual(st['day_again']['sets'], st['day']['sets'])
        self.assertEqual((st['night2']['kbps'], st['day2']['kbps']), (900, 1400))
        self.assertIn('night setting (night): main bit rate 2000 -> 900 kbit/s', out)
        self.assertIn('night setting (day): main bit rate 900 -> 1400 kbit/s', out)
        self.assertIn('the night ceiling (RTSP_NIGHT_KBPS) keeps the encoder at 900 kbit/s', out)
        # a ceiling above ABR's rate: ABR's step down still acts, a step up stops at the ceiling
        _, hi = self.run_s(kbps='1500')
        self.assertEqual(hi['night']['kbps'], 1500)
        self.assertEqual(hi['abr_down']['kbps'], 1400)
        self.assertEqual(hi['abr_up']['kbps'], 1500)
        self.assertEqual(hi['day']['kbps'], 1400)
        # above the configured rate: nothing to do
        out, over = self.run_s(kbps='5000')
        self.assertNotIn('night setting', out)
        self.assertEqual(over['night']['kbps'], 2000)
        # both keys
        _, both = self.run_s(qp='2', kbps='900')
        self.assertEqual((both['night']['qp'], both['night']['kbps'], both['night']['restarts']), (35, 900, 1))
        self.assertEqual((both['day']['qp'], both['day']['kbps']), (33, 1400))


class NightCeilWiring(unittest.TestCase):
    def test_hooks(self):
        src = SRC.read_text(encoding='utf-8')
        self.assertIn('style_switch(bw); nc_mark(1); }', src)                          # every black-and-white change
        self.assertIn('if (nc_first) { nc_first = 0; nc_mark(0); }', src)                # the start
        stat = src.index('LOG("STAT cap %lu')
        self.assertIn('nc_tick((long)(tn.tv_sec - tl.tv_sec), S[0].nfr, S[0].nbytes);', src[stat:stat + 1400])
        self.assertIn('nc_ae_note(ae_gain(&r), r.lumi, r.exp_time);', src)
        self.assertLess(src.index('nc_stop();'), src.index('return exit_code;\n}'))
        # review: the stop row reads the main encoder, so it is written before the encoders are closed (freed)
        self.assertLess(src.index('\tnc_stop();'), src.index('if (S[k].enc) p_close(S[k].enc);'))
        # review: the card file is trimmed only at the stop, never in the capture loop
        self.assertIn('if (!sd || at_stop) nc_trim(', src)
        self.assertIn('nc_flush(1);', src[src.index('static void nc_stop(void)'):])
        # the same total gain as low light
        self.assertIn('g = ae_gain(r);', src)
        self.assertIn('return (int)(((long long)r->isp_d_gain * (((long long)r->a_gain * r->d_gain) >> 8)) >> 16);', src)
        # measurement only: the block calls no encoder or ISP setter
        b = block(src)
        for call in ('ioctl(', 'p_set_br', 'fe_set_', 'rc_set_', 'md_enc_'):
            self.assertNotIn(call, b[:b.index('/* ---- NIGHT-CEIL, the night setting') if '/* ---- NIGHT-CEIL, the night setting' in b else len(b)])
        self.assertIn('nc_on = !(e && e[0] == \'0\')', b)                                 # on unless RTSP_NIGHTCEIL_LOG=0
        # the night setting: once the encoders are open, before the free encoders' per-picture settings (fe_set_fps)
        i = src.index('night_enc_sync();\t/* NIGHT-CEIL')
        self.assertLess(src.index('if (fail_main) { LOG("ak_venc_open failed'), i)
        self.assertLess(i, src.index('fe_set_fps(fe, enc_rate);'))
        self.assertEqual(src.count('night_enc_sync();'), 1)
        self.assertIn('r = p_set_br(S[0].enc, night_kbps_now > 0 && want > night_kbps_now ? night_kbps_now : want);', src)


if __name__ == '__main__':
    unittest.main()
