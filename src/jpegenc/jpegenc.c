/*
 * jpegenc: JPEG encoding on the hardware JPEG engine of the AK3918EV300
 * (Allegro DVT core, registers 0x20028000..), driven from user space through
 * the ak39_venc kernel driver (/dev/uio0). No vendor library involved.
 *
 * STATUS: the tables, the layout of the table block and the control words
 * follow the decompiled control software (JpegTables_InitQuant/InitHuffman,
 * JpegParamToCtrlRegs, AL_EncCore_EncodeJpeg) and a recorded hardware trace of
 * the vendor encoder at 1920x1080. The tables are verified offline
 * (jpeg_hw_tables.py --check). The hardware run itself has NOT been tried:
 * use --dry first, then --run only on a test camera booted from RAM.
 *
 *   jpegenc [--dry] [--run] [-q QUALITY] in.nv12 WIDTH HEIGHT out.jpg
 *
 *   --dry   (default) build the table block and the control words, write
 *           out.jpg.tables and print the words; touches no hardware
 *   --run   encode on the hardware, write out.jpg.hw (raw stream) and out.jpg
 *           (the stream of the vendor encoder is a complete JPEG: the core writes the
 *           header itself from the table block; a software header is only a fallback)
 *
 * License: GPL-2.0-or-later
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

#include "jpeg_hw.h"
#ifndef JPEGENC_NO_DEVICE
#include "../libakuio/ak39_venc.h"
#endif

static int quality = 35;

/* ---- JFIF header written by software ---- */
static size_t put_seg(uint8_t *o, uint8_t m, const uint8_t *d, size_t n)
{
	o[0] = 0xff; o[1] = m; o[2] = (n + 2) >> 8; o[3] = (n + 2) & 255;
	memcpy(o + 4, d, n);
	return n + 4;
}

static size_t build_header(uint8_t *o, int w, int h, int q)
{
	uint8_t b[300], *p = o;
	int i, t, scale = q < 50 ? 5000 / q : 200 - 2 * q;

	*p++ = 0xff; *p++ = 0xd8;
	memcpy(b, "JFIF\0\1\1\0\0\1\0\1\0\0", 14);
	p += put_seg(p, 0xe0, b, 14);
	for (t = 0; t < 2; t++) {
		const uint8_t *base = t ? quant_chroma : quant_luma;

		b[0] = t;
		for (i = 0; i < 64; i++) {
			int v = (scale * base[zigzag[i]] + 50) / 100;

			b[1 + i] = v == 0 ? 1 : v > 255 ? 255 : v;
		}
		p += put_seg(p, 0xdb, b, 65);
	}
	b[0] = 8; b[1] = h >> 8; b[2] = h & 255; b[3] = w >> 8; b[4] = w & 255; b[5] = 3;
	b[6] = 1; b[7] = 0x22; b[8] = 0;	/* Y 2x2 */
	b[9] = 2; b[10] = 0x11; b[11] = 1;	/* Cb 1x1 */
	b[12] = 3; b[13] = 0x11; b[14] = 1;	/* Cr 1x1 */
	p += put_seg(p, 0xc0, b, 15);
	{
		const struct { uint8_t id; const uint8_t *d; size_t n; } dht[] = {
			{ 0x00, dht_dc_luma, sizeof dht_dc_luma }, { 0x10, dht_ac_luma, sizeof dht_ac_luma },
			{ 0x01, dht_dc_chroma, sizeof dht_dc_chroma }, { 0x11, dht_ac_chroma, sizeof dht_ac_chroma },
		};
		for (i = 0; i < 4; i++) {
			b[0] = dht[i].id;
			memcpy(b + 1, dht[i].d, dht[i].n);
			p += put_seg(p, 0xc4, b, dht[i].n + 1);
		}
	}
	memcpy(b, "\3\1\0\2\021\3\021\0\77\0", 10);
	p += put_seg(p, 0xda, b, 10);
	return p - o;
}

int main(int argc, char **argv)
{
	int dry = 1, a = 1, w, h;
	const char *in, *out;

	while (a < argc && argv[a][0] == '-') {
		if (!strcmp(argv[a], "--run")) dry = 0;
		else if (!strcmp(argv[a], "--dry")) dry = 1;
		else if (!strcmp(argv[a], "-q") && a + 1 < argc) quality = atoi(argv[++a]);
		else break;
		a++;
	}
	if (argc - a != 4 || quality < 1 || quality > 100) {
		fprintf(stderr, "usage: %s [--dry|--run] [-q 1..100] in.nv12 WIDTH HEIGHT out.jpg\n", argv[0]);
		return 2;
	}
	in = argv[a]; w = atoi(argv[a + 1]); h = atoi(argv[a + 2]); out = argv[a + 3];
	if (w < 16 || h < 16 || (w & 15) || (h & 7)) {
		fprintf(stderr, "size must be a multiple of 16x8 (hardware verified at 1920x1080 only)\n");
		return 2;
	}
	size_t ysz = (size_t)w * h, insz = ysz * 3 / 2;
	uint8_t *src = malloc(insz);
	FILE *f = fopen(in, "rb");

	if (!src || !f || fread(src, 1, insz, f) != insz) {
		fprintf(stderr, "cannot read %zu bytes of NV12 from %s\n", insz, in);
		return 1;
	}
	fclose(f);

	/* pool layout: [stream 0x7e900][aux 0x6400][Y][UV] */
	uint32_t stream_size = 0x7e900, aux_off = stream_size, y_off = 0x100000;
	uint32_t uv_off = y_off + ysz, pool_need = uv_off + ysz / 2;
	uint32_t pool_paddr = 0x81800000;	/* dry-run value */
	uint8_t *pool;
#ifndef JPEGENC_NO_DEVICE
	int fd = -1;
#endif

#ifndef JPEGENC_NO_DEVICE
	struct ak39_venc_pool_info info;

	if (!dry) {
		const char *dev = getenv("AKUIO_DEV") ? getenv("AKUIO_DEV") : "/dev/uio0";

		fd = open(dev, O_RDWR | O_SYNC);
		if (fd < 0 || ioctl(fd, AK39_VENC_POOL_INFO, &info) < 0) {
			perror(dev); return 1;
		}
		if (info.size < pool_need) { fprintf(stderr, "pool too small (%u)\n", info.size); return 1; }
		pool_paddr = info.paddr;
		pool = mmap(NULL, info.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_POOL);
		regs = mmap(NULL, info.regs_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, AK39_VENC_MMAP_REGS);
		if (pool == MAP_FAILED || regs == MAP_FAILED) { perror("mmap"); return 1; }
	} else
#endif
	{
		pool = calloc(1, pool_need);
		if (!pool) return 1;
	}

	/* the vendor trace shows control word 6 (0x3d8) is the "JPEG table buffer": the table block goes there,
	 * not at the start of the output buffer (word 7, 0x3dc) as first assumed */
	build_tables(getenv("JPEGENC_OLDLAYOUT") ? pool : pool + aux_off, quality);
	if (getenv("JPEGENC_NOTABLES")) memset(pool + aux_off, 0, TABLES_SIZE);	/* debug: does the core read the block at all? */
	memcpy(pool + y_off, src, ysz);
	memcpy(pool + uv_off, src + ysz, ysz / 2);

	uint32_t c[11];

	ctrl_words(c, w, h, pool_paddr + y_off, pool_paddr + uv_off, pool_paddr + aux_off, pool_paddr, stream_size);
	{
		int i;

		printf("control words (0x200283c0..):");
		for (i = 0; i < 11; i++) printf(" %08x", c[i]);
		printf("\n");
	}
	if (dry) {
		char name[1024];
		snprintf(name, sizeof name, "%s.tables", out);
		f = fopen(name, "wb");
		if (!f || fwrite(getenv("JPEGENC_OLDLAYOUT") ? pool : pool + aux_off, 1, TABLES_SIZE, f) != TABLES_SIZE) { perror(name); return 1; }
		fclose(f);
		printf("dry run: table block written to %s\n", name);
		{
			uint8_t hdr[2048];
			size_t hl = build_header(hdr, w, h, quality);

			snprintf(name, sizeof name, "%s.header", out);
			f = fopen(name, "wb");
			if (!f || fwrite(hdr, 1, hl, f) != hl) { perror(name); return 1; }
			fclose(f);
			printf("dry run: JFIF header (%zu bytes) written to %s\n", hl, name);
		}
		return 0;
	}
#ifndef JPEGENC_NO_DEVICE
	{
		uint32_t st[3];
		uint8_t *hdr = malloc(2048), *buf;
		size_t hl, n;
		char name[1024];

		if (getenv("JPEGENC_SENTINEL")) {	/* debug: which bytes does the core really write? */
			memset(pool + TABLES_SIZE, 0xa5, stream_size - TABLES_SIZE);
			printf("sentinel 0xa5 in the stream buffer; status before: %08x %08x\n",
			       RD(R_STAT), RD(R_JPEG_STATUS + 4));
		}
		hw_init();
		hw_encode(c);
		if (ioctl(fd, AKUIO_WAIT_IRQ, &(int){ 0 }) < 0) { perror("wait irq"); return 1; }
		st[0] = RD(R_JPEG_STATUS); st[1] = RD(R_JPEG_STATUS + 4); st[2] = RD(R_JPEG_STATUS + 8);
		(void)RD(R_STAT); (void)RD(R_ACK); WR(R_ACK, 0x10001);
		WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
		WR(R_CLK, (RD(R_CLK) & 0xffff7fff) | 0xe00);
		printf("status words: %08x %08x %08x\n", st[0], st[1], st[2]);
		if (getenv("JPEGENC_SENTINEL")) {
			size_t k, last = 0, cnt = 0;

			for (k = TABLES_SIZE; k < stream_size; k++)
				if (pool[k] != 0xa5) { cnt++; last = k; }
			printf("bytes changed by the core: %zu, last at +0x%zx\n", cnt, last);
		}
		if (getenv("JPEGENC_DUMPTAB")) {	/* debug: the table block after the run */
			snprintf(name, sizeof name, "%s.tab", out);
			f = fopen(name, "wb"); fwrite(pool + aux_off, 1, TABLES_SIZE, f); fclose(f);
		}
		n = st[1];
		if (n == 0 || n > stream_size - TABLES_SIZE) { fprintf(stderr, "bad length %zu\n", n); return 1; }
		buf = pool + TABLES_SIZE;
		snprintf(name, sizeof name, "%s.hw", out);
		f = fopen(name, "wb"); fwrite(buf, 1, n, f); fclose(f);
		/* the vendor trace shows the core emits the complete file (SOI ... SOS, 650-byte
		 * header included) and reg 0x3f4 is its length; if it does not, add our own header */
		f = fopen(out, "wb");
		if (n > 2 && buf[0] == 0xff && buf[1] == 0xd8) {
			fwrite(buf, 1, n, f);
			printf("raw stream %s (%zu bytes) is a complete JPEG, copied to %s\n", name, n, out);
		} else {
			hl = build_header(hdr, w, h, quality);
			fwrite(hdr, 1, hl, f); fwrite(buf, 1, n, f);
			printf("raw stream %s (%zu bytes) has no SOI: software header (%zu bytes) added in %s\n", name, n, hl, out);
		}
		fclose(f);
	}
#endif
	return 0;
}
