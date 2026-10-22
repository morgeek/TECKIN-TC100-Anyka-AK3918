/* venctest: H.264 / H.265 through the vendor encoder control library on Linux 6.6.
 *
 * The vendor libmpi_venc_ex.so (ak_venc_*), libakv_encode.so and libplat_* are uClibc libraries. They are loaded
 * with dlopen() from a program that runs under the uClibc loader (see Makefile); the hardware side
 * (register window, interrupt, DMA pool) comes from the free libakuio.so and the ak39_venc kernel driver.
 *
 * usage: venctest [-c h264|h265|mjpeg] [-n FRAMES] [-b KBPS] [-f FPS] [-o OUT] [-d VIDEODEV] [-L LIBDIR]
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>
#include <ucontext.h>

#define W 1920
#define H 1080

/* struct venc_param of the vendor SDK (48 bytes), layout read from ak_venc_open() */
struct venc_param {
	unsigned int width, height;
	unsigned int qpmin, qpmax;
	unsigned int fps, gop;
	unsigned int kbps;
	unsigned int profile;		/* h264: 0 main, 1 high, 2 baseline; h265: 3, 4 */
	unsigned int size_class;	/* 1: 256 KiB stream cache, else 512 KiB */
	unsigned int group;		/* encoder slot */
	unsigned int rc_vbr;		/* 0: constant bit rate */
	unsigned int codec;		/* 0 h264, 1 mjpeg, 2 h265 */
};

/* struct video_stream: only the first fields are filled by ak_venc_send_frame() */
struct video_stream {
	unsigned char *data;
	unsigned int len;
	unsigned int w2[3];		/* timestamp, sequence (filled by the caller / other paths) */
	unsigned int frame_type;	/* offset 20 */
	unsigned int rest[10];
};

#define ERR(...) do { char _b[300]; int _n = snprintf(_b, sizeof _b, __VA_ARGS__); if (_n > 0) (void)!write(2, _b, _n); } while (0)

static void *(*p_open)(const struct venc_param *);
static int (*p_send)(void *, unsigned char *, unsigned int, struct video_stream *);
static int (*p_release)(void *, struct video_stream *);
static int (*p_close)(void *);
static unsigned long (*p_alloc)(int);
static int (*p_v2p)(unsigned long);
static int (*p_pinit)(void);
static volatile int run = 1;

static void on_sig(int s) { (void)s; run = 0; }

static void *ld(const char *dir, const char *name, int must)
{
	char p[300];
	void *h;

	snprintf(p, sizeof p, "%s/%s", dir, name);
	h = dlopen(p, RTLD_LAZY | RTLD_GLOBAL);
	if (!h) {
		ERR("dlopen %s: %s\n", p, dlerror());
		if (must) exit(2);
	}
	return h;
}

static int num(const char *s)
{
	int v = 0;

	while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
	return v;
}

static void hex(char *o, unsigned long v)
{
	for (int i = 0; i < 8; i++) o[i] = "0123456789abcdef"[(v >> (28 - 4 * i)) & 15];
}

static void on_fpe(int sig, siginfo_t *si, void *uc_)
{
	ucontext_t *uc = uc_;
	char b[] = "SIG pc=00000000 lr=00000000 sp=00000000 addr=00000000\n";
	b[3] = '0' + sig / 10 % 10; (void)si;
	hex(b + 8, uc->uc_mcontext.arm_pc);
	hex(b + 20, uc->uc_mcontext.arm_lr);
	hex(b + 32, uc->uc_mcontext.arm_sp);
	hex(b + 47, (unsigned long)si->si_addr);
	(void)!write(2, b, sizeof b - 1);
	int f = open("/proc/self/maps", O_RDONLY);
	char m[4096];
	int n = f >= 0 ? read(f, m, sizeof m) : 0;
	if (n > 0) (void)!write(2, m, n);
	_exit(3);
}

int main(int argc, char **argv)
{
	const char *akuio = "/mnt/sd/tc100test/libakuio.so", *out = "/tmp/venc.bin", *dev = "/dev/video0", *dir = "/mnt/sd/lib", *cd = "h264";
	int o, frames = 60, kbps = 2000, fps = 15, stat = 0, qmin = 25, qmax = 48;

	for (o = 1; o + 1 < argc; o += 2) {
		const char *a = argv[o], *v = argv[o + 1];

		if (!strcmp(a, "-c")) cd = v;
		else if (!strcmp(a, "-n")) frames = num(v);
		else if (!strcmp(a, "-b")) kbps = num(v);
		else if (!strcmp(a, "-f")) fps = num(v);
		else if (!strcmp(a, "-s")) stat = num(v);
		else if (!strcmp(a, "-q")) qmin = qmax = num(v);
		else if (!strcmp(a, "-o")) out = v;
		else if (!strcmp(a, "-d")) dev = v;
		else if (!strcmp(a, "-L")) dir = v;
		else if (!strcmp(a, "-A")) akuio = v;
		else { ERR("usage: venctest [-c h264|h265|mjpeg] [-n N] [-b KBPS] [-f FPS] [-o OUT] [-d DEV] [-L LIBDIR] [-A libakuio.so]\n"); return 2; }
	}
	signal(SIGINT, on_sig); signal(SIGTERM, on_sig);

	/* the vendor library insists on a config file that it then does not use */
	if (access("/etc/jffs2/venc.cfg", F_OK)) {
		FILE *f;
		(void)!mkdir("/etc/jffs2", 0755);
		f = fopen("/etc/jffs2/venc.cfg", "w");
		if (f) fclose(f);
	}

	if (!dlopen(akuio, RTLD_LAZY | RTLD_GLOBAL)) { ERR("dlopen %s: %s\n", akuio, dlerror()); return 2; }
	ld(dir, "libplat_common.so", 0);
	ld(dir, "libplat_thread.so", 1);
	ld(dir, "libplat_drv.so", 0);
	ld(dir, "libplat_ipcsrv.so", 0);
	ld(dir, "libplat_venc_cb.so", 1);
	ld(dir, "libakv_encode.so", 1);
	{
		void *m = ld(dir, "libmpi_venc_ex.so", 1);
		p_open = dlsym(m, "ak_venc_open");
		p_send = dlsym(m, "ak_venc_send_frame");
		p_release = dlsym(m, "ak_venc_release_stream");
		p_close = dlsym(m, "ak_venc_close");
		p_alloc = dlsym(RTLD_DEFAULT, "akuio_alloc_pmem");
		p_v2p = dlsym(RTLD_DEFAULT, "akuio_vaddr2paddr");
		p_pinit = dlsym(RTLD_DEFAULT, "akuio_pmem_init");
		if (!p_open || !p_send || !p_release || !p_alloc || !p_v2p) {
			ERR("missing symbols: open %p send %p release %p alloc %p v2p %p\n",
				(void *)p_open, (void *)p_send, (void *)p_release, (void *)p_alloc, (void *)p_v2p);
			return 2;
		}
	}
	if (p_pinit && p_pinit()) { ERR("akuio_pmem_init failed\n"); return 2; }

	/* capture: one V4L2 buffer = 1080p NV12 followed by the small sub-stream picture */
	int fd = open(dev, O_RDWR | O_NONBLOCK);
	if (fd < 0) { ERR("%s: %s\n", dev, strerror(errno)); return 1; }
	struct v4l2_format fmt;
	memset(&fmt, 0, sizeof fmt);
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = W; fmt.fmt.pix.height = H;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12; fmt.fmt.pix.field = V4L2_FIELD_NONE;
	ioctl(fd, VIDIOC_S_FMT, &fmt);
	struct v4l2_requestbuffers rq;
	memset(&rq, 0, sizeof rq);
	rq.count = 2; rq.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rq.memory = V4L2_MEMORY_MMAP;
	if (ioctl(fd, VIDIOC_REQBUFS, &rq) < 0) { ERR("%s: %s\n", "REQBUFS", strerror(errno)); return 1; }
	void *vb[4];
	for (unsigned i = 0; i < rq.count; i++) {
		struct v4l2_buffer b;
		memset(&b, 0, sizeof b);
		b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP; b.index = i;
		if (ioctl(fd, VIDIOC_QUERYBUF, &b) < 0) { ERR("%s: %s\n", "QUERYBUF", strerror(errno)); return 1; }
		vb[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, b.m.offset);
		if (vb[i] == MAP_FAILED) { ERR("%s: %s\n", "mmap", strerror(errno)); return 1; }
		ioctl(fd, VIDIOC_QBUF, &b);
	}
	enum v4l2_buf_type bt = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (ioctl(fd, VIDIOC_STREAMON, &bt) < 0) { ERR("%s: %s\n", "STREAMON", strerror(errno)); return 1; }

	unsigned int flen = W * H * 3 / 2;
	unsigned char *pf = (unsigned char *)p_alloc(flen);
	if (!pf) { ERR("no DMA memory for the frame\n"); return 1; }
	ERR("frame buffer %p phys %#x\n", pf, p_v2p((unsigned long)pf));

	struct venc_param pa;
	memset(&pa, 0, sizeof pa);
	pa.width = W; pa.height = H; pa.qpmin = qmin; pa.qpmax = qmax;
	pa.fps = fps; pa.gop = fps * 2; pa.kbps = kbps;
	if (!strcmp(cd, "h265")) { pa.codec = 2; pa.profile = 3; }
	else if (!strcmp(cd, "mjpeg")) { pa.codec = 1; pa.size_class = 1; }
	void *enc = p_open(&pa);
	ERR("ak_venc_open -> %p\n", enc);
	if (!enc) return 1;

	FILE *fo = fopen(out, "wb");
	if (!fo) { ERR("%s: %s\n", out, strerror(errno)); return 1; }
	int n = 0;
	unsigned long long total = 0;
	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	while (run && n < frames) {
		fd_set fs;
		struct timeval tv = { 2, 0 };
		FD_ZERO(&fs); FD_SET(fd, &fs);
		if (select(fd + 1, &fs, NULL, NULL, &tv) <= 0) continue;
		struct v4l2_buffer b;
		memset(&b, 0, sizeof b);
		b.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; b.memory = V4L2_MEMORY_MMAP;
		if (ioctl(fd, VIDIOC_DQBUF, &b) < 0) continue;
		if (!stat || !n) { memcpy(pf, vb[b.index], flen); if (stat) { FILE *fi = fopen("/tmp/in.nv12", "wb"); fwrite(pf, 1, flen, fi); fclose(fi); } }
		ioctl(fd, VIDIOC_QBUF, &b);
		struct video_stream st;
		memset(&st, 0, sizeof st);
		if (n == 1) { int f = open("/proc/self/maps", O_RDONLY); char m[6000]; int k = f >= 0 ? read(f, m, sizeof m) : 0; if (k > 0) (void)!write(2, m, k); }
		{ void (*mk)(int) = dlsym(RTLD_DEFAULT, "d0_mark"); if (mk) mk(n); }
		ERR("send\n"); int r = p_send(enc, pf, flen, &st); ERR("sent %d\n", r);
		if (r || !st.data) { ERR("frame %d: send_frame -> %d len %u\n", n, r, st.len); n++; continue; }
		if (n < 5 || n % 20 == 0)
			ERR("frame %d: %u bytes type %u, head %02x %02x %02x %02x %02x\n", n, st.len, st.frame_type,
				st.data[0], st.data[1], st.data[2], st.data[3], st.data[4]);
		ERR("write\n"); fwrite(st.data, 1, st.len, fo);
		total += st.len;
		ERR("rel\n"); p_release(enc, &st); ERR("rel done\n");
		n++;
	}
	{ void (*dp)(const char *) = dlsym(RTLD_DEFAULT, "d0_dump"); if (dp && getenv("VT_TRACE")) dp(getenv("VT_TRACE")); }
	clock_gettime(CLOCK_MONOTONIC, &t1);
	fclose(fo);
	double sec = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
	ERR("%d frames, %llu bytes in %.1f s (%.1f fps, %.0f kbit/s)\n", n, total, sec, n / sec, total * 8 / 1000.0 / sec);
	if (p_close) p_close(enc);
	return 0;
}
