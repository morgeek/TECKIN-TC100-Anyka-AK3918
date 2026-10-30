/* mp4box.c: H.264 / H.265 parameter set parsing and fragmented-MP4 box writers, shared by the recorder (rec.c) and the
 * live view (livemp4.c). Moved out of rec.c as it was (only the names got the mp4_ prefix, so that they do not clash with
 * linker symbols such as "end"): the recorder writes the same bytes as before. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "mp4box.h"

#define TS		MP4_TS
#define ATS		MP4_ATS
#define PS_MAX		MP4_PS_MAX

/* ---- bit stream (from src/tc100fix/rec.c) ---- */

int mp4_split_nals(const unsigned char *b, uint32_t len, struct nal *out, int max)
{
	uint32_t i = 0, start = 0;
	int n = 0, in = 0;

	while (i + 2 < len) {
		if (b[i] == 0 && b[i + 1] == 0 && b[i + 2] == 1) {
			if (in && n < max) {
				uint32_t e = i;

				while (e > start && b[e - 1] == 0) e--;
				out[n].p = b + start; out[n].n = e - start; if (out[n].n) n++;
			}
			i += 3; start = i; in = 1;
			continue;
		}
		i++;
	}
	if (in && n < max && len > start) { out[n].p = b + start; out[n].n = len - start; n++; }
	return n;
}

int mp4_nal_type(int codec, const struct nal *u) { return codec == C_H265 ? (u->p[0] >> 1) & 0x3f : u->p[0] & 0x1f; }

static int rbsp(const unsigned char *s, int n, unsigned char *d, int max)
{
	int i, o = 0, z = 0;

	for (i = 0; i < n && o < max; i++) {
		if (z >= 2 && s[i] == 3) { z = 0; continue; }
		d[o++] = s[i];
		z = s[i] ? 0 : z + 1;
	}
	return o;
}

struct bits { const unsigned char *b; int n, pos, err; };
static unsigned rb(struct bits *g, int k)
{
	unsigned v = 0;

	while (k-- > 0) {
		if (g->pos >= g->n * 8) { g->err = 1; return 0; }
		v = (v << 1) | ((g->b[g->pos >> 3] >> (7 - (g->pos & 7))) & 1);
		g->pos++;
	}
	return v;
}
static unsigned ue(struct bits *g)
{
	int z = 0;

	while (!g->err && rb(g, 1) == 0 && z < 32) z++;
	if (z >= 32) { g->err = 1; return 0; }
	return ((1u << z) - 1) + rb(g, z);
}
static int se(struct bits *g) { unsigned v = ue(g); return (v & 1) ? (int)((v + 1) / 2) : -(int)(v / 2); }


int mp4_parse_sps264(const struct nal *u, struct vinfo *vi)
{
	unsigned char r[PS_MAX];
	struct bits g;
	unsigned prof, cf = 1, wm, hm, fmo, cl = 0, cr = 0, ct = 0, cb = 0, i, j;

	g.n = rbsp(u->p + 1, (int)u->n - 1, r, sizeof r); g.b = r; g.pos = 0; g.err = 0;
	prof = rb(&g, 8); rb(&g, 16); ue(&g);
	if (prof == 100 || prof == 110 || prof == 122 || prof == 244 || prof == 44 || prof == 83 ||
	    prof == 86 || prof == 118 || prof == 128 || prof == 138 || prof == 139 || prof == 134 || prof == 135) {
		cf = ue(&g);
		if (cf == 3) rb(&g, 1);
		ue(&g); ue(&g); rb(&g, 1);
		if (rb(&g, 1))
			for (i = 0; i < (cf != 3 ? 8u : 12u); i++)
				if (rb(&g, 1)) {
					int last = 8, next = 8, sz = i < 6 ? 16 : 64;

					for (j = 0; j < (unsigned)sz; j++) {
						if (next) next = (last + se(&g) + 256) % 256;
						last = next ? next : last;
					}
				}
	}
	ue(&g);
	i = ue(&g);
	if (i == 0) ue(&g);
	else if (i == 1) { rb(&g, 1); se(&g); se(&g); j = ue(&g); while (j-- && !g.err) se(&g); }
	ue(&g); rb(&g, 1);
	wm = ue(&g); hm = ue(&g); fmo = rb(&g, 1);
	if (!fmo) rb(&g, 1);
	rb(&g, 1);
	if (rb(&g, 1)) { cl = ue(&g); cr = ue(&g); ct = ue(&g); cb = ue(&g); }
	if (g.err) return -1;
	vi->w = (int)((wm + 1) * 16 - (cl + cr) * (cf ? 2 : 1));
	vi->h = (int)((2 - fmo) * (hm + 1) * 16 - (ct + cb) * (cf == 1 ? 2 : 1) * (2 - fmo));
	return vi->w > 0 && vi->h > 0 ? 0 : -1;
}

int mp4_parse_sps265(const struct nal *u, struct vinfo *vi)
{
	unsigned char r[PS_MAX];
	struct bits g;
	unsigned msl, i, pp[8], lp[8], w, h, cf, sw, sh, cl = 0, cr = 0, ct = 0, cb = 0;

	if (u->n < 16) return -1;
	g.n = rbsp(u->p + 2, (int)u->n - 2, r, sizeof r); g.b = r; g.pos = 0; g.err = 0;
	if (g.n < 14) return -1;
	rb(&g, 4); msl = rb(&g, 3); rb(&g, 1);
	memcpy(vi->ptl, r + 1, 12);
	g.pos += 96;
	for (i = 0; i < msl; i++) { pp[i] = rb(&g, 1); lp[i] = rb(&g, 1); }
	if (msl > 0) for (i = msl; i < 8; i++) rb(&g, 2);
	for (i = 0; i < msl; i++) { if (pp[i]) g.pos += 88; if (lp[i]) g.pos += 8; }
	ue(&g);
	cf = ue(&g);
	if (cf == 3) rb(&g, 1);
	w = ue(&g); h = ue(&g);
	if (rb(&g, 1)) { cl = ue(&g); cr = ue(&g); ct = ue(&g); cb = ue(&g); }
	vi->depth_l = (int)ue(&g); vi->depth_c = (int)ue(&g);
	if (g.err || cf > 3) return -1;
	sw = (cf == 1 || cf == 2) ? 2 : 1; sh = cf == 1 ? 2 : 1;
	vi->chroma = (int)cf;
	vi->w = (int)(w - (cl + cr) * sw);
	vi->h = (int)(h - (ct + cb) * sh);
	return vi->w > 0 && vi->h > 0 ? 0 : -1;
}

/* ---- growable buffer and MP4 boxes (src/tc100fix/rec.c) -------------------------------------------------------- */

void mp4_b_need(struct buf *b, size_t k)
{
	size_t c;
	unsigned char *np;

	if (b->err || b->n + k <= b->cap) return;
	c = b->cap ? b->cap : 4096;
	while (c < b->n + k) c *= 2;
	np = realloc(b->p, c);
	if (!np) { b->err = 1; return; }
	b->p = np; b->cap = c;
}
void mp4_b_put(struct buf *b, const void *d, size_t k) { mp4_b_need(b, k); if (!b->err) { memcpy(b->p + b->n, d, k); b->n += k; } }
void mp4_b8(struct buf *b, unsigned v) { unsigned char c = (unsigned char)v; mp4_b_put(b, &c, 1); }
void mp4_b16(struct buf *b, unsigned v) { mp4_b8(b, v >> 8); mp4_b8(b, v); }
void mp4_b32(struct buf *b, uint32_t v) { mp4_b16(b, v >> 16); mp4_b16(b, v & 0xffff); }
void mp4_b64(struct buf *b, uint64_t v) { mp4_b32(b, (uint32_t)(v >> 32)); mp4_b32(b, (uint32_t)v); }
void mp4_bzero_(struct buf *b, size_t k) { while (k--) mp4_b8(b, 0); }
size_t mp4_box(struct buf *b, const char *t) { size_t at = b->n; mp4_b32(b, 0); mp4_b_put(b, t, 4); return at; }
size_t mp4_fbox(struct buf *b, const char *t, unsigned v, uint32_t f) { size_t at = mp4_box(b, t); mp4_b32(b, (v << 24) | f); return at; }
void mp4_end(struct buf *b, size_t at)
{
	uint32_t s = (uint32_t)(b->n - at);

	if (b->err) return;
	b->p[at] = (unsigned char)(s >> 24); b->p[at + 1] = (unsigned char)(s >> 16);
	b->p[at + 2] = (unsigned char)(s >> 8); b->p[at + 3] = (unsigned char)s;
}

static const uint32_t matrix[9] = { 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000 };

/* ftyp + moov: one video track, sample entry avc1 / hvc1 with the parameter sets, fragments announced by mvex */
void mp4_init_segment(struct buf *b, int codec, const struct vinfo *vi,
			 const struct nal *vps, const struct nal *sps, const struct nal *pps, int audio)
{
	size_t moov, trak, mdia, minf, stbl, stsd, se_, cfg, dinf, dref, mvex, a;
	int i;

	a = mp4_box(b, "ftyp"); mp4_b_put(b, "isom", 4); mp4_b32(b, 0x200);
	mp4_b_put(b, "isomiso6mp41", 12); mp4_b_put(b, codec == C_H265 ? "hvc1" : "avc1", 4); mp4_end(b, a);

	moov = mp4_box(b, "moov");
	a = mp4_fbox(b, "mvhd", 0, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, 1000); mp4_b32(b, 0);
	mp4_b32(b, 0x10000); mp4_b16(b, 0x100); mp4_bzero_(b, 10);
	for (i = 0; i < 9; i++) mp4_b32(b, matrix[i]);
	mp4_bzero_(b, 24); mp4_b32(b, audio ? 3 : 2); mp4_end(b, a);

	trak = mp4_box(b, "trak");
	a = mp4_fbox(b, "tkhd", 0, 3); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, 1); mp4_b32(b, 0); mp4_b32(b, 0);
	mp4_bzero_(b, 8); mp4_b16(b, 0); mp4_b16(b, 0); mp4_b16(b, 0); mp4_b16(b, 0);
	for (i = 0; i < 9; i++) mp4_b32(b, matrix[i]);
	mp4_b32(b, (uint32_t)vi->w << 16); mp4_b32(b, (uint32_t)vi->h << 16); mp4_end(b, a);

	mdia = mp4_box(b, "mdia");
	a = mp4_fbox(b, "mdhd", 0, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, (uint32_t)TS); mp4_b32(b, 0);
	mp4_b16(b, 0x55c4); mp4_b16(b, 0); mp4_end(b, a);
	a = mp4_fbox(b, "hdlr", 0, 0); mp4_b32(b, 0); mp4_b_put(b, "vide", 4); mp4_bzero_(b, 12);
	mp4_b_put(b, "VideoHandler", 13); mp4_end(b, a);
	minf = mp4_box(b, "minf");
	a = mp4_fbox(b, "vmhd", 0, 1); mp4_bzero_(b, 8); mp4_end(b, a);
	dinf = mp4_box(b, "dinf"); dref = mp4_fbox(b, "dref", 0, 0); mp4_b32(b, 1);
	a = mp4_fbox(b, "url ", 0, 1); mp4_end(b, a); mp4_end(b, dref); mp4_end(b, dinf);

	stbl = mp4_box(b, "stbl");
	stsd = mp4_fbox(b, "stsd", 0, 0); mp4_b32(b, 1);
	se_ = mp4_box(b, codec == C_H265 ? "hvc1" : "avc1");
	mp4_bzero_(b, 6); mp4_b16(b, 1); mp4_bzero_(b, 16);
	mp4_b16(b, (unsigned)vi->w); mp4_b16(b, (unsigned)vi->h);
	mp4_b32(b, 0x480000); mp4_b32(b, 0x480000); mp4_b32(b, 0); mp4_b16(b, 1);
	mp4_bzero_(b, 32); mp4_b16(b, 0x18); mp4_b16(b, 0xffff);
	if (codec == C_H265) {
		const struct nal *arr[3];
		int t[3] = { 32, 33, 34 };

		arr[0] = vps; arr[1] = sps; arr[2] = pps;
		cfg = mp4_box(b, "hvcC");
		mp4_b8(b, 1); mp4_b_put(b, vi->ptl, 12);
		mp4_b16(b, 0xf000); mp4_b8(b, 0xfc); mp4_b8(b, 0xfc | (vi->chroma & 3));
		mp4_b8(b, 0xf8 | (vi->depth_l & 7)); mp4_b8(b, 0xf8 | (vi->depth_c & 7));
		mp4_b16(b, 0); mp4_b8(b, 0x0f); mp4_b8(b, 3);
		for (i = 0; i < 3; i++) { mp4_b8(b, 0x80 | t[i]); mp4_b16(b, 1); mp4_b16(b, arr[i]->n); mp4_b_put(b, arr[i]->p, arr[i]->n); }
		mp4_end(b, cfg);
	} else {
		cfg = mp4_box(b, "avcC");
		mp4_b8(b, 1); mp4_b8(b, sps->p[1]); mp4_b8(b, sps->p[2]); mp4_b8(b, sps->p[3]); mp4_b8(b, 0xff);
		mp4_b8(b, 0xe1); mp4_b16(b, sps->n); mp4_b_put(b, sps->p, sps->n);
		mp4_b8(b, 1); mp4_b16(b, pps->n); mp4_b_put(b, pps->p, pps->n);
		mp4_end(b, cfg);
	}
	mp4_end(b, se_); mp4_end(b, stsd);
	a = mp4_fbox(b, "stts", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
	a = mp4_fbox(b, "stsc", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
	a = mp4_fbox(b, "stsz", 0, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_end(b, a);
	a = mp4_fbox(b, "stco", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
	mp4_end(b, stbl); mp4_end(b, minf); mp4_end(b, mdia); mp4_end(b, trak);

	if (audio) {	/* track 2: G.711 A-law, 8 kHz mono: the 'alaw' sample entry ffmpeg reads (QuickTime sound description v0) */
		trak = mp4_box(b, "trak");
		a = mp4_fbox(b, "tkhd", 0, 3); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, 2); mp4_b32(b, 0); mp4_b32(b, 0);
		mp4_bzero_(b, 8); mp4_b16(b, 0); mp4_b16(b, 0); mp4_b16(b, 0x100); mp4_b16(b, 0);
		for (i = 0; i < 9; i++) mp4_b32(b, matrix[i]);
		mp4_b32(b, 0); mp4_b32(b, 0); mp4_end(b, a);
		mdia = mp4_box(b, "mdia");
		a = mp4_fbox(b, "mdhd", 0, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, ATS); mp4_b32(b, 0);
		mp4_b16(b, 0x55c4); mp4_b16(b, 0); mp4_end(b, a);
		a = mp4_fbox(b, "hdlr", 0, 0); mp4_b32(b, 0); mp4_b_put(b, "soun", 4); mp4_bzero_(b, 12);
		mp4_b_put(b, "SoundHandler", 13); mp4_end(b, a);
		minf = mp4_box(b, "minf");
		a = mp4_fbox(b, "smhd", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
		dinf = mp4_box(b, "dinf"); dref = mp4_fbox(b, "dref", 0, 0); mp4_b32(b, 1);
		a = mp4_fbox(b, "url ", 0, 1); mp4_end(b, a); mp4_end(b, dref); mp4_end(b, dinf);
		stbl = mp4_box(b, "stbl");
		stsd = mp4_fbox(b, "stsd", 0, 0); mp4_b32(b, 1);
		se_ = mp4_box(b, "alaw");
		mp4_bzero_(b, 6); mp4_b16(b, 1);			/* reserved, data reference index */
		mp4_b16(b, 0); mp4_b16(b, 0); mp4_b32(b, 0);		/* sound version 0, revision, vendor */
		mp4_b16(b, 1); mp4_b16(b, 16); mp4_b16(b, 0); mp4_b16(b, 0);	/* channels, sample size, compression id, packet size */
		mp4_b32(b, (uint32_t)ATS << 16);			/* sample rate 16.16 */
		mp4_end(b, se_); mp4_end(b, stsd);
		a = mp4_fbox(b, "stts", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
		a = mp4_fbox(b, "stsc", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
		a = mp4_fbox(b, "stsz", 0, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_end(b, a);
		a = mp4_fbox(b, "stco", 0, 0); mp4_b32(b, 0); mp4_end(b, a);
		mp4_end(b, stbl); mp4_end(b, minf); mp4_end(b, mdia); mp4_end(b, trak);
	}

	mvex = mp4_box(b, "mvex");
	a = mp4_fbox(b, "trex", 0, 0); mp4_b32(b, 1); mp4_b32(b, 1); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_end(b, a);
	if (audio) { a = mp4_fbox(b, "trex", 0, 0); mp4_b32(b, 2); mp4_b32(b, 1); mp4_b32(b, 0); mp4_b32(b, 0); mp4_b32(b, 0); mp4_end(b, a); }
	mp4_end(b, mvex);
	mp4_end(b, moov);
}
