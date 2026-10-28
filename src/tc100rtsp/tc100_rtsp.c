/* tc100_rtsp: RTSP/H.264 or H.265 server for the TECKIN TC100 on Linux 6.6.
 *
 * Capture (V4L2, 1080p NV12) -> vendor H.264 encoder control library on the free libakuio + ak39_venc driver
 * (see src/venctest) -> RTP (RFC 6184, packetization-mode 1, FU-A) over RTSP: TCP interleaved or UDP unicast.
 * The select() loop of the main thread serves the V4L2 device, the listening socket, the clients and the microphone;
 * the only other thread is the recorder's card writer (rec.c: an SD card can stall a write for seconds).
 * The GOP being encoded is cached so that a new client starts immediately on the last IDR frame.
 *
 * Two streams: main 1920x1080 and a 640x360 sub-stream (second encoder channel, fed from the scaled picture that
 * also makes the web UI's stream.jpg). Paths with "video1" in them, or starting with /ch1 or /sub, serve the
 * sub-stream; every other path the main stream (also the sub paths when the sub-stream is off or did not open).
 * Sound: the microphone (an arecord child, the only ALSA capture reader) feeds the RTSP audio track, the recordings (rec.c,
 * REC_AUDIO), the sound level and the web UI's Listen button (alisten.c: FIFOs); a client that asks for the ONVIF backchannel
 * (go2rtc, Frigate, Home Assistant) can play its sound on the speaker (talk.c, RTSP_LITE_TALK, password required).
 * Also here: the web UI pictures (hardware JPEG), motion detection with ignored zones (/tmp/rec_control), the
 * microphone level for the sound detection (/var/run/sound_level) and the local recording (rec.c, fragmented MP4 files
 * on the SD card). Settings are read from /mnt/config while running (boot.conf, rtspserver.conf, isp_tune.conf,
 * sound_detection.conf, motion_zones.conf, frigate_live.conf).
 *
 * usage: tc100_rtsp [-c h264|h265] [-p PORT] [-b KBPS] [-f FPS] [-q QMIN] [-Q QMAX] [-d VIDEODEV] [-L LIBDIR] [-A libakuio.so]
 *            [-u USER] [-w PASSWORD_FILE]   (Digest or Basic when the file holds a password)
 *            [-a 0|1 audio track] [-s 0|1 sub-stream] [-C h264|h265 sub codec] [-B KBPS sub bit rate]
 *            [-R RECORD_DIR (/mnt/DCIM)] [-S SOUND_LEVEL_FILE (/var/run/sound_level)]
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "../libakuio/ak39_venc.h"
#include "alisten.h"
#include "jpeg_hw.h"
#include "rec.h"
#include "talk.h"
#include "util.h"

#define W 1920
#define H 1080
#define SW 640		/* sub-stream, stored in the V4L2 buffer after the main picture */
#define SH 360
#define MAXCLI 4
#define RTP_PAYLOAD 1400
#define CACHE_MAX (1536 * 1024)
#define CACHE_MAX_SUB (384 * 1024)
#define CACHE_FRAMES 128
#define QMAX (768 * 1024)	/* per-client output queue limit */
#ifndef CONF
#define CONF "/mnt/config/"
#endif

/* struct encode_param of the vendor SDK (48 bytes). size_class is the "use channel" (0 main, 1 sub: 512 / 256 KiB
 * stream cache) and group the encoder group (one handle per group: "group %d's handle has already opened"). The vendor
 * v4l2rtspserver (AnykaCameraManager::getVideoEncodeParams, disassembled) opens its main stream with 0 / 1 and its
 * sub-stream with 1 / 2; tc100_rtsp keeps group 0 for the main stream (what ran on 6.6 since the start) and uses the
 * vendor's 1 / 2 for the sub-stream. RTSP_SUB_CHN / RTSP_SUB_GROUP (environment, e.g. config/rtsp.env) override. */
struct venc_param {
	unsigned int width, height, qpmin, qpmax, fps, gop, kbps, profile, size_class, group, rc_vbr, codec;
};
struct video_stream {
	unsigned char *data;
	unsigned int len;
	unsigned int w2[3];
	unsigned int frame_type;
	unsigned int rest[10];
};

#define LOG(...) do { char _b[300]; int _n = snprintf(_b, sizeof _b, __VA_ARGS__); \
	_n = _n > (int)sizeof _b - 1 ? (int)sizeof _b - 1 : _n; if (_n > 0) (void)!write(2, _b, _n); } while (0)

static void *(*p_open)(const struct venc_param *);
static int (*p_send)(void *, unsigned char *, unsigned int, struct video_stream *);
static int (*p_release)(void *, struct video_stream *);
static int (*p_close)(void *);
static unsigned long (*p_alloc)(int);
static int (*p_pinit)(void);
static volatile int run = 1;

static void on_sig(int s) { (void)s; run = 0; }

/* ---- web UI pictures from the hardware JPEG engine (same files as tc100_streamer) ---- */
#define JSTREAM 0x7e900
static int (*p_v2p)(unsigned long);
static void (*p_wait)(unsigned long);
static uint8_t *jbuf;
static uint32_t jpaddr;
static int jpeg_ok, jpeg_inited;

static int jpeg_init(void)
{
	const char *dv = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";
	struct ak39_venc_pool_info info;
	int fd = open(dv, O_RDWR | O_SYNC);

	if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) return -1;
	regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
	if (regs == MAP_FAILED) { regs = NULL; return -1; }
	p_v2p = dlsym(RTLD_DEFAULT, "akuio_vaddr2paddr");
	p_wait = dlsym(RTLD_DEFAULT, "akuio_wait_irq");
	jbuf = (uint8_t *)p_alloc(JSTREAM + AUX_SIZE);
	if (!p_v2p || !p_wait || !jbuf) return -1;
	jpaddr = (uint32_t)p_v2p((unsigned long)jbuf);
	return jpaddr ? 0 : -1;
}

/* encode one NV12 picture (physical addresses) -> jbuf + TABLES_SIZE, returns the length or 0 */
static uint32_t jpeg_run(uint32_t y, uint32_t uv, int w, int h, int q)
{
	uint32_t c[11], st[3];

	build_tables(jbuf + JSTREAM, q);
	ctrl_words(c, w, h, y, uv, jpaddr + JSTREAM, jpaddr, JSTREAM);
	{ FILE *df = w < 1000 ? fopen("/tmp/c2", "r") : NULL; char hb[16];	/* debug: control word 2 override (hex) */
	  if (df) {	/* no fscanf: glibc headers turn it into __isoc23_fscanf, which uClibc does not have */
		if (fgets(hb, sizeof hb, df)) {
			uint32_t v = 0; int k = 0; const char *p = hb + (hb[0] == '0' && (hb[1] | 32) == 'x' ? 2 : 0);

			for (; *p; p++, k++) {
				int d = *p >= '0' && *p <= '9' ? *p - '0' : (*p | 32) >= 'a' && (*p | 32) <= 'f' ? (*p | 32) - 'a' + 10 : -1;

				if (d < 0) break;
				v = v << 4 | (uint32_t)d;
			}
			if (k) c[2] = v;
		}
		fclose(df);
	  } }
	if (!jpeg_inited) { hw_init(); jpeg_inited = 1; }
	hw_encode(c);
	p_wait(0);
	st[0] = RD(R_JPEG_STATUS); st[1] = RD(R_JPEG_STATUS + 4); st[2] = RD(R_JPEG_STATUS + 8);
	(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 0x10001);
	WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
	WR(R_CLK, (RD(R_CLK) & 0xffff7fff) | 0xe00);
	if (getenv("RTSP_DEBUG")) LOG("JPEG %dx%d status %08x %08x %08x\n", w, h, st[0], st[1], st[2]);
	if (st[1] < 4 || st[1] > JSTREAM - TABLES_SIZE || jbuf[TABLES_SIZE] != 0xff || jbuf[TABLES_SIZE + 1] != 0xd8) return 0;
	return st[1];
}

static void wfile(const char *name, const void *d, size_t n)
{
	char tmp[96];
	int f;

	snprintf(tmp, sizeof tmp, "%s.tmp", name);
	f = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (f < 0) return;
	if (write(f, d, n) == (ssize_t)n) { close(f); rename(tmp, name); }
	else { close(f); unlink(tmp); }
}

/* The 6.6 ISP driver does not fill the sub-channel of the V4L2 buffer: make the 640x360 picture from the main one
 * (3x3 decimation, a 3-sample average along the line). */
static void sub_scale(const unsigned char *src, unsigned char *dst)
{
	const unsigned char *uv = src + W * H;
	unsigned char *duv = dst + SW * SH;

	for (int y = 0; y < SH; y++) {
		const unsigned char *r = src + (3 * y + 1) * W;
		unsigned char *o = dst + y * SW;

		for (int x = 0; x < SW; x++)
			o[x] = (r[3 * x] + r[3 * x + 1] + r[3 * x + 2]) / 3;
	}
	for (int y = 0; y < SH / 2; y++) {
		const unsigned char *r = uv + (3 * y + 1) * W;
		unsigned char *o = duv + y * SW;

		for (int x = 0; x < SW / 2; x++) {
			o[2 * x] = r[(3 * x + 1) * 2];
			o[2 * x + 1] = r[(3 * x + 1) * 2 + 1];
		}
	}
}

static double now_s(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static int atoi_(const char *s)	/* no atoi/strtol: they pull C2x symbols the camera's uClibc does not have */
{
	int n = 0, neg = 0;

	if (*s == '-') { neg = 1; s++; }
	while (*s >= '0' && *s <= '9') n = n * 10 + (*s++ - '0');
	return neg ? -n : n;
}

static void sscanf_4(const char *s, int *o)	/* "x1,y1,x2,y2" */
{
	int i;

	for (i = 0; i < 4; i++) { o[i] = atoi_(s); while (*s && *s != ',') s++; if (*s == ',') s++; }
}

/* ---- picture post-processing, done while the frame is copied to the encoder buffer ----------------------------
 * - live image tuning (Image page: brightness, contrast, saturation, hue) from config/isp_tune.conf when ISP_TUNE=1
 *   in boot.conf (sharpness needs a filter and is not done)
 * - grey-world white balance of the colour cast the ISP leaves (off when config/awb.off exists)
 * - privacy masks (isp_tune.conf MASK1..4 = x1,y1,x2,y2 in percent, MASK_COLOR) and the clock overlay
 *   (rtspserver.conf osdenabled / osdtext / [0] osdx osdy osdfontsize): burned in before the encoder, like the vendor ISP */
static unsigned char ylut[256], ulut[256], vlut[256];
static int p_ytune, p_hue, p_tune, p_bri, p_con, p_sat, p_mask[4][4], p_mcol = 16, p_osd, p_osdx = 20, p_osdy = 24, p_osdsz = 32;
static int p_awb = 1, p_du, p_dv;
static char p_fmt[64] = "%H:%M:%S %d.%m.%Y";

static int clampi(int v) { return v < 0 ? 0 : v > 255 ? 255 : v; }

static int cfg_get(const char *file, const char *sec, const char *key, char *out, int n)
{
	FILE *f = fopen(file, "r");
	char ln[512], cur[16] = "";
	int kl = (int)strlen(key), found = 0;

	if (!f) return 0;
	while (fgets(ln, sizeof ln, f)) {
		char *e = ln + strlen(ln);

		while (e > ln && (e[-1] == '\n' || e[-1] == '\r')) *--e = 0;
		if (ln[0] == '[') { snprintf(cur, sizeof cur, "%.15s", ln + 1); { char *r = strchr(cur, ']'); if (r) *r = 0; } continue; }
		if (strcmp(cur, sec)) continue;
		if (!strncmp(ln, key, kl) && ln[kl] == '=') {
			char *v = ln + kl + 1;

			if (*v == '"') { v++; { char *q = strrchr(v, '"'); if (q) *q = 0; } }
			snprintf(out, n, "%s", v); found = 1; break;
		}
	}
	fclose(f);
	return found;
}

static void post_luts(void)
{
	int i;
	int cf = 100 + p_con * 2, sf = 100 + p_sat * 2;

	p_ytune = p_tune && (p_bri || p_con);
	for (i = 0; i < 256; i++) {
		ylut[i] = (unsigned char)(p_ytune ? clampi((i - 128) * cf / 100 + 128 + p_bri * 2) : i);
		ulut[i] = (unsigned char)clampi(128 + (i - 128) * (p_tune ? sf : 100) / 100 - p_du);
		vlut[i] = (unsigned char)clampi(128 + (i - 128) * (p_tune ? sf : 100) / 100 - p_dv);
	}
}

static int truthy(const char *v) { return v[0] == '1' || !strcmp(v, "true") || !strcmp(v, "yes") || !strcmp(v, "on") || !strcmp(v, "enabled"); }

/* the picture settings (called by cfg_reload when boot.conf, isp_tune.conf or rtspserver.conf changed) */
static void post_apply(void)
{
	static const char *fn[3] = { CONF "boot.conf", CONF "isp_tune.conf", CONF "rtspserver.conf" };
	int i;
	char v[80];

	p_tune = cfg_get(fn[0], "", "ISP_TUNE", v, sizeof v) && truthy(v);
	p_bri = p_con = p_sat = p_hue = 0; memset(p_mask, 0, sizeof p_mask); p_mcol = 16;
	if (p_tune) {
		if (cfg_get(fn[1], "", "BRIGHTNESS", v, sizeof v)) p_bri = atoi_(v);
		if (cfg_get(fn[1], "", "CONTRAST", v, sizeof v)) p_con = atoi_(v);
		if (cfg_get(fn[1], "", "SATURATION", v, sizeof v)) p_sat = atoi_(v);
		if (cfg_get(fn[1], "", "HUE", v, sizeof v)) p_hue = atoi_(v);
		for (i = 0; i < 4; i++) {
			char k[8];

			snprintf(k, sizeof k, "MASK%d", i + 1);
			if (cfg_get(fn[1], "", k, v, sizeof v)) sscanf_4(v, p_mask[i]);
		}
		if (cfg_get(fn[1], "", "MASK_COLOR", v, sizeof v)) p_mcol = !strcmp(v, "white") ? 235 : !strcmp(v, "gray") ? 128 : 16;
	}
	p_osd = cfg_get(fn[2], "", "osdenabled", v, sizeof v) && v[0] == '1';
	if (cfg_get(fn[2], "", "osdtext", v, sizeof v) && v[0]) snprintf(p_fmt, sizeof p_fmt, "%.63s", v);
	if (cfg_get(fn[2], "0", "osdx", v, sizeof v)) p_osdx = atoi_(v);
	if (cfg_get(fn[2], "0", "osdy", v, sizeof v)) p_osdy = atoi_(v);
	if (cfg_get(fn[2], "0", "osdfontsize", v, sizeof v)) p_osdsz = atoi_(v);
	if (p_osdsz < 8) p_osdsz = 8;
	p_hue = p_tune ? p_hue : 0;
	post_luts();
}

/* hue: rotate (U,V) by p_hue * 0.6 degrees, fixed point */
static void hue_pair(unsigned char *u, unsigned char *v)
{
	static const int cs[] = { 256, 255, 253, 249, 244, 237, 230, 221 };	/* cos/sin of 0..~21 degrees (x256), index = |hue|*7/50 */
	static const int sn[] = { 0, 24, 48, 71, 94, 115, 135, 154 };
	int k = (p_hue < 0 ? -p_hue : p_hue) * 7 / 50, c = cs[k], s = p_hue < 0 ? -sn[k] : sn[k];
	int a = *u - 128, b = *v - 128;

	*u = (unsigned char)clampi(128 + (a * c - b * s) / 256);
	*v = (unsigned char)clampi(128 + (a * s + b * c) / 256);
}

static void post_awb_sample(const unsigned char *uv)
{
	long su = 0, sv = 0; int n = 0, i;

	if (!p_awb) return;
	for (i = 0; i < W * H / 2 - 2; i += 64) { su += uv[i]; sv += uv[i + 1]; n++; }	/* even i: U, i+1: V */
	if (!n) return;
	{
		int tu = (int)(su / n) - 128, tv = (int)(sv / n) - 128, ou = p_du, ov = p_dv;

		tu = tu > 85 ? 85 : tu < -85 ? -85 : tu;
		tv = tv > 85 ? 85 : tv < -85 ? -85 : tv;
		p_du += (tu - p_du + (tu > p_du ? 2 : -2)) / 4; p_dv += (tv - p_dv + (tv > p_dv ? 2 : -2)) / 4;
		if (p_du != ou || p_dv != ov) post_luts();
	}
}

static void post_copy(unsigned char *dst, const unsigned char *src)
{
	int i, n = W * H / 2;

	if (p_ytune) for (i = 0; i < W * H; i++) dst[i] = ylut[src[i]]; else memcpy(dst, src, W * H);
	src += W * H; dst += W * H;
	if (p_hue) { for (i = 0; i < n; i += 2) { dst[i] = ulut[src[i]]; dst[i + 1] = vlut[src[i + 1]]; hue_pair(&dst[i], &dst[i + 1]); } }
	else if (p_awb || p_tune) for (i = 0; i < n; i += 2) { dst[i] = ulut[src[i]]; dst[i + 1] = vlut[src[i + 1]]; }
	else memcpy(dst, src, n);
}

/* zero-copy mode: the same corrections as post_copy, in the capture buffer itself (nothing to do when none is on) */
static void post_inplace(unsigned char *p)
{
	int i, n = W * H / 2;
	unsigned char *c = p + W * H;

	if (p_ytune) for (i = 0; i < W * H; i++) p[i] = ylut[p[i]];
	if (p_hue) { for (i = 0; i < n; i += 2) { c[i] = ulut[c[i]]; c[i + 1] = vlut[c[i + 1]]; hue_pair(&c[i], &c[i + 1]); } }
	else if (p_awb || p_tune) for (i = 0; i < n; i += 2) { c[i] = ulut[c[i]]; c[i + 1] = vlut[c[i + 1]]; }
}

static void post_sub(unsigned char *p)	/* in place, SW x SH */
{
	int i, n = SW * SH / 2;

	if (p_ytune) for (i = 0; i < SW * SH; i++) p[i] = ylut[p[i]];
	p += SW * SH;
	if (p_awb || p_tune) for (i = 0; i < n; i += 2) { p[i] = ulut[p[i]]; p[i + 1] = vlut[p[i + 1]]; if (p_hue) hue_pair(&p[i], &p[i + 1]); }
}

static void fill(unsigned char *y, int w, int h, int x1, int y1, int x2, int y2, int col)
{
	int x, yy;

	x1 &= ~1; y1 &= ~1; x2 &= ~1; y2 &= ~1;
	x1 = x1 < 0 ? 0 : x1; y1 = y1 < 0 ? 0 : y1; x2 = x2 > w ? w : x2; y2 = y2 > h ? h : y2;
	for (yy = y1; yy < y2; yy++) memset(y + yy * w + x1, col, x2 > x1 ? x2 - x1 : 0);
	for (yy = y1 / 2; yy < y2 / 2; yy++) { unsigned char *r = y + w * h + yy * w; for (x = x1; x < x2; x += 2) { r[x] = 128; r[x + 1] = 128; } }
}

static const unsigned char font57[14][5] = {
	{0x3E,0x51,0x49,0x45,0x3E},{0x00,0x42,0x7F,0x40,0x00},{0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4B,0x31},
	{0x18,0x14,0x12,0x7F,0x10},{0x27,0x45,0x45,0x45,0x39},{0x3C,0x4A,0x49,0x49,0x30},{0x01,0x71,0x09,0x05,0x03},
	{0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1E},{0x00,0x36,0x36,0x00,0x00},{0x00,0x60,0x60,0x00,0x00},
	{0x08,0x08,0x08,0x08,0x08},{0x20,0x10,0x08,0x04,0x02} };

static void post_overlay(unsigned char *p, int w, int h, int main_pic)
{
	int i;

	for (i = 0; i < 4; i++)
		if (p_mask[i][2] > p_mask[i][0] && p_mask[i][3] > p_mask[i][1])
			fill(p, w, h, p_mask[i][0] * w / 100, p_mask[i][1] * h / 100, p_mask[i][2] * w / 100, p_mask[i][3] * h / 100, p_mcol);
	if (main_pic && p_osd) {
		char t[64]; time_t now = time(NULL); struct tm *tm = localtime(&now);
		int sc = p_osdsz / 8 ? p_osdsz / 8 : 1, x = p_osdx, y = p_osdy, n, c, r, k;

		if (!tm || !strftime(t, sizeof t, p_fmt, tm)) return;
		n = (int)strlen(t);
		fill(p, w, h, x - 2 * sc, y - 2 * sc, x + n * 6 * sc + 2 * sc, y + 9 * sc, 16);
		for (i = 0; i < n; i++) {
			const char *g = "0123456789:.-/"; const char *q = strchr(g, t[i]);

			if (!q || !t[i]) continue;
			k = (int)(q - g);
			for (c = 0; c < 5; c++) for (r = 0; r < 7; r++) if (font57[k][c] & (1 << r)) {
				int xx = x + (i * 6 + c) * sc, yy = y + r * sc, a, b;

				if (xx + sc > w || yy + sc > h) continue;
				for (b = 0; b < sc; b++) for (a = 0; a < sc; a++) p[(yy + b) * w + xx + a] = 235;
			}
		}
	}
}

static void *ld(const char *dir, const char *name, int must)
{
	char p[300];
	void *h;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	h = dlopen(p, RTLD_LAZY | RTLD_GLOBAL);
	if (!h) {
		LOG("dlopen %s: %s\n", p, dlerror());
		if (must) exit(2);
	}
	return h;
}

/* The vendor encoder library: libmpi_venc_ex.so (the copy stored in the project) first, else libmpi_venc.so (the camera's
 * own copy). Logs the one opened and its version string when it exports ak_venc_get_version (const char *(void)). */
static void *ld_venc(const char *dir)
{
	static const char *const names[] = { "libmpi_venc_ex.so", "libmpi_venc.so" };

	for (int i = 0; i < 2; i++) {
		char p[300];
		const char *(*gv)(void);
		const char *v = NULL;
		void *h;

		snprintf(p, sizeof p, "%s/%s", dir, names[i]);
		if (access(p, R_OK)) { LOG("encoder library %s: not present\n", p); continue; }
		if (!(h = ld(dir, names[i], 0))) continue;
		if (!dlsym(h, "ak_venc_open")) { LOG("encoder library %s: no ak_venc_open, trying the next one\n", p); continue; }
		gv = (const char *(*)(void))dlsym(h, "ak_venc_get_version");
		if (gv) {
			v = gv();
			if ((uintptr_t)v < 0x10000) v = NULL;
		}
		if (v) {
			char vb[64];
			int k = 0;

			for (; k < 63 && v[k] >= 32 && v[k] < 127; k++) vb[k] = v[k];
			vb[k] = 0;
			LOG("encoder library: %s, version \"%s\"\n", p, vb);
		} else {
			LOG("encoder library: %s%s\n", p, gv ? " (version string empty)" : " (no ak_venc_get_version)");
		}
		return h;
	}
	LOG("no encoder library (libmpi_venc_ex.so, libmpi_venc.so) in %s\n", dir);
	exit(2);
}

static int num(const char *s)
{
	int v = 0;

	while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
	return v;
}

/* ---- the two streams: encoder, parameter sets, GOP cache ---- */
struct cframe { unsigned char *d; int len; uint32_t ts; };
struct strm {
	const char *name;
	int hevc;			/* RFC 7798 packetization, VPS/SPS/PPS */
	int w, h;
	int on;				/* encoder open and usable */
	int active;			/* frames are being encoded */
	int fails;			/* encoder calls that failed in a row */
	void *enc;
	struct venc_param pa;
	unsigned long nsent;		/* frames sent to the encoder since it was opened */
	unsigned char sps[128], pps[64], vps[64];
	int sps_len, pps_len, vps_len;
	char sprop[448], plid[8];
	struct cframe cache[CACHE_FRAMES];	/* the last IDR and the frames after it */
	int ncache, cache_ok, cache_bytes, cache_max;
	unsigned long nfr, nbytes;
	uint32_t ssrc;
};
static struct strm S[2];
#define NT(s, b) ((s)->hevc ? ((b) >> 1) & 63 : (b) & 31)
#define HAVE_PS(s) ((s)->sps_len && (s)->pps_len && (!(s)->hevc || (s)->vps_len))

static const char b64t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int b64(char *o, const unsigned char *d, int n)
{
	int i, k = 0;

	for (i = 0; i + 2 < n; i += 3) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[((d[i] & 3) << 4) | (d[i + 1] >> 4)];
		o[k++] = b64t[((d[i + 1] & 15) << 2) | (d[i + 2] >> 6)];
		o[k++] = b64t[d[i + 2] & 63];
	}
	if (n - i == 1) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[(d[i] & 3) << 4];
		o[k++] = '='; o[k++] = '=';
	} else if (n - i == 2) {
		o[k++] = b64t[d[i] >> 2];
		o[k++] = b64t[((d[i] & 3) << 4) | (d[i + 1] >> 4)];
		o[k++] = b64t[(d[i + 1] & 15) << 2];
		o[k++] = '=';
	}
	o[k] = 0;
	return k;
}

/* next NAL unit in an Annex B buffer: returns its start (after the start code), sets *len; -1 at the end */
static int next_nal(const unsigned char *d, int n, int from, int *len)
{
	int i = from, s = -1;

	for (; i + 3 <= n; i++)
		if (d[i] == 0 && d[i + 1] == 0 && d[i + 2] == 1) {
			if (s >= 0) {
				int e = i;

				while (e > s && d[e - 1] == 0) e--;
				*len = e - s;
				return s;
			}
			s = i + 3;
			i += 2;
		}
	if (s < 0) return -1;
	*len = n - s;
	return s;
}

static void learn_params(struct strm *st, const unsigned char *d, int n)
{
	int pos = 0, l, s;

	while ((s = next_nal(d, n, pos, &l)) >= 0) {
		int t = NT(st, d[s]);

		if (st->hevc) {
			if (t == 32 && l < (int)sizeof st->vps) { memcpy(st->vps, d + s, l); st->vps_len = l; }
			if (t == 33 && l < (int)sizeof st->sps) { memcpy(st->sps, d + s, l); st->sps_len = l; }
			if (t == 34 && l < (int)sizeof st->pps) { memcpy(st->pps, d + s, l); st->pps_len = l; }
		} else {
			if (t == 7 && l < (int)sizeof st->sps) { memcpy(st->sps, d + s, l); st->sps_len = l; }
			if (t == 8 && l < (int)sizeof st->pps) { memcpy(st->pps, d + s, l); st->pps_len = l; }
		}
		pos = s + l;
	}
	if (!HAVE_PS(st)) return;
	{
		char a[200], c[100], v[100];

		b64(a, st->sps, st->sps_len);
		b64(c, st->pps, st->pps_len);
		if (st->hevc) {
			b64(v, st->vps, st->vps_len);
			snprintf(st->sprop, sizeof st->sprop, "sprop-vps=%.99s;sprop-sps=%.199s;sprop-pps=%.99s", v, a, c);
		} else if (st->sps_len > 3) {
			snprintf(st->sprop, sizeof st->sprop, "%s,%s", a, c);
			snprintf(st->plid, sizeof st->plid, "%02x%02x%02x", st->sps[1], st->sps[2], st->sps[3]);
		}
	}
}

/* ---- GOP cache: the last IDR and the frames after it ---- */
static void cache_reset(struct strm *s)
{
	for (int i = 0; i < s->ncache; i++) free(s->cache[i].d);
	s->ncache = 0; s->cache_bytes = 0; s->cache_ok = 1;
}

static void cache_add(struct strm *s, const unsigned char *d, int len, uint32_t ts, int idr)
{
	if (idr) cache_reset(s);
	if (!s->cache_ok) return;
	if (s->ncache >= CACHE_FRAMES || s->cache_bytes + len > s->cache_max) { s->cache_ok = 0; return; }
	s->cache[s->ncache].d = malloc(len);
	if (!s->cache[s->ncache].d) { s->cache_ok = 0; return; }
	memcpy(s->cache[s->ncache].d, d, len);
	s->cache[s->ncache].len = len; s->cache[s->ncache].ts = ts;
	s->ncache++; s->cache_bytes += len;
}


/* ---- MD5 (for RTSP Digest) and Base64 decoding (for Basic) ---- */
struct md5 { uint32_t a, b, c, d; uint64_t n; unsigned char buf[64]; };

static const uint32_t K5[64] = {
	0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
	0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
	0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
	0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
	0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
	0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
	0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
	0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391 };
static const unsigned char R5[64] = {
	7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
	4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21 };

static void md5_block(struct md5 *m, const unsigned char *p)
{
	uint32_t w[16], a = m->a, b = m->b, c = m->c, d = m->d;
	int i;

	for (i = 0; i < 16; i++) w[i] = p[i * 4] | p[i * 4 + 1] << 8 | p[i * 4 + 2] << 16 | (uint32_t)p[i * 4 + 3] << 24;
	for (i = 0; i < 64; i++) {
		uint32_t f, t;
		int g;

		if (i < 16) { f = (b & c) | (~b & d); g = i; }
		else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) & 15; }
		else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) & 15; }
		else { f = c ^ (b | ~d); g = (7 * i) & 15; }
		t = d; d = c; c = b;
		f = a + f + K5[i] + w[g];
		b = b + ((f << R5[i]) | (f >> (32 - R5[i])));
		a = t;
	}
	m->a += a; m->b += b; m->c += c; m->d += d;
}

static void md5_init(struct md5 *m) { m->a = 0x67452301; m->b = 0xefcdab89; m->c = 0x98badcfe; m->d = 0x10325476; m->n = 0; }

static void md5_add(struct md5 *m, const void *d, size_t n)
{
	const unsigned char *p = d;

	while (n--) {
		m->buf[m->n++ & 63] = *p++;
		if (!(m->n & 63)) md5_block(m, m->buf);
	}
}

static void md5_hex(struct md5 *m, char *out)
{
	uint64_t bits = m->n * 8;
	unsigned char z = 0x80, pad = 0, r[16];
	uint32_t v[4];
	int i;

	md5_add(m, &z, 1);
	while ((m->n & 63) != 56) md5_add(m, &pad, 1);
	for (i = 0; i < 8; i++) { unsigned char c = bits >> (8 * i); md5_add(m, &c, 1); }
	v[0] = m->a; v[1] = m->b; v[2] = m->c; v[3] = m->d;
	for (i = 0; i < 16; i++) r[i] = v[i / 4] >> (8 * (i % 4));
	for (i = 0; i < 16; i++) { out[i * 2] = "0123456789abcdef"[r[i] >> 4]; out[i * 2 + 1] = "0123456789abcdef"[r[i] & 15]; }
	out[32] = 0;
}

static void md5s(char *out, int n, const char *a, const char *b, const char *c)
{
	struct md5 m;
	const char *p[3] = { a, b, c };

	md5_init(&m);
	for (int i = 0; i < n; i++) {
		if (i) md5_add(&m, ":", 1);
		md5_add(&m, p[i], strlen(p[i]));
	}
	md5_hex(&m, out);
}

static int b64dec(char *o, int osz, const char *s)
{
	int k = 0, acc = 0, bits = 0;

	for (; *s && *s != '='; s++) {
		const char *q = strchr(b64t, *s);

		if (!q) continue;
		acc = acc << 6 | (int)(q - b64t); bits += 6;
		if (bits >= 8) { bits -= 8; if (k < osz - 1) o[k++] = (acc >> bits) & 255; }
	}
	o[k] = 0;
	return k;
}

/* ---- authentication: user and password from a file (one password for the camera); none = open ---- */
static char au_user[64] = "root", au_pass[128];
static int au_on;

static const char *hdr(const char *req, const char *name, char *o, int osz);

static int field(const char *h, const char *key, char *o, int osz)
{
	const char *p = strstr(h, key);
	int n = 0;

	if (!p) return 0;
	p += strlen(key);
	if (*p == '"') { p++; while (*p && *p != '"' && n < osz - 1) o[n++] = *p++; }
	else while (*p && *p != ',' && *p != ' ' && *p != '\r' && n < osz - 1) o[n++] = *p++;
	o[n] = 0;
	return 1;
}

static int auth_ok(const char *req, const char *method, const char *nonce)
{
	char a[512];

	if (!au_on) return 1;
	if (!hdr(req, "Authorization", a, sizeof a)) return 0;
	if (!strncasecmp(a, "Basic ", 6)) {
		char d[200], want[200];

		b64dec(d, sizeof d, a + 6);
		snprintf(want, sizeof want, "%s:%s", au_user, au_pass);
		return !strcmp(d, want);
	}
	if (!strncasecmp(a, "Digest ", 7)) {
		char u[64], n[64], uri[256], resp[40], ha1[33], ha2[33], exp[33];

		if (!field(a, "username=", u, sizeof u) || !field(a, "nonce=", n, sizeof n) ||
		    !field(a, "uri=", uri, sizeof uri) || !field(a, "response=", resp, sizeof resp))
			return 0;
		if (strcmp(u, au_user) || strcmp(n, nonce)) return 0;
		md5s(ha1, 3, au_user, "TC100", au_pass);
		md5s(ha2, 2, method, uri, "");
		{
			struct md5 m;

			md5_init(&m);
			md5_add(&m, ha1, 32); md5_add(&m, ":", 1); md5_add(&m, n, strlen(n)); md5_add(&m, ":", 1); md5_add(&m, ha2, 32);
			md5_hex(&m, exp);
		}
		return !strcmp(exp, resp);
	}
	return 0;
}

/* ---- RTSP clients ---- */
struct cli {
	int fd;
	int playing, wait_idr;
	int si, described;		/* stream (0 main, 1 sub), chosen by DESCRIBE (or SETUP without it) */
	uint32_t peer;			/* client IPv4 address, network order */
	int tcp;			/* interleaved over the RTSP connection */
	int ch;				/* RTP channel when interleaved */
	struct sockaddr_in udp;		/* client RTP address */
	uint16_t seq;
	int a_ok, a_ch;			/* audio track set up, its interleaved channel */
	struct sockaddr_in a_udp;	/* client audio RTP address */
	uint16_t a_seq;
	int v_set;			/* video track set up (a client that set up only the backchannel gets no video) */
	int b_ok, b_tcp, b_ch;		/* backchannel (the client's sound for the speaker) set up, over TCP on channel b_ch */
	struct sockaddr_in b_udp;	/* its RTP source address (UDP) */
	char sess[16];
	char nonce[24];
	char buf[4096];
	int blen;
	time_t last;
	unsigned char *q;		/* output queue (non-blocking socket) */
	int qlen, qpos, qcap;
	time_t qprog;
	unsigned long dropped;
};
static struct cli cl[MAXCLI];
static int udpfd = -1;
static int talk_cfg = 1;		/* RTSP_LITE_TALK of boot.conf (anything but 0, no, off, false) */
static uint16_t srv_rtp = 5004;
static const uint32_t SSRC = 0x54433130;	/* "TC10" */

static void cli_close(struct cli *c)
{
	if (c->b_ok) talk_release((int)(c - cl));
	if (c->fd >= 0) close(c->fd);
	free(c->q);
	memset(c, 0, sizeof *c);
	c->fd = -1;
}

/* output queue: the socket is non-blocking; a slow client never stalls the encoder, it just skips to the next IDR */
static int qfree(struct cli *c) { return QMAX - (c->qlen - c->qpos); }

static int qsend(struct cli *c, const void *p, int n)
{
	if (c->qpos && c->qpos == c->qlen) c->qpos = c->qlen = 0;
	if (c->qlen + n > c->qcap) {
		int nc = c->qcap ? c->qcap : 16384;
		unsigned char *nq;

		if (c->qpos) {			/* compact first */
			memmove(c->q, c->q + c->qpos, c->qlen - c->qpos);
			c->qlen -= c->qpos; c->qpos = 0;
		}
		while (nc < c->qlen + n) nc *= 2;
		if (nc > QMAX + 4096) nc = QMAX + 4096;
		if (c->qlen + n > nc) return -1;
		if (nc > c->qcap) {
			nq = realloc(c->q, nc);
			if (!nq) return -1;
			c->q = nq; c->qcap = nc;
		}
	}
	memcpy(c->q + c->qlen, p, n);
	c->qlen += n;
	return 0;
}

/* push the queue out; returns -1 when the connection is gone */
static int qflush(struct cli *c)
{
	while (c->qpos < c->qlen) {
		int r = send(c->fd, c->q + c->qpos, c->qlen - c->qpos, MSG_NOSIGNAL);

		if (r < 0) {
			if (errno == EINTR) continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) return 0;
			return -1;
		}
		c->qpos += r;
		c->qprog = time(NULL);
	}
	c->qpos = c->qlen = 0;
	c->qprog = time(NULL);
	return 0;
}

static int rtp_out(struct cli *c, const unsigned char *hdr12, const unsigned char *pl, int n)
{
	unsigned char pk[16 + RTP_PAYLOAD + 64];

	memcpy(pk + 4, hdr12, 12);
	memcpy(pk + 16, pl, n);
	if (c->tcp) {
		pk[0] = '$'; pk[1] = c->ch; pk[2] = (12 + n) >> 8; pk[3] = (12 + n) & 255;
		return qsend(c, pk, 16 + n);
	}
	return sendto(udpfd, pk + 4, 12 + n, 0, (struct sockaddr *)&c->udp, sizeof c->udp) < 0 ? -1 : 0;
}

/* ---- audio: microphone (ALSA, via arecord) -> G.711 A-law -> RTP PT 8, 8 kHz mono, 20 ms per packet ----
 * arecord runs only while it is needed: an audio client plays, or the sound detection is on (level meter below). */
static int audio_on;
static pid_t aud_pid = -1, aud_dead = -1;	/* arecord, and the one stopped but not yet reaped */
static time_t aud_dead_t, aud_unneeded;
static int aud_fd = -1, aud_odd = -1, aud_tx, aud_gap;
static time_t aud_retry;
static uint32_t aud_ts = 0x1234;
static unsigned char aud_buf[160 * 2];
static int aud_n;

/* ---- sound level for the sound detection (the 2.x libtc100fix meter, same file format) ----
 * When config/sound_detection.conf has ENABLE=1, the level file (-S, default /var/run/sound_level) is rewritten every
 * 0.25 s: "<epoch> <rms_dbfs> <peak_dbfs> <events> <last_event_epoch> <last_event_dbfs>", RMS and peak of the last
 * 0.25 s around the mean (no DC offset). An event is a second whose RMS reaches the threshold (dBFS, read every 10 s
 * from <file>.threshold, written by controlscripts/sound-detection; default -30): the daemon may poll slowly and still
 * count every loud second (MIN_LOUD_SECONDS). */
static const char *snd_file = "/var/run/sound_level";
static int snd_on, snd_thr = -30, snd_last_db = -96;
static struct lvl snd_w, snd_s;
static unsigned long snd_events;
static long snd_last_ev;
static time_t snd_thr_read;

static void snd_window(void)
{
	char line[96], tf[128];
	time_t now = time(NULL);
	int n;

	lvl_merge(&snd_s, &snd_w);
	if (snd_s.n >= 8000) {			/* one second */
		int db = lvl_rms_db(&snd_s);

		if (now - snd_thr_read >= 10) {
			FILE *f;

			snprintf(tf, sizeof tf, "%s.threshold", snd_file);
			if ((f = fopen(tf, "r"))) {
				char b[16];

				if (fgets(b, sizeof b, f)) { int t = atoi_(b); if (t <= 0 && t >= -90) snd_thr = t; }
				fclose(f);
			}
			snd_thr_read = now;
		}
		if (db >= snd_thr) { snd_events++; snd_last_ev = (long)now; snd_last_db = db; }
		lvl_reset(&snd_s);
	}
	n = snprintf(line, sizeof line, "%ld %d %d %lu %ld %d\n", (long)now, lvl_rms_db(&snd_w), lvl_peak_db(&snd_w),
		     snd_events, snd_last_ev, snd_last_db);
	wfile(snd_file, line, n);
	lvl_reset(&snd_w);
}

static void snd_reload(void)
{
	char v[16];
	int on = cfg_get(CONF "sound_detection.conf", "", "ENABLE", v, sizeof v) && truthy(v);

	if (on != snd_on) {
		LOG("sound level: %s (%s)\n", on ? "on" : "off", snd_file);
		lvl_reset(&snd_w); lvl_reset(&snd_s);
		snd_thr_read = 0;
	}
	snd_on = on;
}

static unsigned char alaw(int s)
{
	int mask = 0xD5, e, m;

	if (s < 0) { mask = 0x55; s = -s - 1; }
	if (s > 32767) s = 32767;
	if (s < 256) return ((s >> 4) ^ mask) & 0xff;
	for (e = 1; e < 7 && s >= (512 << (e - 1)); e++) ;
	m = (s >> (e + 3)) & 0x0f;
	return (((e << 4) | m) ^ mask) & 0xff;
}

/* start arecord on a pipe (vfork + exec, no shell; the child closes our sockets and devices) */
static void aud_open(void)
{
	int p[2];
	pid_t pid;

	aud_retry = time(NULL) + 5;
	if (pipe(p)) { LOG("audio: pipe: %s\n", strerror(errno)); return; }
	pid = vfork();
	if (pid == 0) {
		int i = open("/dev/null", O_WRONLY);

		dup2(p[1], 1);
		if (i >= 0) dup2(i, 2);
		for (i = 3; i < 256; i++) close(i);
		execlp("arecord", "arecord", "-q", "-D", "hw:0,0", "-f", "S16_LE", "-r", "8000", "-c", "1", "-t", "raw", (char *)NULL);
		_exit(127);
	}
	close(p[1]);
	if (pid < 0) { close(p[0]); LOG("audio: arecord failed: %s\n", strerror(errno)); return; }
	aud_pid = pid; aud_fd = p[0];
	fcntl(aud_fd, F_SETFL, fcntl(aud_fd, F_GETFL) | O_NONBLOCK);
	aud_n = 0; aud_odd = -1; aud_gap = 1;
	lvl_reset(&snd_w); lvl_reset(&snd_s);
}

/* stop arecord without waiting for it (reaped later by aud_reap) */
static void aud_close(void)
{
	if (aud_fd >= 0) close(aud_fd);
	aud_fd = -1;
	if (aud_pid > 0) {
		kill(aud_pid, SIGTERM);
		if (aud_dead > 0) waitpid(aud_dead, NULL, WNOHANG);
		aud_dead = aud_pid; aud_dead_t = time(NULL);
	}
	aud_pid = -1;
}

static void aud_reap(void)
{
	if (aud_dead > 0) {
		if (waitpid(aud_dead, NULL, WNOHANG) != 0) aud_dead = -1;
		else if (time(NULL) - aud_dead_t > 3) kill(aud_dead, SIGKILL);
	}
	if (aud_pid > 0 && waitpid(aud_pid, NULL, WNOHANG) == aud_pid) {	/* arecord died by itself */
		aud_pid = -1;
		if (aud_fd >= 0) { close(aud_fd); aud_fd = -1; }
	}
}

static void aud_send(const unsigned char *pl, int n)
{
	for (int i = 0; i < MAXCLI; i++) {
		struct cli *c = &cl[i];
		unsigned char pk[4 + 12 + 160];

		if (c->fd < 0 || !c->playing || !c->a_ok) continue;
		pk[4] = 0x80; pk[5] = 8;
		pk[6] = c->a_seq >> 8; pk[7] = c->a_seq & 255; c->a_seq++;
		pk[8] = aud_ts >> 24; pk[9] = aud_ts >> 16; pk[10] = aud_ts >> 8; pk[11] = aud_ts;
		pk[12] = (SSRC + 1) >> 24; pk[13] = ((SSRC + 1) >> 16) & 255; pk[14] = ((SSRC + 1) >> 8) & 255; pk[15] = (SSRC + 1) & 255;
		memcpy(pk + 16, pl, n);
		if (c->tcp) {
			if (qfree(c) < 4096) continue;	/* congested: audio is dropped before video is */
			pk[0] = '$'; pk[1] = c->a_ch; pk[2] = (12 + n) >> 8; pk[3] = (12 + n) & 255;
			if (qsend(c, pk, 16 + n) || qflush(c)) cli_close(c);
		} else {
			sendto(udpfd, pk + 4, 12 + n, 0, (struct sockaddr *)&c->a_udp, sizeof c->a_udp);
		}
	}
	aud_ts += n;
}

static uint64_t now_us64(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000000ULL + (uint64_t)t.tv_nsec / 1000;
}

static void aud_pump(void)
{
	unsigned char raw[1024];
	int r;

	while ((r = read(aud_fd, raw, sizeof raw)) > 0) {
		int rec_a = rec_audio_wanted();
		uint64_t tus = rec_a ? now_us64() : 0;
		unsigned char pcm[sizeof raw + 2];
		int pn = 0;

		for (int i = 0; i < r; i++) {
			int s;

			if (aud_odd < 0) { aud_odd = raw[i]; continue; }
			s = (int16_t)(aud_odd | (raw[i] << 8));
			aud_odd = -1;
			pcm[pn++] = (unsigned char)s; pcm[pn++] = (unsigned char)((unsigned)s >> 8);
			if (snd_on) { lvl_add(&snd_w, s); if (snd_w.n >= 2000) snd_window(); }
			if (aud_tx || rec_a) {
				aud_buf[aud_n++] = alaw(s);
				if (aud_n == 160) {
					if (aud_tx) aud_send(aud_buf, 160);
					if (rec_a) { rec_audio(aud_buf, 160, tus, aud_gap); aud_gap = 0; }
					aud_n = 0;
				}
			}
		}
		if (pn) lis_write(pcm, pn);
	}
	if (r == 0 || (r < 0 && errno != EAGAIN && errno != EINTR)) aud_close();
}

static int send_pkt(struct cli *c, uint32_t ts, int marker, const unsigned char *pl, int n)
{
	unsigned char h[12];
	uint32_t ssrc = S[c->si].ssrc;

	h[0] = 0x80; h[1] = (marker ? 0x80 : 0) | 96;
	h[2] = c->seq >> 8; h[3] = c->seq & 255; c->seq++;
	h[4] = ts >> 24; h[5] = ts >> 16; h[6] = ts >> 8; h[7] = ts;
	h[8] = ssrc >> 24; h[9] = ssrc >> 16; h[10] = ssrc >> 8; h[11] = ssrc;
	return rtp_out(c, h, pl, n);
}

/* one NAL unit as one packet or FU fragments (FU-A for H.264, RFC 7798 FU for H.265) */
static int send_nal(struct cli *c, uint32_t ts, const unsigned char *nal, int len, int last)
{
	int hevc = S[c->si].hevc;

	if (len <= RTP_PAYLOAD)
		return send_pkt(c, ts, last, nal, len);
	{
		unsigned char fu[RTP_PAYLOAD + 3];
		int hl = hevc ? 2 : 1, ph = hevc ? 3 : 2, off = hl, first = 1;

		while (off < len) {
			int n = len - off > RTP_PAYLOAD - ph ? RTP_PAYLOAD - ph : len - off;
			int end = off + n >= len;

			if (hevc) {
				fu[0] = (nal[0] & 0x81) | (49 << 1);
				fu[1] = nal[1];
				fu[2] = (first ? 0x80 : 0) | (end ? 0x40 : 0) | ((nal[0] >> 1) & 63);
			} else {
				fu[0] = (nal[0] & 0xe0) | 28;
				fu[1] = (first ? 0x80 : 0) | (end ? 0x40 : 0) | (nal[0] & 31);
			}
			memcpy(fu + ph, nal + off, n);
			if (send_pkt(c, ts, last && end, fu, n + ph)) return -1;
			off += n; first = 0;
		}
	}
	return 0;
}

/* VPS (H.265), SPS and PPS in band */
static int send_ps(struct cli *c, uint32_t ts)
{
	struct strm *s = &S[c->si];

	if (s->hevc && send_nal(c, ts, s->vps, s->vps_len, 0)) return -1;
	return send_nal(c, ts, s->sps, s->sps_len, 0) || send_nal(c, ts, s->pps, s->pps_len, 0);
}

static int send_frame(struct cli *c, const unsigned char *d, int n, uint32_t ts)
{
	const struct strm *st = &S[c->si];
	int pos = 0, l, s;
	struct { int s, l; } nl[16];
	int k = 0, i;

	while (k < 16 && (s = next_nal(d, n, pos, &l)) >= 0) {
		int t = NT(st, d[s]);

		pos = s + l;
		if (t == (st->hevc ? 35 : 9)) continue;		/* access unit delimiter */
		nl[k].s = s; nl[k].l = l; k++;
	}
	for (i = 0; i < k; i++)
		if (send_nal(c, ts, d + nl[i].s, nl[i].l, i == k - 1)) return -1;
	return 0;
}

/* queue space a frame needs: payload, RTP/interleave headers per packet, parameter sets */
static int frame_need(int n) { return n + (n / (RTP_PAYLOAD - 2) + 12) * 18 + 400; }

static void bcast(int si, const unsigned char *d, int n, uint32_t ts, int idr)
{
	for (int i = 0; i < MAXCLI; i++) {
		struct cli *c = &cl[i];

		if (c->fd < 0 || !c->playing || c->si != si || (c->b_ok && !c->v_set)) continue;
		if (c->wait_idr && !idr) continue;
		if (c->tcp && qfree(c) < frame_need(n)) {	/* congested: skip this frame, resume at the next IDR */
			c->wait_idr = 1;
			c->dropped++;
			continue;
		}
		c->wait_idr = 0;
		if (idr && HAVE_PS(&S[si])) {	/* parameter sets in band before every IDR that lacks them */
			if (send_ps(c, ts)) { cli_close(c); continue; }
		}
		if (send_frame(c, d, n, ts) || (c->tcp && qflush(c))) cli_close(c);
	}
}

static void reply(struct cli *c, int code, const char *txt, int cseq, const char *extra, const char *body)
{
	char b[2048];
	int n = snprintf(b, sizeof b, "RTSP/1.0 %d %s\r\nCSeq: %d\r\nServer: tc100-rtsp\r\n%s", code, txt, cseq, extra ? extra : "");

	if (body)
		n += snprintf(b + n, sizeof b - n, "Content-Type: application/sdp\r\nContent-Length: %d\r\n\r\n%s", (int)strlen(body), body);
	else
		n += snprintf(b + n, sizeof b - n, "\r\n");
	if (qsend(c, b, n) || qflush(c)) cli_close(c);
}

static const char *hdr(const char *req, const char *name, char *o, int osz)
{
	const char *p = req;
	int nl = strlen(name);

	while ((p = strstr(p, "\r\n")) != NULL) {
		p += 2;
		if (!strncasecmp(p, name, nl) && p[nl] == ':') {
			const char *v = p + nl + 1, *e;

			while (*v == ' ') v++;
			e = strstr(v, "\r\n");
			if (!e) e = v + strlen(v);
			snprintf(o, osz, "%.*s", (int)(e - v), v);
			return o;
		}
	}
	return NULL;
}

static void play_burst(struct cli *c)
{
	struct strm *s = &S[c->si];
	int need = 400;

	if (c->b_ok && !c->v_set) return;

	for (int i = 0; i < s->ncache; i++) need += frame_need(s->cache[i].len);
	if (s->cache_ok && s->ncache && (!c->tcp || qfree(c) > need)) {
		if (HAVE_PS(s) && send_ps(c, s->cache[0].ts)) { cli_close(c); return; }
		for (int i = 0; i < s->ncache; i++)
			if (send_frame(c, s->cache[i].d, s->cache[i].len, s->cache[i].ts)) { cli_close(c); return; }
		if (c->tcp && qflush(c)) { cli_close(c); return; }
		c->wait_idr = 0;
	} else {
		c->wait_idr = 1;
	}
}

/* two-way audio: on in boot.conf (RTSP_LITE_TALK, default on) and only with the RTSP password: without one, anybody on the
 * network could talk through the camera's speaker */
static int talk_enabled(void) { return talk_cfg && au_on; }

static void handle(struct cli *c, char *req, int cseq_default)
{
	char m[16] = "", url[256] = "", v[300], ex[512];
	int cseq = cseq_default;
	struct sockaddr_in me;
	socklen_t ml = sizeof me;
	char host[32] = "0.0.0.0";

	{	/* "METHOD URL RTSP/1.0" */
		int i = 0, j = 0;

		while (req[i] && req[i] != ' ' && i < 15) { m[i] = req[i]; i++; }
		m[i] = 0;
		while (req[i] == ' ') i++;
		while (req[i] && req[i] != ' ' && req[i] != '\r' && j < 255) url[j++] = req[i++];
		url[j] = 0;
	}
	if (hdr(req, "CSeq", v, sizeof v)) cseq = num(v);
	if (!getsockname(c->fd, (struct sockaddr *)&me, &ml)) inet_ntop(AF_INET, &me.sin_addr, host, sizeof host);
	c->last = time(NULL);

	if (au_on && strcmp(m, "OPTIONS") && !auth_ok(req, m, c->nonce)) {
		char ch[400];

		if (!c->nonce[0]) snprintf(c->nonce, sizeof c->nonce, "%08x%08x", (unsigned)time(NULL), (unsigned)(c - cl) * 2654435761u ^ (unsigned)(uintptr_t)c);
		snprintf(ch, sizeof ch, "WWW-Authenticate: Digest realm=\"TC100\", nonce=\"%s\"\r\nWWW-Authenticate: Basic realm=\"TC100\"\r\n", c->nonce);
		reply(c, 401, "Unauthorized", cseq, ch, NULL);
		return;
	}
	if (!strcmp(m, "OPTIONS")) {
		reply(c, 200, "OK", cseq, "Public: OPTIONS, DESCRIBE, SETUP, PLAY, PAUSE, TEARDOWN, GET_PARAMETER\r\n", NULL);
	} else if (!strcmp(m, "DESCRIBE")) {
		char sdp[1536], base[300], fm[600];
		struct strm *s;

		if (!c->playing) { c->si = S[1].on && url_is_sub(url); c->described = 1; }
		s = &S[c->si];
		if (!HAVE_PS(s)) { reply(c, 503, "Service Unavailable", cseq, NULL, NULL); return; }
		if (s->hevc) snprintf(fm, sizeof fm, "%s", s->sprop);
		else snprintf(fm, sizeof fm, "packetization-mode=1;profile-level-id=%s;sprop-parameter-sets=%s", s->plid, s->sprop);
		snprintf(base, sizeof base, "Content-Base: %s%s\r\n", url, url[strlen(url) - 1] == '/' ? "" : "/");
		snprintf(sdp, sizeof sdp,
			 "v=0\r\no=- 1 1 IN IP4 %s\r\ns=TC100\r\nc=IN IP4 0.0.0.0\r\nt=0 0\r\na=control:*\r\n"
			 "m=video 0 RTP/AVP 96\r\na=rtpmap:96 %s/90000\r\n"
			 "a=fmtp:96 %s\r\na=control:track1\r\n",
			 host, s->hevc ? "H265" : "H264", fm);
		if (audio_on) strncat(sdp, "m=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\na=control:track2\r\n", sizeof sdp - strlen(sdp) - 1);
		if (talk_enabled() && hdr(req, "Require", v, sizeof v) && strstr(v, "backchannel"))	/* ONVIF backchannel: the client sends here */
			strncat(sdp, "m=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\na=control:track3\r\na=sendonly\r\n", sizeof sdp - strlen(sdp) - 1);
		reply(c, 200, "OK", cseq, base, sdp);
	} else if (!strcmp(m, "SETUP")) {
		char tr[300];

		if (!hdr(req, "Transport", tr, sizeof tr)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
		if (!c->described && !c->playing) c->si = S[1].on && url_is_sub(url);	/* SETUP without DESCRIBE */
		if (!c->sess[0]) snprintf(c->sess, sizeof c->sess, "%08x", (unsigned)(time(NULL) ^ (c - cl) * 7919));
		if (talk_enabled() && strstr(url, "track3")) {	/* backchannel: sound from the client to the speaker */
			if (strstr(tr, "TCP")) {
				char *q = strstr(tr, "interleaved=");

				c->b_tcp = 1; c->b_ch = q ? num(q + 12) : 4;
				snprintf(ex, sizeof ex, "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d\r\nSession: %s;timeout=60\r\n", c->b_ch, c->b_ch + 1, c->sess);
			} else {
				char *q = strstr(tr, "client_port=");
				struct sockaddr_in pe;
				socklen_t pl = sizeof pe;

				if (!q || getpeername(c->fd, (struct sockaddr *)&pe, &pl)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
				c->b_tcp = 0; c->b_udp = pe; c->b_udp.sin_port = htons(num(q + 12));
				snprintf(ex, sizeof ex, "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d\r\nSession: %s;timeout=60\r\n",
					 num(q + 12), num(q + 12) + 1, srv_rtp, srv_rtp + 1, c->sess);
			}
			c->b_ok = 1;
			reply(c, 200, "OK", cseq, ex, NULL);
			return;
		}
		if (audio_on && strstr(url, "track2")) {	/* audio track */
			if (strstr(tr, "TCP")) {
				char *q = strstr(tr, "interleaved=");

				c->tcp = 1; c->a_ch = q ? num(q + 12) : 2;
				snprintf(ex, sizeof ex, "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d\r\nSession: %s;timeout=60\r\n", c->a_ch, c->a_ch + 1, c->sess);
			} else {
				char *q = strstr(tr, "client_port=");
				struct sockaddr_in pe;
				socklen_t pl = sizeof pe;

				if (!q || getpeername(c->fd, (struct sockaddr *)&pe, &pl)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
				c->tcp = 0; c->a_udp = pe; c->a_udp.sin_port = htons(num(q + 12));
				snprintf(ex, sizeof ex, "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d\r\nSession: %s;timeout=60\r\n",
					 num(q + 12), num(q + 12) + 1, srv_rtp, srv_rtp + 1, c->sess);
			}
			c->a_seq = (uint16_t)(time(NULL) * 17);
			c->a_ok = 1;
			reply(c, 200, "OK", cseq, ex, NULL);
			return;
		}
		if (strstr(tr, "TCP")) {
			char *q = strstr(tr, "interleaved=");

			c->tcp = 1; c->ch = q ? num(q + 12) : 0;
			snprintf(ex, sizeof ex, "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d\r\nSession: %s;timeout=60\r\n", c->ch, c->ch + 1, c->sess);
		} else {
			char *q = strstr(tr, "client_port=");
			struct sockaddr_in pe;
			socklen_t pl = sizeof pe;

			if (!q || getpeername(c->fd, (struct sockaddr *)&pe, &pl)) { reply(c, 461, "Unsupported Transport", cseq, NULL, NULL); return; }
			c->tcp = 0; c->udp = pe; c->udp.sin_port = htons(num(q + 12));
			snprintf(ex, sizeof ex, "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d\r\nSession: %s;timeout=60\r\n",
				 num(q + 12), num(q + 12) + 1, srv_rtp, srv_rtp + 1, c->sess);
		}
		c->seq = (uint16_t)(time(NULL) * 31);
		c->v_set = 1;
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "PLAY")) {
		snprintf(ex, sizeof ex, "Range: npt=0.000-\r\nSession: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
		if (c->fd >= 0) { c->playing = 1; play_burst(c); }
	} else if (!strcmp(m, "PAUSE")) {
		c->playing = 0;
		snprintf(ex, sizeof ex, "Session: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "GET_PARAMETER") || !strcmp(m, "SET_PARAMETER")) {
		snprintf(ex, sizeof ex, "Session: %s\r\n", c->sess);
		reply(c, 200, "OK", cseq, ex, NULL);
	} else if (!strcmp(m, "TEARDOWN")) {
		reply(c, 200, "OK", cseq, NULL, NULL);
		cli_close(c);
	} else {
		reply(c, 501, "Not Implemented", cseq, NULL, NULL);
	}
}

/* read what the client sent: RTSP requests, interleaved RTCP frames are skipped */
static void cli_read(struct cli *c)
{
	int r = recv(c->fd, c->buf + c->blen, sizeof c->buf - 1 - c->blen, 0);

	if (r <= 0) {
		if (r < 0 && (errno == EAGAIN || errno == EINTR)) return;
		cli_close(c);
		return;
	}
	c->blen += r;
	c->buf[c->blen] = 0;
	for (;;) {
		char *e;
		int used;

		if (c->blen >= 4 && (unsigned char)c->buf[0] == '$') {
			int len = 4 + ((unsigned char)c->buf[2] << 8 | (unsigned char)c->buf[3]);

			if (c->blen < len) return;
			if (c->b_ok && c->b_tcp && c->playing && (unsigned char)c->buf[1] == c->b_ch)
				talk_rtp((int)(c - cl), (const unsigned char *)c->buf + 4, len - 4, now_us64());
			memmove(c->buf, c->buf + len, c->blen - len);
			c->blen -= len;
			continue;
		}
		e = strstr(c->buf, "\r\n\r\n");
		if (!e) {
			if (c->blen >= (int)sizeof c->buf - 1) cli_close(c);
			return;
		}
		used = e + 4 - c->buf;
		*e = 0;
		strcat(c->buf, "\r\n");	/* keeps the header scanner happy on the last line */
		handle(c, c->buf, 1);
		if (c->fd < 0) return;
		memmove(c->buf, c->buf + used, c->blen - used);
		c->blen -= used;
		c->buf[c->blen] = 0;
	}
}

/* ---- motion detection: luma grid, ignored zones, sensitivity ---------------------------------------------------
 * On while /tmp/tc100_md exists (setconf -k p 1: controlscripts/motion-detection, the web UI, MQTT) and
 * rtspserver.conf does not say mdenabled=0. 4 times a second the luma of a 64x36 grid is compared with the previous
 * sample, leaving out the cells whose centre lies in a zone of config/motion_zones.conf (as md.c did on 2.x).
 * Sensitivity 1-100: /tmp/tc100_md_sens (setconf -k m), else rtspserver.conf mdsens. /tmp/rec_control gets "1" on
 * motion and "0" 8 s after it stopped: the detection monitor (MQTT event, snapshot, LED) and the recorder read it.
 * /var/run/md_zones: what the detector uses, the 2.x line (action.cgi md_zones_info). */
#define MD_GW 64
#define MD_GH 36
static int md_on, md_conf_on = 1, md_conf_sens = 60, md_sens = 60, md_nz, md_watch = MD_GW * MD_GH, md_motion;
static int md_z[MDZ_MAX][4];
static unsigned char md_mask[MD_GW * MD_GH];
static unsigned md_starts;
static unsigned char md_prev[MD_GW * MD_GH];
static int md_have, md_hits;
static double md_t, md_tlast;

static void md_reload(int conf_changed, int zones_changed)
{
	static int old_z[MDZ_MAX][4], old_nz = -1;
	char v[16];
	int on, sens;
	FILE *f;

	if (conf_changed) {
		md_conf_on = !cfg_get(CONF "rtspserver.conf", "", "mdenabled", v, sizeof v) || v[0] != '0';
		md_conf_sens = cfg_get(CONF "rtspserver.conf", "", "mdsens", v, sizeof v) && v[0] >= '0' && v[0] <= '9' ? atoi_(v) : 60;
	}
	if (zones_changed) {
		char ln[128];

		md_nz = 0;
		if ((f = fopen(CONF "motion_zones.conf", "r"))) {
			while (md_nz < MDZ_MAX && fgets(ln, sizeof ln, f))
				if (mdz_parse_line(ln, md_z[md_nz])) md_nz++;
			fclose(f);
		}
	}
	sens = md_conf_sens;
	if ((f = fopen("/tmp/tc100_md_sens", "r"))) {
		if (fgets(v, sizeof v, f) && v[0] >= '0' && v[0] <= '9') sens = atoi_(v);
		fclose(f);
	}
	if (sens < 1) sens = 1;
	if (sens > 100) sens = 100;
	on = md_conf_on && !access("/tmp/tc100_md", F_OK);
	if (on == md_on && sens == md_sens && md_nz == old_nz && !memcmp(md_z, old_z, sizeof md_z)) return;
	md_sens = sens; old_nz = md_nz; memcpy(old_z, md_z, sizeof md_z);
	if (on) {
		char st[128];
		int n;

		md_watch = mdz_mask(md_mask, MD_GW, MD_GH, md_z, md_nz);
		md_starts++;
		n = snprintf(st, sizeof st, "starts=%u grid=%dx%d sensitivity=%d ignored=%d result=%s\n", md_starts, MD_GW, MD_GH,
			     md_sens, MD_GW * MD_GH - md_watch, md_nz ? "area" : "global");
		wfile("/var/run/md_zones", st, n);
		if (!md_on || old_nz != md_nz) LOG("motion detection on: sensitivity %d, %d zone(s), %d of %d cells watched\n",
						    md_sens, md_nz, md_watch, MD_GW * MD_GH);
	} else if (md_on) {
		LOG("motion detection off\n");
		if (md_motion) wfile("/tmp/rec_control", "0\n", 2);
		md_motion = 0; md_have = 0; md_hits = 0;
	}
	md_on = on;
}

static void md_frame(const unsigned char *sy, double tn)
{
	unsigned char cur[MD_GW * MD_GH];
	int x, y, n = 0, chg = 0;

	if (tn - md_t < 0.25) return;
	md_t = tn;
	if (!md_on) { md_have = 0; return; }
	for (y = 0; y < MD_GH; y++)
		for (x = 0; x < MD_GW; x++) cur[n++] = sy[(y * 30 + 15) * W + x * 30 + 15];
	if (md_have) {
		for (n = 0; n < MD_GW * MD_GH; n++)
			if (md_mask[n]) { int d = cur[n] - md_prev[n]; if (d < 0) d = -d; if (d > 20) chg++; }
		if (md_triggered(chg, md_watch, md_sens)) md_hits++; else md_hits = 0;
		if (md_hits >= 2) { md_tlast = tn; if (!md_motion) { md_motion = 1; wfile("/tmp/rec_control", "1\n", 2); } }
	}
	memcpy(md_prev, cur, sizeof cur); md_have = 1;
	if (md_motion && tn - md_tlast > 8.0) { md_motion = 0; wfile("/tmp/rec_control", "0\n", 2); }
}

/* ---- local recording (rec.c): settings of boot.conf, as on 2.x (Settings -> Recording) -------------------------
 * REC_LOCAL=1 turns it on (controlscripts/recording start|stop writes it); REC_WHEN=offline|always|motion;
 * REC_STREAM=main|sub; REC_SEGMENT_SEC, REC_RESERVE_MB, REC_OFFLINE_SEC, REC_POSTROLL_SEC, REC_RING_KB;
 * REC_CLIENT = the recorder's IPv4 address, else the host of FRIGATE_URL (config/frigate_live.conf), else any client.
 * Read again whenever boot.conf changes: no restart needed. */
static const char *rec_dir = "/mnt/DCIM";
static int rec_sub, rec_mode;
static uint32_t rec_client;		/* network order, 0 = any client */
static time_t snd_pulse;		/* sound event for the motion recording (controlscripts/sound-detection) */

static int cfg_num(const char *file, const char *key, int def)
{
	char v[32];

	return cfg_get(file, "", key, v, sizeof v) && v[0] >= '0' && v[0] <= '9' ? atoi_(v) : def;
}

static uint32_t ip_of(const char *v)	/* dotted quad, alone or as the host of a URL; 0 when none */
{
	const char *p = strstr(v, "://");
	char h[32];
	int i = 0;
	struct in_addr a;

	p = p ? p + 3 : v;
	while (*p && *p != ':' && *p != '/' && i < 31) h[i++] = *p++;
	h[i] = 0;
	for (i = 0; h[i]; i++) if (h[i] != '.' && (h[i] < '0' || h[i] > '9')) return 0;
	return h[0] && inet_aton(h, &a) ? a.s_addr : 0;
}

static void rec_reload(void)
{
	static struct rec_cfg last;
	static const char *mn[] = { "off", "always", "offline (while the recorder does not receive the stream)", "motion" };
	struct rec_cfg rc;
	char v[200];
	const char *bc = CONF "boot.conf";

	memset(&rc, 0, sizeof rc);
	snprintf(rc.dir, sizeof rc.dir, "%s", rec_dir);
	snprintf(rc.status, sizeof rc.status, "/var/run/tc100rec");
	if (cfg_get(bc, "", "REC_LOCAL", v, sizeof v) && truthy(v)) {
		rc.mode = REC_OFFLINE;
		if (cfg_get(bc, "", "REC_WHEN", v, sizeof v))
			rc.mode = !strcmp(v, "always") ? REC_ALWAYS : !strcmp(v, "motion") ? REC_MOTION : REC_OFFLINE;
	}
	rc.segment_s = cfg_num(bc, "REC_SEGMENT_SEC", 300);
	rc.reserve_mb = cfg_num(bc, "REC_RESERVE_MB", 256);
	rc.offline_s = cfg_num(bc, "REC_OFFLINE_SEC", 5);
	rc.postroll_s = cfg_num(bc, "REC_POSTROLL_SEC", 30);
	rc.ring_kb = cfg_num(bc, "REC_RING_KB", 1024);
	rc.audio = cfg_num(bc, "REC_AUDIO", 1) != 0;
	rec_sub = cfg_get(bc, "", "REC_STREAM", v, sizeof v) && !strcmp(v, "sub");
	rec_client = 0;
	if (cfg_get(bc, "", "REC_CLIENT", v, sizeof v) && v[0]) rec_client = ip_of(v);
	else if (cfg_get(CONF "frigate_live.conf", "", "FRIGATE_URL", v, sizeof v)) rec_client = ip_of(v);
	rec_mode = rc.mode;
	if (!memcmp(&rc, &last, sizeof rc)) return;
	last = rc;
	if (rc.mode != REC_OFF || rec_active())
		LOG("recording: %s, %s stream, %s, %d s files, keep %d MB free, into %s\n", mn[rc.mode & 3], rec_sub ? "sub" : "main",
		    rc.audio ? "with sound (G.711 A-law)" : "no sound", rc.segment_s, rc.reserve_mb, rc.dir);
	rec_config(&rc);
}

/* someone receives the stream (for REC_WHEN=offline): a playing client, not local, from REC_CLIENT when set, whose
 * data flows (a recorder that lost the network keeps its TCP connection open for a while; its queue gives it away) */
static int rec_watched(void)
{
	time_t now = time(NULL);

	for (int i = 0; i < MAXCLI; i++) {
		const struct cli *c = &cl[i];
		const unsigned char *ip = (const unsigned char *)&c->peer;

		if (c->fd < 0 || !c->playing || ip[0] == 127) continue;
		if (rec_client && c->peer != rec_client) continue;
		if (c->tcp && c->qpos < c->qlen && now - c->qprog >= 3) continue;
		return 1;
	}
	return 0;
}

/* ---- encoders ---- */
static void pool_log(const struct strm *s)
{
	unsigned long (*gf)(void) = (unsigned long (*)(void))dlsym(RTLD_DEFAULT, "akuio_get_free_pmem");
	unsigned long (*gu)(void) = (unsigned long (*)(void))dlsym(RTLD_DEFAULT, "akuio_get_used_pmem");

	LOG("encoder %s %dx%d %s %u kbit/s (channel %u group %u): %s; pool used %lu, free %lu\n", s->name, s->w, s->h,
	    s->pa.codec == 2 ? "H.265" : "H.264", s->pa.kbps, s->pa.size_class, s->pa.group, s->enc ? "open" : "OPEN FAILED",
	    gu ? gu() : 0UL, gf ? gf() : 0UL);
}

static int strm_reopen(struct strm *s)
{
	if (s->enc) p_close(s->enc);
	s->enc = p_open(&s->pa);
	s->nsent = 0; s->fails = 0;
	if (!s->enc) pool_log(s);
	return s->enc != NULL;
}

/* the sub-stream stops for good (open failed, no frames): its clients are closed, they reconnect to the main one */
static void sub_off(const char *why)
{
	struct strm *s = &S[1];

	if (!s->on) return;
	LOG("sub-stream off (%s): the sub-stream paths serve the main stream from now on\n", why);
	if (s->enc) p_close(s->enc);
	s->enc = NULL; s->on = 0; s->active = 0;
	cache_reset(s);
	for (int i = 0; i < MAXCLI; i++) if (cl[i].fd >= 0 && cl[i].si == 1) cli_close(&cl[i]);
}

static void sub_start(int want)
{
	struct strm *s = &S[1];

	if (!want) { LOG("sub-stream off (-s 0): every path serves the main stream\n"); return; }
	s->enc = p_open(&s->pa);
	pool_log(s);
	if (!s->enc) { LOG("sub-stream: the encoder did not open; the sub-stream paths serve the main stream\n"); return; }
	s->on = 1; s->active = 1; s->nsent = 0; s->fails = 0;
}

/* ---- settings read while running (every 2 s: a stat() per file) ---- */
static void cfg_reload(double tn)
{
	static const char *fn[6] = { CONF "boot.conf", CONF "isp_tune.conf", CONF "rtspserver.conf",
				     CONF "sound_detection.conf", CONF "motion_zones.conf", CONF "frigate_live.conf" };
	static time_t mt[6];
	static off_t sz[6];
	static double chk = -10;
	struct stat sb;
	int i, ch[6], pic = 0;

	if (tn - chk < 2.0) return;
	chk = tn;
	for (i = 0; i < 6; i++) {
		time_t m = 0;
		off_t z = 0;

		if (!stat(fn[i], &sb)) { m = sb.st_mtime; z = sb.st_size; }
		ch[i] = m != mt[i] || z != sz[i];
		mt[i] = m; sz[i] = z;
	}
	{ int a = access(CONF "awb.off", F_OK) ? 1 : 0; if (a != p_awb) { p_awb = a; if (!a) p_du = p_dv = 0; pic = 1; } }
	if (pic || ch[0] || ch[1] || ch[2]) post_apply();
	if (ch[0]) {
		char v[16];

		talk_cfg = !(cfg_get(CONF "boot.conf", "", "RTSP_LITE_TALK", v, sizeof v) &&
			     (v[0] == '0' || !strcmp(v, "no") || !strcmp(v, "off") || !strcmp(v, "false")));
	}
	if (ch[0] || ch[5]) rec_reload();
	if (ch[3]) snd_reload();
	md_reload(ch[2], ch[4]);
}

int main(int argc, char **argv)
{
	const char *akuio = "/mnt/sd/tc100test/libakuio.so", *dev = "/dev/video0", *dir = "/mnt/sd/lib";
	const char *pwfile = NULL;
	int o, kbps = 2000, fps = 15, qmin = 25, qmax = 48, port = 554, hevc = 0, sub_on = 1, sub_hevc = 0, sub_kbps = 400;

	for (o = 1; o + 1 < argc; o += 2) {
		const char *a = argv[o], *v = argv[o + 1];

		if (!strcmp(a, "-p")) port = num(v);
		else if (!strcmp(a, "-c")) hevc = !strcmp(v, "h265");
		else if (!strcmp(a, "-b")) kbps = num(v);
		else if (!strcmp(a, "-f")) fps = num(v);
		else if (!strcmp(a, "-q")) qmin = num(v);
		else if (!strcmp(a, "-Q")) qmax = num(v);
		else if (!strcmp(a, "-d")) dev = v;
		else if (!strcmp(a, "-u")) snprintf(au_user, sizeof au_user, "%s", v);
		else if (!strcmp(a, "-w")) pwfile = v;
		else if (!strcmp(a, "-L")) dir = v;
		else if (!strcmp(a, "-A")) akuio = v;
		else if (!strcmp(a, "-a")) audio_on = num(v) != 0;
		else if (!strcmp(a, "-s")) sub_on = num(v) != 0;
		else if (!strcmp(a, "-C")) sub_hevc = !strcmp(v, "h265");
		else if (!strcmp(a, "-B")) sub_kbps = num(v);
		else if (!strcmp(a, "-R")) rec_dir = v;
		else if (!strcmp(a, "-S")) snd_file = v;
		else {
			LOG("usage: tc100_rtsp [-p PORT] [-b KBPS] [-f FPS] [-c h264|h265] [-q QMIN] [-Q QMAX] [-d DEV] [-L LIBDIR]\n");
			LOG("                  [-A libakuio.so] [-u USER] [-w PASSWORD_FILE] [-a 0|1 audio]\n");
			LOG("                  [-s 0|1 sub-stream] [-C h264|h265 sub codec] [-B KBPS sub bit rate]\n");
			LOG("                  [-R RECORD_DIR (/mnt/DCIM)] [-S SOUND_LEVEL_FILE (/var/run/sound_level)]\n");
			return 2;
		}
	}
	if (fps < 1) fps = 1;
	if (sub_kbps < 32) sub_kbps = 32;
	if (pwfile) {	/* first line of the file is the password; an empty or missing file leaves the stream open */
		FILE *pf = fopen(pwfile, "r");

		if (pf) {
			if (fgets(au_pass, sizeof au_pass, pf)) {
				au_pass[strcspn(au_pass, "\r\n")] = 0;
				au_on = au_pass[0] != 0;
			}
			fclose(pf);
		}
	}
	signal(SIGINT, on_sig); signal(SIGTERM, on_sig); signal(SIGPIPE, SIG_IGN);
	lis_init();
	talk_init();

#ifndef TC100_HOST_TEST
	if (access("/etc/jffs2/venc.cfg", F_OK)) {
		FILE *f;

		(void)!mkdir("/etc/jffs2", 0755);
		f = fopen("/etc/jffs2/venc.cfg", "w");
		if (f) fclose(f);
	}
	if (!dlopen(akuio, RTLD_LAZY | RTLD_GLOBAL)) { LOG("dlopen %s: %s\n", akuio, dlerror()); return 2; }
	ld(dir, "libplat_common.so", 0);
	ld(dir, "libplat_thread.so", 1);
	ld(dir, "libplat_drv.so", 0);
	ld(dir, "libplat_ipcsrv.so", 0);
	ld(dir, "libplat_venc_cb.so", 1);
	ld(dir, "libakv_encode.so", 1);
	{
		void *m = ld_venc(dir);

		p_open = dlsym(m, "ak_venc_open");
		p_send = dlsym(m, "ak_venc_send_frame");
		p_release = dlsym(m, "ak_venc_release_stream");
		p_close = dlsym(m, "ak_venc_close");
		p_alloc = dlsym(RTLD_DEFAULT, "akuio_alloc_pmem");
		p_pinit = dlsym(RTLD_DEFAULT, "akuio_pmem_init");
		if (!p_open || !p_send || !p_release || !p_close || !p_alloc) { LOG("missing encoder symbols\n"); return 2; }
	}
	if (p_pinit && p_pinit()) { LOG("akuio_pmem_init failed\n"); return 2; }
#endif

unsigned char *fpb[2] = { NULL, NULL };	/* RTSP_ZEROCOPY: the capture buffers are encoder pool memory */
	int zc = 0;
#ifdef TC100_HOST_TEST	/* make test_rtsp: no camera, no encoder: the network, audio and settings code on the build host */
	int fd;
	{ int pp[2]; if (pipe(pp)) return 1; fd = pp[0]; }	/* never readable */
	void *vb[4] = { NULL };
	unsigned int flen = W * H * 3 / 2, slen = SW * SH * 3 / 2;
	unsigned char *pf = NULL;
	double t_luma = 0, t_str = 0, t_snap = 0;
#else
	/* capture */
	int fd = open(dev, O_RDWR | O_NONBLOCK);
	if (fd < 0) { LOG("%s: %s\n", dev, strerror(errno)); return 1; }
	struct v4l2_format fmt;
	memset(&fmt, 0, sizeof fmt);
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = W; fmt.fmt.pix.height = H;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12; fmt.fmt.pix.field = V4L2_FIELD_NONE;
	ioctl(fd, VIDIOC_S_FMT, &fmt);
	struct v4l2_requestbuffers rq;
	void *vb[4];
	/* encoder pool: the picture of each stream (main, then the 640x360 sub picture right after it), the JPEG buffer,
	 * then the encoders' own buffers */
	unsigned int flen = W * H * 3 / 2, slen = SW * SH * 3 / 2, ftot = flen + slen;
	unsigned char *pf = (unsigned char *)p_alloc(ftot);
	if (!pf) { LOG("no DMA memory for the frame\n"); return 1; }
	if (getenv("RTSP_ZEROCOPY") && getenv("RTSP_ZEROCOPY")[0] == '1') {
		/* capture straight into the pool: needs the kernel's USERPTR support (patch 0011); any failure -> copy mode */
		fpb[0] = pf; fpb[1] = (unsigned char *)p_alloc(flen);
		memset(&rq, 0, sizeof rq);
		rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_USERPTR;
		if (fpb[1] && ioctl(fd, VIDIOC_REQBUFS, &rq) == 0 && rq.count == 2) {
			unsigned i;

			zc = 1;
			for (i = 0; i < 2 && zc; i++) {
				struct v4l2_buffer b;

				memset(&b, 0, sizeof b);
				b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_USERPTR; b.index = i;
				b.m.userptr = (unsigned long)fpb[i]; b.length = flen;
				if (ioctl(fd, VIDIOC_QBUF, &b) < 0) { LOG("zero-copy: QBUF: %s\n", strerror(errno)); zc = 0; }
				vb[i] = fpb[i];
			}
		} else LOG("zero-copy: %s\n", fpb[1] ? "the kernel has no USERPTR capture" : "no pool memory for the second buffer");
		if (!zc) {	/* back to the usual mmap buffers */
			memset(&rq, 0, sizeof rq);
			rq.count = 0; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_USERPTR;
			ioctl(fd, VIDIOC_REQBUFS, &rq);
		}
		LOG("capture: %s\n", zc ? "zero-copy (the ISP writes into the encoder pool)" : "copy");
	}
	if (!zc) {
		memset(&rq, 0, sizeof rq);
		rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_MMAP;
		if (ioctl(fd, VIDIOC_REQBUFS, &rq) < 0) { LOG("REQBUFS: %s\n", strerror(errno)); return 1; }
		for (unsigned i = 0; i < rq.count && i < 4; i++) {
			struct v4l2_buffer b;

			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = i;
			if (ioctl(fd, VIDIOC_QUERYBUF, &b) < 0) { LOG("QUERYBUF: %s\n", strerror(errno)); return 1; }
			vb[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, b.m.offset);
			if (vb[i] == MAP_FAILED) { LOG("mmap: %s\n", strerror(errno)); return 1; }
			ioctl(fd, VIDIOC_QBUF, &b);
		}
	}
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (ioctl(fd, VIDIOC_STREAMON, &bt) < 0) { LOG("STREAMON: %s\n", strerror(errno)); return 1; }

	double t_luma = 0, t_str = 0, t_snap = 0;
	if (!getenv("NO_JPEG")) jpeg_ok = jpeg_init() == 0;
	LOG("web pictures: hardware JPEG %s\n", jpeg_ok ? "on" : "off");
#endif

	for (int k = 0; k < 2; k++) {
		struct strm *s = &S[k];
		struct venc_param *pa = &s->pa;

		s->name = k ? "sub" : "main";
		s->hevc = k ? sub_hevc : hevc;
		s->w = k ? SW : W; s->h = k ? SH : H;
		s->cache_max = k ? CACHE_MAX_SUB : CACHE_MAX;
		s->ssrc = SSRC + 2 * k;
		cache_reset(s);
		memset(pa, 0, sizeof *pa);
		pa->width = s->w; pa->height = s->h; pa->qpmin = qmin; pa->qpmax = qmax;
		pa->fps = fps; pa->gop = fps * 2; pa->kbps = k ? sub_kbps : kbps;
		if (s->hevc) { pa->codec = 2; pa->profile = 3; }
		if (k) {
			const char *e;

			pa->size_class = (e = getenv("RTSP_SUB_CHN")) && *e ? (unsigned)num(e) : 1;
			pa->group = (e = getenv("RTSP_SUB_GROUP")) && *e ? (unsigned)num(e) : 2;
		}
	}
#ifdef TC100_HOST_TEST
	int prime = 0;
	{	/* parameter sets of a 640x360 baseline stream, so that DESCRIBE answers */
		static const unsigned char ps[] = { 0, 0, 0, 1, 0x67, 0x42, 0xc0, 0x1e, 0xda, 0x05, 0xa1, 0xe8, 0x80,
						    0, 0, 0, 1, 0x68, 0xce, 0x3c, 0x80 };

		S[0].on = S[0].active = 1;
		learn_params(&S[0], ps, sizeof ps);
	}
#else
	/* H.265 as the very first use of the encoder after power-up corrupts kernel memory (seen on 6.6: oops within
	 * seconds, repeatable); after one H.264 session it is stable. So an H.265 server first runs one H.264 frame. */
	int prime = (S[0].hevc || (sub_on && S[1].hevc)) && !getenv("NO_PRIME");
	struct venc_param p0 = S[0].pa;

	if (prime) { p0.codec = 0; p0.profile = 0; }
	S[0].enc = p_open(prime ? &p0 : &S[0].pa);
	if (!prime) pool_log(&S[0]);
	if (!S[0].enc) { LOG("ak_venc_open failed\n"); return 1; }
	S[0].on = S[0].active = 1;
	if (!prime) sub_start(sub_on);
#endif

	/* network */
	int ls = socket(AF_INET, SOCK_STREAM, 0), one = 1;
	struct sockaddr_in sa;

	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&sa, 0, sizeof sa);
	sa.sin_family = AF_INET; sa.sin_addr.s_addr = htonl(INADDR_ANY); sa.sin_port = htons(port);
	if (bind(ls, (struct sockaddr *)&sa, sizeof sa) || listen(ls, 4)) { LOG("port %d: %s\n", port, strerror(errno)); return 1; }
	udpfd = socket(AF_INET, SOCK_DGRAM, 0);
	sa.sin_port = htons(srv_rtp);
	if (bind(udpfd, (struct sockaddr *)&sa, sizeof sa)) LOG("udp %d: %s\n", srv_rtp, strerror(errno));
	for (int i = 0; i < MAXCLI; i++) cl[i].fd = -1;
	LOG("tc100_rtsp: rtsp://<ip>:%d/  %dx%d %d fps %d kbit/s %s; sub-stream (/video1, /ch1, /sub) %s %dx%d %d kbit/s %s\n",
	    port, W, H, fps, kbps, hevc ? "H.265" : "H.264", sub_on ? "on" : "off", SW, SH, sub_kbps, sub_hevc ? "H.265" : "H.264");
	cfg_reload(now_s());

	struct timespec t0;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	unsigned long ncap = 0, ntot = 0;
	struct timespec tl = t0;
	long enc_us = 0, snd_us = 0, pp_us = 0, sub_us = 0;	/* per 5 s: picture post-processing (main copy + tuning + clock), sub picture */
	int np[2] = { 0, 0 }, na = 0;
	time_t sec_last = 0;

	while (run) {
		fd_set fs, ws;
#ifdef TC100_HOST_TEST
		struct timeval tv = { 0, 100000 };
#else
		struct timeval tv = { 1, 0 };
#endif
		int mx = fd > ls ? fd : ls, i;
		time_t nowt = time(NULL);

		/* microphone: while an audio client plays or the sound detection needs it; stopped 10 s after that */
		lis_scan(now_us64() / 1000);
		talk_tick(now_us64());
		aud_tx = audio_on && na > 0;
		if (aud_tx || snd_on || rec_audio_wanted() || lis_count()) {
			aud_unneeded = 0;
			if (aud_fd < 0 && aud_pid < 0 && nowt >= aud_retry) aud_open();
		} else if (aud_fd >= 0) {
			if (!aud_unneeded) aud_unneeded = nowt;
			else if (nowt - aud_unneeded >= 10) { aud_close(); aud_unneeded = 0; }
		}
		FD_ZERO(&fs); FD_ZERO(&ws); FD_SET(fd, &fs); FD_SET(ls, &fs);
		if (udpfd >= 0) { FD_SET(udpfd, &fs); if (udpfd > mx) mx = udpfd; }
		if (aud_fd >= 0) { FD_SET(aud_fd, &fs); if (aud_fd > mx) mx = aud_fd; }
		for (i = 0; i < MAXCLI; i++)
			if (cl[i].fd >= 0) {
				FD_SET(cl[i].fd, &fs);
				if (cl[i].qpos < cl[i].qlen) FD_SET(cl[i].fd, &ws);
				if (cl[i].fd > mx) mx = cl[i].fd;
			}
		if (select(mx + 1, &fs, &ws, NULL, &tv) < 0) continue;
		{
			struct timespec tn;

			clock_gettime(CLOCK_MONOTONIC, &tn);
			if (tn.tv_sec - tl.tv_sec >= 5) {
				{ unsigned long dr = 0; for (int k = 0; k < MAXCLI; k++) dr += cl[k].dropped;
				  LOG("STAT cap %lu enc %lu bytes %lu enc_ms %ld snd_ms %ld clients %d dropped %lu sub_enc %lu sub_bytes %lu rec %d pp_ms %ld sub_ms %ld\n",
				      ncap, S[0].nfr, S[0].nbytes, enc_us / 1000, snd_us / 1000, np[0] + np[1], dr, S[1].nfr, S[1].nbytes,
				      rec_active(), pp_us / 1000, sub_us / 1000); }
				ncap = 0; S[0].nfr = S[0].nbytes = S[1].nfr = S[1].nbytes = 0; enc_us = snd_us = pp_us = sub_us = 0; tl = tn;
			}
		}

		if (aud_fd >= 0 && FD_ISSET(aud_fd, &fs)) aud_pump();
		if (udpfd >= 0 && FD_ISSET(udpfd, &fs)) {	/* RTP from a client's backchannel (UDP) */
			unsigned char pk[2048];
			struct sockaddr_in from;
			socklen_t fl = sizeof from;
			int n = (int)recvfrom(udpfd, pk, sizeof pk, MSG_DONTWAIT, (struct sockaddr *)&from, &fl), best = -1;

			for (i = 0; n > 12 && i < MAXCLI; i++) {
				if (cl[i].fd < 0 || !cl[i].b_ok || cl[i].b_tcp || !cl[i].playing || cl[i].b_udp.sin_addr.s_addr != from.sin_addr.s_addr) continue;
				if (cl[i].b_udp.sin_port == from.sin_port) { best = i; break; }
				if (best < 0) best = i;		/* same host, another port (NAT): still its sound */
			}
			if (best >= 0) talk_rtp(best, pk, n, now_us64());
		}
		if (FD_ISSET(ls, &fs)) {
			struct sockaddr_in pa;
			socklen_t pl = sizeof pa;
			int s = accept(ls, (struct sockaddr *)&pa, &pl);

			if (s >= 0) {
				for (i = 0; i < MAXCLI && cl[i].fd >= 0; i++) ;
				if (i == MAXCLI) { close(s); }
				else {
					memset(&cl[i], 0, sizeof cl[i]);
					cl[i].fd = s; cl[i].last = time(NULL); cl[i].qprog = time(NULL);
					cl[i].peer = pa.sin_addr.s_addr;
					fcntl(s, F_SETFL, fcntl(s, F_GETFL) | O_NONBLOCK);
					setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
				}
			}
		}
		np[0] = np[1] = 0; na = 0;
		for (i = 0; i < MAXCLI; i++) {
			if (cl[i].fd >= 0 && FD_ISSET(cl[i].fd, &ws) && qflush(&cl[i])) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && cl[i].qpos < cl[i].qlen && time(NULL) - cl[i].qprog > 20) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && FD_ISSET(cl[i].fd, &fs)) cli_read(&cl[i]);
			if (cl[i].fd >= 0 && !cl[i].tcp && time(NULL) - cl[i].last > 90) cli_close(&cl[i]);
			if (cl[i].fd >= 0 && cl[i].playing && !(cl[i].b_ok && !cl[i].v_set)) { np[cl[i].si]++; if (cl[i].a_ok) na++; }
		}
		if (nowt != sec_last) {		/* once a second: recorder inputs, arecord reaped */
			int snd = 0;

			sec_last = nowt;
			if (rec_mode == REC_MOTION && !access("/tmp/motion_detected", F_OK)) {	/* sound event (sound-detection) */
				unlink("/tmp/motion_detected");
				snd_pulse = nowt;
			}
			snd = snd_pulse && nowt - snd_pulse < 2;
			rec_inputs(rec_watched(), md_motion || snd);
			aud_reap();
		}

		if (FD_ISSET(fd, &fs)) {
			struct v4l2_buffer b;
			struct timespec t1;
			uint32_t ts;
			uint64_t ts_us;
			int k, rec_on, rsi, rec_idr = 0, fail_main = 0;

			memset(&b, 0, sizeof b);
			b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = zc ? V4L2_MEMORY_USERPTR : V4L2_MEMORY_MMAP;
			if (ioctl(fd, VIDIOC_DQBUF, &b) < 0) continue;
			unsigned char *cur = zc ? (unsigned char *)vb[b.index] : pf;	/* the main picture the encoder reads */
			ncap++; ntot++;
			if (prime) {
				struct video_stream ps;

				if (!zc) memcpy(pf, vb[b.index], flen);
				if (!zc) ioctl(fd, VIDIOC_QBUF, &b);
				memset(&ps, 0, sizeof ps);
				if (!p_send(S[0].enc, cur, flen, &ps) && ps.data) p_release(S[0].enc, &ps);
				if (zc) { b.m.userptr = (unsigned long)cur; b.length = flen; ioctl(fd, VIDIOC_QBUF, &b); }
				p_close(S[0].enc);
				S[0].enc = p_open(&S[0].pa);
				pool_log(&S[0]);
				if (!S[0].enc) { LOG("ak_venc_open failed\n"); break; }
				prime = 0;
				sub_start(sub_on);
				continue;
			}
			/* encode while someone watches, until the parameter sets are known, and for the recorder.
			 * Idle: the encoder state moves on without a viewer, so the next viewer gets a new encoder:
			 * its first frame is an IDR. */
			rec_on = rec_active();
			rsi = rec_sub && S[1].on ? 1 : 0;
			for (k = 0; k < 2; k++) {
				struct strm *s = &S[k];
				int want = s->on && (np[k] || !HAVE_PS(s) || (rec_on && k == rsi));

				if (s->active && !want) {
					s->active = 0;
					cache_reset(s);
				} else if (!s->active && want) {
					if (!strm_reopen(s)) {
						if (k) { sub_off("the encoder did not open again"); continue; }
						fail_main = 1;
						break;
					}
					s->active = 1;
					cache_reset(s);
					for (i = 0; i < MAXCLI; i++) if (cl[i].fd >= 0 && cl[i].playing && cl[i].si == k) cl[i].wait_idr = 1;
				}
			}
			if (fail_main) { LOG("ak_venc_open failed\n"); break; }
			rsi = rec_sub && S[1].on ? 1 : 0;
			double tn = now_s();
			/* the web pictures are only made often while somebody reads them (a read after a write moves atime) */
			double str_iv = 2.0, snap_iv = 10.0;
			static time_t bw_chk = 0; static int bw = 0;
			{
				struct stat sb; time_t nw = time(NULL);

				if (!stat("/tmp/stream.jpg", &sb) && nw - sb.st_atime < 4) str_iv = 0.25;
				if (!stat("/tmp/currentpic.cache.jpg", &sb) && nw - sb.st_atime < 10) snap_iv = 2.0;
				if (nw != bw_chk) { bw_chk = nw; bw = !access("/tmp/tc100_bw", F_OK); }	/* black and white switch */
			}
			int d_luma = tn - t_luma >= 0.5, d_str = jpeg_ok && tn - t_str >= str_iv;
			int d_snap = jpeg_ok && (tn - t_snap >= snap_iv || !access("/tmp/snapshot_request", F_OK));
			/* recording: a JPEG of the picture of each keyframe of the recorded stream (the file's thumbnail), from
			 * the sub picture; made on the frames where the encoder will start a GOP */
			const struct strm *rs = &S[rsi];
			int thumb_due = jpeg_ok && rec_on && rs->active && rs->pa.gop && rs->nsent % rs->pa.gop == 0;
			int sub_made = S[1].active || d_str || thumb_due;

			if (d_luma) {	/* mean of the sub-stream luma samples, like tc100_streamer */
				const unsigned char *sy = vb[b.index];	/* main luma at sub-stream coordinates x3 */
				unsigned sum = 0, ns = 0;
				char lb[16];
				int ln;

				for (int y = 10; y < SH - 10; y += 16)
					for (int x = 10; x < SW - 10; x += 16) { sum += sy[(y * 3) * W + x * 3]; ns++; }
				ln = snprintf(lb, sizeof lb, "%u\n", ns ? sum / ns : 50);
				wfile("/tmp/cam_luma", lb, ln);
				t_luma = tn;
			}
			md_frame(vb[b.index], tn);
			cfg_reload(tn);
			{ static double t_awb; if (tn - t_awb >= 0.5) { t_awb = tn; post_awb_sample((const unsigned char *)vb[b.index] + W * H); } }
			double t_pp0 = now_s(), t_pp1;
			/* zero-copy: the sub picture is made first, from the raw picture; the corrections of the main one then
			 * happen in place. With the copy, the raw picture is untouched and the order does not matter. */
			if (sub_made) { sub_scale(vb[b.index], pf + flen); post_sub(pf + flen); post_overlay(pf + flen, SW, SH, 0); if (bw) memset(pf + flen + SW * SH, 128, SW * SH / 2); }
			t_pp1 = now_s();
			if (S[0].active || d_snap) {
				if (zc) post_inplace(cur); else post_copy(pf, vb[b.index]);
				post_overlay(cur, W, H, 1);
				if (bw) memset(cur + W * H, 128, W * H / 2);
			}
			sub_us += (long)((t_pp1 - t_pp0) * 1e6); pp_us += (long)((now_s() - t_pp1) * 1e6);
			if (!zc) ioctl(fd, VIDIOC_QBUF, &b);	/* zero-copy: the buffer goes back once it has been encoded */
			clock_gettime(CLOCK_MONOTONIC, &t1);
			ts = (uint32_t)(((t1.tv_sec - t0.tv_sec) * 1000000ULL + (t1.tv_nsec - t0.tv_nsec) / 1000) * 9 / 100);
			ts_us = (uint64_t)t1.tv_sec * 1000000ULL + (uint64_t)t1.tv_nsec / 1000;
			for (k = 0; k < 2; k++) {
				struct strm *s = &S[k];
				struct video_stream st;
				int r, idr = 0;

				if (!s->active) continue;
				memset(&st, 0, sizeof st);
				{ struct timespec ta, tb; clock_gettime(CLOCK_MONOTONIC, &ta);
				r = p_send(s->enc, k ? pf + flen : cur, k ? slen : flen, &st);
				clock_gettime(CLOCK_MONOTONIC, &tb); enc_us += (tb.tv_sec - ta.tv_sec) * 1000000L + (tb.tv_nsec - ta.tv_nsec) / 1000; }
				s->nsent++;
				if (r || !st.data || !st.len) {
					if (k && ++s->fails >= 50) sub_off("the encoder gives no frames");
					continue;
				}
				s->fails = 0;
				{
					int pos = 0, l, n;

					while ((n = next_nal(st.data, st.len, pos, &l)) >= 0) {
						{ int t = NT(s, st.data[n]); if (s->hevc ? (t >= 16 && t <= 21) : t == 5) idr = 1; }
						pos = n + l;
					}
				}
				if (idr) learn_params(s, st.data, st.len);
				if (getenv("RTSP_DEBUG")) LOG("FRAME %s %s len %u\n", s->name, idr ? "IDR" : "P", st.len);
				if (st.len > 10 || idr) {	/* skip frames still count in the timeline */
					cache_add(s, st.data, st.len, ts, idr);
					{ struct timespec ta, tb; clock_gettime(CLOCK_MONOTONIC, &ta);
					bcast(k, st.data, st.len, ts, idr);
					clock_gettime(CLOCK_MONOTONIC, &tb); snd_us += (tb.tv_sec - ta.tv_sec) * 1000000L + (tb.tv_nsec - ta.tv_nsec) / 1000; }
					s->nbytes += st.len;
					if (rec_on && k == rsi) { rec_frame(st.data, st.len, ts_us, idr, s->hevc); if (idr) rec_idr = 1; }
				}
				s->nfr++;
				p_release(s->enc, &st);
			}
			{
				int want_thumb = jpeg_ok && rec_idr && sub_made;

				if (d_str || d_snap || want_thumb) {
					uint32_t py = (uint32_t)p_v2p((unsigned long)cur), pys = (uint32_t)p_v2p((unsigned long)pf) + flen, n;

					if (d_str && !access("/tmp/dump_sub", F_OK)) { unlink("/tmp/dump_sub"); wfile("/tmp/sub.nv12", pf + flen, slen); }
					if ((d_str || want_thumb) && (n = jpeg_run(pys, pys + SW * SH, SW, SH, 40))) {
						if (d_str) {
							wfile("/tmp/stream.jpg", jbuf + TABLES_SIZE, n);
							wfile("/tmp/frame_ch0.jpg", jbuf + TABLES_SIZE, n);
							t_str = tn;
						}
						if (want_thumb) rec_thumb(jbuf + TABLES_SIZE, n, ts_us);
					}
					if (d_snap) {
						unlink("/tmp/snapshot_request");
						if ((n = jpeg_run(py, py + W * H, W, H, 35))) {
							char tsb[24];

							wfile("/tmp/currentpic.cache.jpg", jbuf + TABLES_SIZE, n);
							wfile("/tmp/currentpic.cache.ts", tsb, snprintf(tsb, sizeof tsb, "%ld\n", (long)time(NULL)));
						}
						t_snap = tn;
					}
				}
			}
			if (zc) { b.m.userptr = (unsigned long)cur; b.length = flen; ioctl(fd, VIDIOC_QBUF, &b); }	/* encoded and copied out: capture here again */
		}
	}
	rec_shutdown();
	talk_shutdown();
	lis_close_all();
	aud_close();
	for (int k = 1; k >= 0; k--) if (S[k].enc) p_close(S[k].enc);
	LOG("tc100_rtsp: stopped after %lu frames\n", ntot);
	return 0;
}
