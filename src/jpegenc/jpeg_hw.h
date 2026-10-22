/* Hardware JPEG engine of the AK3918EV300 (Allegro DVT core, registers 0x20028000..): table block, control words
 * and the register sequence, shared by jpegenc (command line tool) and tc100_rtsp (snapshots). GPL-2.0-or-later.
 * The including program provides the mapped 64 KiB window at 0x20020000 in `regs` (not with JPEGENC_NO_DEVICE). */
#ifndef JPEG_HW_H
#define JPEG_HW_H
#include <stdint.h>
#include <string.h>
#include "jpeg_std_tables.h"

#define TABLES_SIZE	0x800	/* room the hardware expects before the stream */
#define AUX_SIZE	0x6400	/* second buffer given to the core (reg 0x3d8) */

/* register offsets inside the 64 KiB window at 0x20020000 */
#define R_IRQ_EN	0x8010
#define R_MASK		0x8014
#define R_STAT_CLR	0x8018
#define R_STAT		0x801c
#define R_ACK		0x8020
#define R_JPEG_CTRL	0x83c0	/* 11 control words */
#define R_JPEG_STATUS	0x83f0	/* 3 status words */
#define R_START		0x8084
#define R_CLK		0xc004

static void le32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }	/* little endian host */

/* ---- hardware table block (layout of preprocessEp1: color, normal mode) ---- */
static void build_tables(uint8_t *t, int q)
{
	int i, scale = q < 50 ? 5000 / q : 200 - 2 * q;
	uint8_t qz[2][64];
	int tbl;

	memset(t, 0, TABLES_SIZE);
	for (tbl = 0; tbl < 2; tbl++) {
		const uint8_t *base = tbl ? quant_chroma : quant_luma;

		for (i = 0; i < 64; i++) {
			int v = (scale * base[zigzag[i]] + 50) / 100;

			qz[tbl][i] = v == 0 ? 1 : v > 255 ? 255 : v;
			t[tbl * 0x40 + i] = qz[tbl][i];
		}
	}
	for (tbl = 0; tbl < 2; tbl++)
		for (i = 0; i < 64; i++) {
			uint16_t r = (0x10000 + (qz[tbl][i] >> 1)) / qz[tbl][i] - 1;

			memcpy(t + 0x80 + (tbl * 0x40 + zigzag[i]) * 2, &r, 2);
		}
	/* constants written by JpegTables_InitHuffman */
	static const uint32_t k180[] = { 1, 0, 0x20103, 0x3020403, 0x5050404, 0x17d, 0x10501, 0x1010101,
					 0x1000000, 0, 0x20102, 0x4040304, 0x7050404, 0x10277 };
	for (i = 0; i < 14; i++)
		le32(t + 0x180 + i * 4, k180[i]);
	le32(t + 0x1b8, 0x30101);
	le32(t + 0x1bc, 0x1010101);
	le32(t + 0x1c0, 0x1010100);
	le32(t + 0x1c4, 0);
	memcpy(t + 0x1c8, hw_ac_luma, 0x288);
	memcpy(t + 0x450, hw_dc_luma, 0x30);
	memcpy(t + 0x480, hw_ac_chroma, 0x288);
	memcpy(t + 0x708, hw_dc_chroma, 0x30);
	/* 0x738..0x790 stays zero */
}

/* ---- the 11 control words (JpegParamToCtrlRegs + AL_EncCore_EncodeJpeg) ---- */
static void ctrl_words(uint32_t *c, int w, int h, uint32_t y, uint32_t uv, uint32_t aux,
		       uint32_t stream, uint32_t stream_size)
{
	c[0] = 0x130;			/* 4:2:0, taken from the vendor trace */
	c[1] = ((w - 1) << 16) | (h - 1);
	c[2] = 0x00100009;		/* verified at 1920x1080 only */
	c[3] = w;			/* source stride, bytes */
	c[4] = y;
	c[5] = uv;
	c[6] = aux;
	c[7] = stream;
	c[8] = stream_size - 0x200;
	c[9] = TABLES_SIZE;
	c[10] = c[8] - TABLES_SIZE;
}

#ifndef JPEGENC_NO_DEVICE
static volatile uint32_t *regs;
#define RD(o)	(regs[(o) / 4])
#define WR(o, v) (regs[(o) / 4] = (v))

static void hw_init(void)	/* what the vendor encoder does once at start */
{
	WR(R_IRQ_EN, 0xffffffff); WR(R_STAT_CLR, 0xffffff);
	(void)RD(R_ACK); WR(R_ACK, 1); WR(0x822c, 0);
	(void)RD(R_ACK); WR(R_ACK, 0x10000);
	WR(0x8034, 0); WR(0x8054, 0x70);
}

static void hw_encode(const uint32_t *c)
{
	int i;

	(void)RD(R_STAT);
	(void)RD(R_ACK); WR(R_ACK, 1);
	WR(R_IRQ_EN, 0x1000007); WR(0x822c, 0);
	WR(R_MASK, RD(R_MASK) | 0x40000);
	WR(R_CLK, (RD(R_CLK) & 0xffff7fff) | 0xe00);
	WR(R_IRQ_EN, 0x10000000);
	for (i = 0; i < 11; i++)
		WR(R_JPEG_CTRL + i * 4, c[i]);
	WR(R_START, 0x10);
}
#endif

#endif
