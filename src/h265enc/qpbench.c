/*
 * qpbench: the T1 bench (docs/linux-port/frontier/t1-qp-bench.md): is the 0x4040-byte "tables" buffer of the encoder
 * core its QP control buffer (QP bounds, then a QP / forced intra / forced skip byte per block, qpctl.h)?
 * BENCH ONLY, on a test camera with tc100_rtsp stopped: it takes the ISP and the encoder for itself, writes nothing to
 * the flash and changes nothing in tc100_rtsp.
 *
 *   qpbench [-c hevc|avc] [-q QP] [-n N] [-g GOP] [-s SKIP] [-F] -x SPEC OUTDIR
 *   qpbench --dry [-c hevc|avc] -x SPEC        what SPEC changes, no device (tests/test_h265cmdlist.py QpBench)
 *
 *   -x SPEC   the experiment, ONE per run (qpctl.h: ctl, min=N, max=N, thrI=V, dq=V, dqI=V, byte@OFF=V, map=V[,...],
 *             list@WORD:MASK=V). --multi allows up to 4 -x in one run: only to look for the list bit that turns the
 *             map on (a map and one list bit together).
 *   -c        hevc (default) or avc, both 1920x1080 from the ISP main channel; -q the QP of every picture (default 32:
 *             the rate control is off, so that a size only moves with the experiment); -n pictures per phase (default
 *             50); -g an IDR every GOP pictures (default 25); -s pictures dropped first while the ISP settles (15)
 *   -F        freeze: the capture is stopped after one picture and that picture is coded every time (the sizes then
 *             depend on the experiment alone; P pictures of a frozen source are nearly empty: use it with -g 1)
 *
 * A run is three phases of N pictures on the same scene: base1 (the vendor's values), test (the vendor's values + the
 * experiment), base2 (the vendor's values again). Every phase starts with an IDR and goes to its own file
 * (OUTDIR/base1.265, test.265, base2.265; .264 with -c avc). OUTDIR/run.csv has one line per picture: number, phase,
 * type (I / P / F = failed), QP, bytes, milliseconds on the core, then the 48 status words 0x40-0x6f the core wrote
 * into the list (hexadecimal). OUTDIR/summary.txt = what is printed at the end.
 *
 * The encoder is freeenc.h itself (what tc100_rtsp runs), with its FE_BENCH_HOOK: before every picture the whole
 * tables buffer is written again from the vendor's values, and the experiment goes on top of them in the test phase
 * only. At the first failed picture (no interrupt within the kernel's 2 s, or a length of 0 or over the stream
 * buffer) the run stops: the vendor's values are back, up to 3 pictures are tried with them, and the result says
 * whether the core codes again or the camera needs a reboot.
 * Exit status: 0 done, 1 set-up error, 2 usage, 3 failed in the test phase (the core codes again), 4 failed in a
 * baseline phase (not the experiment's doing), 5 the core does not answer any more (reboot).
 *
 * Host build (-DQPBENCH_NO_DEVICE): --dry, and --sim = the whole run on a simulated core (a picture's size follows
 * bytes 19 and 64 of the tables buffer; QPB_SIM_FAIL=test: no interrupt in the test phase, =dead: and never again).
 * License: GPL-2.0-or-later
 */
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#ifndef QPBENCH_NO_DEVICE
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/videodev2.h>
#include "../libakuio/ak39_venc.h"
#else
#define FE_HOST_TEST
#endif

struct fe_enc;
static void qpb_hook(struct fe_enc *e, uint32_t *l, int idr);
#define FE_BENCH_HOOK(e, l, idr) qpb_hook(e, l, idr)
#include "freeenc.h"
#include "qpctl.h"

#define W 1920
#define H 1080
#define QPB_MAXX 4
enum { PH_BASE1, PH_TEST, PH_BASE2, PH_RECOVER };
static const char *const PH_NAME[4] = { "base1", "test", "base2", "recover" };

static int g_phase;
static struct qpc_exp g_x[QPB_MAXX];
static int g_nx, g_freeze;
static uint8_t g_shadow[QPC_SIZE];
static FILE *g_sum;
static volatile sig_atomic_t g_stop;

static void on_signal(int s) { (void)s; g_stop = 1; }

/* freeenc.h calls this right before the core starts on a picture: the vendor's values, always; the experiment on top
 * of them in the test phase only (the list is built again for every picture: nothing to undo there) */
static void qpb_hook(struct fe_enc *e, uint32_t *l, int idr)
{
	int i;

	qpc_vendor(g_shadow, e->hevc, idr);
	if (g_phase == PH_TEST)
		for (i = 0; i < g_nx; i++) qpc_apply(&g_x[i], g_shadow, l);
	memcpy(e->mem + e->tables_off, g_shadow, QPC_SIZE);
}

static void say(const char *fmt, ...)
{
	va_list ap;

	va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
	if (g_sum) { va_start(ap, fmt); vfprintf(g_sum, fmt, ap); va_end(ap); }
	fflush(stdout);
}

static double now_ms(void)
{
	struct timeval tv;

	gettimeofday(&tv, NULL);
	return tv.tv_sec * 1000.0 + tv.tv_usec / 1000.0;
}

/* --dry: the bytes of the tables buffer and the list words an experiment changes, for an IDR and a P picture */
static int dry(int hevc)
{
	static uint8_t v[QPC_SIZE], t[QPC_SIZE];
	static uint32_t l[FE_LIST_WORDS], l0[FE_LIST_WORDS];
	int idr, i, k;

	for (idr = 1; idr >= 0; idr--) {
		const char *ty = idr ? "idr" : "p";
		const uint32_t *src = hevc ? (idr ? LISTGEN_IDR : LISTGEN_P) : (idr ? LISTGEN_H264_1080P_IDR : LISTGEN_H264_1080P_P);

		memset(l0, 0, sizeof l0); memcpy(l0, src, 32 * 4); memcpy(l, l0, sizeof l);
		qpc_vendor(v, hevc, idr); memcpy(t, v, sizeof t);
		for (i = 0; i < g_nx; i++) qpc_apply(&g_x[i], t, l);
		for (i = 0; i < (int)QPC_SIZE; i = k) {
			k = i + 1;
			if (t[i] == v[i]) continue;
			while (k < (int)QPC_SIZE && t[k] != v[k] && t[k] == t[i]) k++;
			printf("%s tables 0x%04x %d 0x%02x\n", ty, i, k - i, t[i]);
		}
		for (i = 0; i < FE_LIST_WORDS; i++)
			if (l[i] != l0[i]) printf("%s list 0x%02x %08x %08x\n", ty, i, l0[i], l[i]);
	}
	return 0;
}

#ifdef QPBENCH_NO_DEVICE
/* ---- the simulated core and source (--sim) ---- */
static uint8_t sim_pool[16 << 20] __attribute__((aligned(4096)));
static int sim_dead;

static unsigned long b_alloc(int n) { return (uint32_t)n <= sizeof sim_pool ? (unsigned long)sim_pool : 0; }
static void b_release(unsigned long v) { (void)v; }
static int b_v2p(unsigned long v) { return (int)(0x81800000u + (uint32_t)(v - (unsigned long)sim_pool)); }
static void b_wait(unsigned long r) { (void)r; }
static const struct fe_env g_env = { NULL, b_alloc, b_release, b_v2p, b_wait, NULL };

static int fe_run(struct fe_enc *e, uint32_t list_pa)
{
	uint32_t *l = (uint32_t *)(void *)(e->mem + (list_pa - e->pa)), len;
	const uint8_t *t = e->mem + e->tables_off;
	const char *f = getenv("QPB_SIM_FAIL");
	int idr = ((l[3] >> 28) & 3) == 2;

	fprintf(stderr, "sim %s %s min %u max %u map0 %02x maplast %02x w2 %08x\n", PH_NAME[g_phase], idr ? "I" : "P", t[QPC_OFF_MIN],
		t[QPC_OFF_MAX], t[QPC_HEAD], t[QPC_SIZE - 1], l[2]);
	if (f && (sim_dead || g_phase == PH_TEST)) { if (!strcmp(f, "dead")) sim_dead = 1; return -1; }
	len = (idr ? 8000u : 2000u) + 64u * t[QPC_OFF_MAX] + 4u * t[QPC_HEAD];
	memset(e->mem + e->stream_off + FE_STREAM_HEAD, 0xab, len);
	l[0x41] = len; l[0x40] = 0x1234;
	return 0;
}

static int src_open(int skip) { (void)skip; return 0; }
static int src_next(uint32_t *pa) { *pa = 0x82d00000u; return 0; }
static void src_done(void) { }
static void src_close(void) { }
static int dev_open(void) { return 0; }
#else
/* ---- the camera: /dev/uio0 (pool, registers, interrupt) and the ISP main channel ---- */
static int ufd = -1, vfd = -1, v_n, v_cur = -1, v_frozen, pool_used;
static uint8_t *pool;
static struct ak39_venc_pool_info info;
static struct fe_env g_env;
static uint32_t v_pa;

struct ak39_vi_phys { uint32_t index, phys_y, phys_uv, size; };
#define AK39_VI_G_PHYS _IOWR('V', BASE_VIDIOC_PRIVATE + 0, struct ak39_vi_phys)
static struct ak39_vi_phys ph[4];

/* one encoder at a time: its block is the start of the pool (tc100_rtsp is stopped, nothing else allocates) */
static unsigned long b_alloc(int n) { if (pool_used || (uint32_t)n > info.size) return 0; pool_used = 1; return (unsigned long)pool; }
static void b_release(unsigned long v) { (void)v; pool_used = 0; }
static int b_v2p(unsigned long v) { return (int)(info.paddr + (uint32_t)(v - (unsigned long)pool)); }
/* as libakuio's akuio_wait_irq: the result stays what the caller set (-1) when no interrupt came */
static void b_wait(unsigned long r) { int v = 0; if (ioctl(ufd, AKUIO_WAIT_IRQ, &v) < 0) return; *(int *)r = 0; }
static void b_reset(void) { ioctl(ufd, AKUIO_VIDEO_RESET, 0); }

static int dev_open(void)
{
	const char *dev = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";
	void *regs;

	ufd = open(dev, O_RDWR | O_SYNC);
	if (ufd < 0 || ioctl(ufd, AK39_VENC_POOL_INFO, &info) < 0) { perror(dev); return -1; }
	pool = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, ufd, AK39_VENC_MMAP_POOL);
	regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, ufd, AK39_VENC_MMAP_REGS);
	if (pool == MAP_FAILED || regs == MAP_FAILED) { perror("mmap"); return -1; }
	g_env.regs = regs; g_env.alloc = b_alloc; g_env.release = b_release; g_env.v2p = b_v2p; g_env.wait = b_wait;
	g_env.reset = b_reset;
	return 0;
}

/* the capture, as h265live / tc100_rtsp: NV12 1920x1080, mmap buffers whose physical address the driver gives */
static int src_open(int skip)
{
	struct v4l2_format fmt;
	struct v4l2_requestbuffers rq;
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	int k;

	vfd = open(getenv("H265_VIDEO") ? getenv("H265_VIDEO") : "/dev/video0", O_RDWR);
	if (vfd < 0) { perror("video (is tc100_rtsp stopped?)"); return -1; }
	memset(&fmt, 0, sizeof fmt);
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = W; fmt.fmt.pix.height = H;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12; fmt.fmt.pix.field = V4L2_FIELD_NONE;
	if (ioctl(vfd, VIDIOC_S_FMT, &fmt) < 0) { perror("S_FMT (is tc100_rtsp stopped?)"); return -1; }
	memset(&rq, 0, sizeof rq);
	rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_MMAP;
	if (ioctl(vfd, VIDIOC_REQBUFS, &rq) < 0 || rq.count < 1 || rq.count > 4) { perror("REQBUFS"); return -1; }
	v_n = (int)rq.count;
	for (k = 0; k < v_n; k++) {
		struct v4l2_buffer b;

		memset(&b, 0, sizeof b);
		b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = (unsigned)k;
		ph[k].index = (unsigned)k; ph[k].phys_y = ph[k].phys_uv = ph[k].size = 0;
		if (ioctl(vfd, VIDIOC_QUERYBUF, &b) < 0 || ioctl(vfd, AK39_VI_G_PHYS, &ph[k]) < 0 || !ph[k].phys_y) {
			fprintf(stderr, "buffer %d: no physical address (AK39_VI_G_PHYS: %s)\n", k, strerror(errno)); return -1;
		}
		/* freeenc.h reads the UV plane right after the Y plane */
		if (ph[k].phys_uv && ph[k].phys_uv != ph[k].phys_y + W * H) {
			fprintf(stderr, "buffer %d: UV at %08x, not right after Y (%08x)\n", k, ph[k].phys_uv, ph[k].phys_y); return -1;
		}
		if (ioctl(vfd, VIDIOC_QBUF, &b) < 0) { perror("QBUF"); return -1; }
	}
	if (ioctl(vfd, VIDIOC_STREAMON, &bt) < 0) { perror("STREAMON"); return -1; }
	for (k = 0; k < skip; k++) {
		struct v4l2_buffer b;

		memset(&b, 0, sizeof b);
		b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
		if (ioctl(vfd, VIDIOC_DQBUF, &b) < 0) { perror("DQBUF"); return -1; }
		ioctl(vfd, VIDIOC_QBUF, &b);
	}
	return 0;
}

static int src_next(uint32_t *pa)
{
	struct v4l2_buffer b;
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;

	if (v_frozen) { *pa = v_pa; return 0; }
	memset(&b, 0, sizeof b);
	b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
	if (ioctl(vfd, VIDIOC_DQBUF, &b) < 0) { perror("DQBUF"); return -1; }
	if ((int)b.index >= v_n) { ioctl(vfd, VIDIOC_QBUF, &b); return -1; }
	*pa = ph[b.index].phys_y;
	if (g_freeze) {	/* the ISP stops writing: this picture stays as it is (the buffers live until the close) */
		ioctl(vfd, VIDIOC_STREAMOFF, &bt);
		v_frozen = 1; v_pa = *pa;
		return 0;
	}
	v_cur = (int)b.index;
	return 0;
}

static void src_done(void)
{
	struct v4l2_buffer b;

	if (v_cur < 0) return;
	memset(&b, 0, sizeof b);
	b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = (unsigned)v_cur;
	ioctl(vfd, VIDIOC_QBUF, &b);
	v_cur = -1;
}

static void src_close(void)
{
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;

	if (vfd < 0) return;
	if (!v_frozen) ioctl(vfd, VIDIOC_STREAMOFF, &bt);
	close(vfd);
}
#endif

struct stat3 { uint32_t n[2]; uint64_t bytes[2]; };

/* the test phase against the two baselines around it, for one picture type */
static void verdict(const struct stat3 *s, int idr)
{
	double b1, b2, t, base, spread, ratio, lim;

	if (!s[PH_BASE1].n[idr] || !s[PH_TEST].n[idr] || !s[PH_BASE2].n[idr]) return;
	b1 = (double)s[PH_BASE1].bytes[idr] / s[PH_BASE1].n[idr];
	b2 = (double)s[PH_BASE2].bytes[idr] / s[PH_BASE2].n[idr];
	t = (double)s[PH_TEST].bytes[idr] / s[PH_TEST].n[idr];
	base = (b1 + b2) / 2;
	spread = (b1 > b2 ? b1 - b2 : b2 - b1) / base;
	ratio = t / base;
	lim = 3 * spread > 0.05 ? 3 * spread : 0.05;
	say("%s pictures: base1 %.0f, test %.0f, base2 %.0f bytes; test / baseline = %.3f (the baselines differ by %.1f %%): %s\n",
	    idr ? "IDR" : "P", b1, t, b2, ratio, spread * 100,
	    ratio > 1 + lim || ratio < 1 - lim ? "CHANGED" : "no change beyond the scene's own");
}

int main(int argc, char **argv)
{
	static struct fe_enc e;
	static struct stat3 st[3];
	const char *spec[QPB_MAXX], *out = NULL, *ext;
	int a, hevc = 1, qp = 32, n = 50, gop = 25, skip = 15, is_dry = 0, multi = 0, sim = 0, nspec = 0;
	int pic, i, rc = 0, failed = -1, recovered = 0, core_wrote = 0;
	FILE *f = NULL, *csv;
	char path[1024];
	uint32_t *l, pa = 0;

	for (a = 1; a < argc && argv[a][0] == '-'; a++) {
		if (!strcmp(argv[a], "--dry")) is_dry = 1;
		else if (!strcmp(argv[a], "--sim")) sim = 1;
		else if (!strcmp(argv[a], "--multi")) multi = 1;
		else if (!strcmp(argv[a], "-F")) g_freeze = 1;
		else if (a + 1 < argc && !strcmp(argv[a], "-c")) hevc = strcmp(argv[++a], "avc") != 0;
		else if (a + 1 < argc && !strcmp(argv[a], "-q")) qp = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-n")) n = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-g")) gop = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-s")) skip = atoi(argv[++a]);
		else if (a + 1 < argc && !strcmp(argv[a], "-x") && nspec < QPB_MAXX) spec[nspec++] = argv[++a];
		else break;
	}
	if (a < argc && argv[a][0] != '-') out = argv[a++];
	if (a != argc || !nspec || (nspec > 1 && !multi) || (!is_dry && !out) || qp < 0 || qp > 51 || n < 1 || n > 1000 || gop < 1 ||
	    skip < 0) {
		fprintf(stderr, "usage: %s [-c hevc|avc] [-q QP] [-n PICTURES_PER_PHASE] [-g GOP] [-s SKIP] [-F] -x SPEC OUTDIR\n"
			"       %s --dry [-c hevc|avc] -x SPEC\n"
			"one -x per run (--multi: up to %d, only to look for the list bit that turns the map on); SPEC: ctl, min=N,\n"
			"max=N, thrI=V, dq=V, dqI=V, byte@OFF=V, map=V[,first=K|top|bottom|left|right|rect=X0:Y0:X1:Y1][,blk=N][,cols=N]\n"
			"[,unit=N], list@WORD:MASK=V (src/h265enc/qpctl.h, docs/linux-port/frontier/t1-qp-bench.md)\n",
			argv[0], argv[0], QPB_MAXX);
		return 2;
	}
	for (i = 0; i < nspec; i++)
		if (qpc_parse(&g_x[i], spec[i], W, H, hevc) < 0) { fprintf(stderr, "experiment not understood: %s\n", spec[i]); return 2; }
	g_nx = nspec;
	if (memcmp(QPC_VENDOR_HEAD, FE_TABLES_HEAD, sizeof QPC_VENDOR_HEAD)) { fprintf(stderr, "qpctl.h and freeenc.h differ on the vendor's values\n"); return 1; }
	if (is_dry) return dry(hevc);
#ifdef QPBENCH_NO_DEVICE
	if (!sim) { fprintf(stderr, "built without the device: --dry or --sim only\n"); return 2; }
#else
	if (sim) { fprintf(stderr, "--sim: host build only\n"); return 2; }
#endif
	ext = hevc ? "265" : "264";
	snprintf(path, sizeof path, "%s/summary.txt", out);
	if (!(g_sum = fopen(path, "w"))) { perror(path); return 1; }
	snprintf(path, sizeof path, "%s/run.csv", out);
	if (!(csv = fopen(path, "w"))) { perror(path); return 1; }
	fprintf(csv, "pic,phase,type,qp,bytes,ms");
	for (i = 0x40; i < 0x70; i++) fprintf(csv, ",s%02x", i);
	fprintf(csv, "\n");
	signal(SIGINT, on_signal); signal(SIGTERM, on_signal);
	if (dev_open() < 0) return 1;
	/* qmin = qmax = QP: one QP for every picture, the rate control has nothing to decide */
	if (!fe_open_wh(&g_env, &e, hevc, W, H, W, 25, gop, 4000, qp, qp)) { fprintf(stderr, "fe_open failed (pool)\n"); return 1; }
	l = (uint32_t *)(void *)(e.mem + e.list_off);
	if (src_open(skip) < 0) { fe_close(&e); return 1; }
#ifndef QPBENCH_NO_DEVICE
	fe_hw_init(&g_env);
#endif
	say("qpbench %s 1920x1080 QP %d, %d pictures per phase, GOP %d%s; experiment:", hevc ? "H.265" : "H.264", qp, n, gop,
	    g_freeze ? ", frozen source" : "");
	for (i = 0; i < nspec; i++) say(" %s", spec[i]);
	say("\n");
	g_phase = PH_BASE1;
	for (pic = 0; pic < 3 * n && !g_stop; pic++) {
		uint8_t *d;
		uint32_t len = 0;
		int idr = 0, r, p = pic / n;
		double t;

		if (p != g_phase || !f) {
			if (f) fclose(f);
			g_phase = p;
			if (pic) e.force_idr = 1;	/* every phase starts with a keyframe: each file plays alone */
			snprintf(path, sizeof path, "%s/%s.%s", out, PH_NAME[p], ext);
			if (!(f = fopen(path, "wb"))) { perror(path); rc = 1; break; }
		}
		if (src_next(&pa) < 0) { say("capture: no picture\n"); rc = 1; break; }
		t = now_ms();
		r = fe_encode(&e, pa, &d, &len, &idr);
		t = now_ms() - t;
		src_done();
		if (memcmp(e.mem + e.tables_off, g_shadow, QPC_SIZE)) core_wrote++;
		if (r < 0) {
			fprintf(csv, "%d,%s,F,%u,%u,%.1f", pic, PH_NAME[p], (l[3] >> 16) & 0xff, e.last_len, t);
			for (i = 0x40; i < 0x70; i++) fprintf(csv, ",%x", l[i]);
			fprintf(csv, "\n");
			say("picture %d (%s) FAILED: length %u, list status %08x, wait %d, 0x8018 %08x, 0x801c %08x, 0x8300 %08x\n", pic,
			    PH_NAME[p], e.last_len, e.last_status, (int)e.dbg[2], e.dbg[3], e.dbg[4], e.dbg[5]);
			failed = p;
			break;
		}
		if (fwrite(d, 1, len, f) != len) { perror(path); rc = 1; break; }
		fprintf(csv, "%d,%s,%c,%u,%u,%.1f", pic, PH_NAME[p], idr ? 'I' : 'P', (l[3] >> 16) & 0xff, len, t);
		for (i = 0x40; i < 0x70; i++) fprintf(csv, ",%x", l[i]);
		fprintf(csv, "\n");
		st[p].n[idr ? 1 : 0]++; st[p].bytes[idr ? 1 : 0] += len;
	}
	if (f) fclose(f);
	if (failed >= 0) {
		/* the vendor's values (the hook writes them in every phase but the test) and up to 3 pictures with them */
		g_phase = PH_RECOVER;
		for (i = 0; i < 3 && !recovered && !g_stop; i++) {
			uint8_t *d;
			uint32_t len;
			int idr;

			if (src_next(&pa) < 0) break;
			if (!fe_encode(&e, pa, &d, &len, &idr)) recovered = 1;
			src_done();
		}
		rc = !recovered ? 5 : failed == PH_TEST ? 3 : 4;
		say("the vendor's values are back: %s\n", recovered ? "the core codes again" :
		    "THE CORE DOES NOT ANSWER, reboot the camera (do not start tc100_rtsp on it)");
		if (recovered) say(failed == PH_TEST ? "the failure came with the experiment: note it, do not repeat this value\n" :
				   "the failure came in a baseline phase: not the experiment's doing, run 'ctl' first\n");
	} else if (!rc && !g_stop) {
		for (i = 0; i < 3; i++)
			say("%-5s: %u IDR, %llu bytes; %u P, %llu bytes\n", PH_NAME[i], st[i].n[1], (unsigned long long)st[i].bytes[1],
			    st[i].n[0], (unsigned long long)st[i].bytes[0]);
		verdict(st, 1); verdict(st, 0);
	}
	if (core_wrote) say("the core (or something else) changed the tables buffer during %d pictures\n", core_wrote);
	g_phase = PH_RECOVER;
	qpc_vendor(e.mem + e.tables_off, hevc, 0);
	src_close();
	fe_close(&e);
	fclose(csv);
	say("%s: %u pictures coded, %u failed -> exit %d\n", out, e.pictures, e.fails, rc);
	fclose(g_sum);
	return rc;
}
