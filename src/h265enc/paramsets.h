/*
 * paramsets.h: the VPS, SPS and PPS of the free encoder (step 3, 2026-11-07), written by our code instead of the copy of
 * the vendor's: the same syntax element values as the vendor encoder's (ffmpeg trace_headers of the IPCAM2 captures),
 * so the bytes are the same for 1920x1080 at 25 fps (tests/test_h265cmdlist.py ParamSets). Main profile, level 4.0,
 * 8 bit 4:2:0, CTB 32 (min CB 8), TB 4..32, scaling lists on (default), SAO off, AMP off, TMVP on, strong intra
 * smoothing on, cu_qp_delta on, deblocking beta/tc offsets -1, lists_modification on, 13 short-term reference picture
 * sets in the SPS (the vendor's; the slices code their own), VUI: SAR 1:1, video format 1, limited range, colour
 * 5/5/5, chroma location 0, timing 1/fps, bitstream restrictions.
 * The slice headers of slicehdr.h depend on two of these values: log2_max_pic_order_cnt_lsb = 10 and the 13 sets
 * (an inter_ref_pic_set_prediction_flag is coded in the slice because there is at least one set).
 * License: GPL-2.0-or-later
 */
#ifndef PARAMSETS_H
#define PARAMSETS_H
#include <stdint.h>

struct pw { uint8_t b[160]; int n; };

static inline void pw_u(struct pw *w, uint32_t v, int bits)
{
	while (bits-- > 0) {
		if (w->n < (int)sizeof w->b * 8 && ((v >> bits) & 1)) w->b[w->n >> 3] |= (uint8_t)(0x80 >> (w->n & 7));
		w->n++;
	}
}

static inline void pw_ue(struct pw *w, uint32_t v)
{
	uint32_t x = v + 1;
	int len = 0;

	while ((x >> len) > 1) len++;
	pw_u(w, 0, len);
	pw_u(w, x, len + 1);
}

static inline void pw_se(struct pw *w, int v)
{
	pw_ue(w, v > 0 ? (uint32_t)(2 * v - 1) : (uint32_t)(-2 * v));
}

static inline void pw_nal_head(struct pw *w, int type)
{
	pw_u(w, 0, 1); pw_u(w, (uint32_t)type, 6); pw_u(w, 0, 6); pw_u(w, 1, 3);
}

/* rbsp_trailing_bits, then the start code and the bytes with emulation prevention into out (from o); new o or -1 */
static inline int pw_emit(struct pw *w, uint8_t *out, int o, int cap)
{
	int i, zeros = 0, nbytes;

	pw_u(w, 1, 1);
	while (w->n & 7) pw_u(w, 0, 1);
	nbytes = w->n >> 3;
	if (w->n > (int)sizeof w->b * 8 || o + 4 + 2 * nbytes > cap) return -1;
	out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
	for (i = 0; i < nbytes; i++) {
		if (i >= 2 && zeros >= 2 && w->b[i] <= 3) { out[o++] = 3; zeros = 0; }
		out[o++] = w->b[i];
		zeros = w->b[i] ? 0 : zeros + 1;
	}
	return o;
}

static inline void pw_profile_tier_level(struct pw *w)
{
	pw_u(w, 0, 2); pw_u(w, 0, 1); pw_u(w, 1, 5);		/* profile space, tier, profile_idc Main */
	pw_u(w, 0x40000000u, 32);				/* compatibility: Main */
	pw_u(w, 1, 1); pw_u(w, 0, 1); pw_u(w, 0, 1); pw_u(w, 1, 1);	/* progressive, interlaced, non packed, frame only */
	pw_u(w, 0, 32); pw_u(w, 0, 11);				/* reserved_zero_43bits */
	pw_u(w, 0, 1);						/* inbld */
	pw_u(w, 120, 8);					/* level 4.0 */
}

/* VPS, SPS and PPS for a width x height picture at fps, Annex B, into out; their length, or -1 */
static inline int h265_param_sets(uint8_t *out, int cap, uint32_t width, uint32_t height, uint32_t fps)
{
	/* the vendor's 13 short-term sets: {negative deltas (used), positive deltas (used)} as (delta, used) */
	static const int8_t rps[13][5] = {	/* n_neg, n_pos, then (minus1, used) pairs: s0 first */
		{ 0, 0 }, { 1, 0, 1, 1 }, { 1, 0, 3, 0 }, { 1, 0, 5, 1 }, { 1, 0, 3, 1 }, { 1, 0, 5, 1 },
		{ 1, 1, 1, 1 }, { 1, 1, 1, 1 }, { 1, 1, 3, 1 }, { 2, 0, 1, 1 }, { 2, 0, 1, 1 }, { 2, 0, 1, 1 }, { 2, 0, 1, 1 },
	};
	/* the second pair of each set, where there is one (s1 for 6-8, s0[1] for 9-12) */
	static const int8_t rps2[13][2] = {
		{ 0 }, { 0 }, { 0 }, { 0 }, { 0 }, { 0 }, { 1, 1 }, { 3, 1 }, { 1, 1 }, { 1, 1 }, { 3, 1 }, { 5, 1 }, { 7, 1 },
	};
	struct pw w;
	int o = 0, i;

	/* VPS */
	memset(&w, 0, sizeof w);
	pw_nal_head(&w, 32);
	pw_u(&w, 0, 4); pw_u(&w, 1, 1); pw_u(&w, 1, 1);		/* vps id, base layer internal, available */
	pw_u(&w, 0, 6); pw_u(&w, 0, 3); pw_u(&w, 1, 1);		/* max layers - 1, max sub layers - 1, temporal id nesting */
	pw_u(&w, 0xffff, 16);
	pw_profile_tier_level(&w);
	pw_u(&w, 1, 1);						/* sub layer ordering info present */
	pw_ue(&w, 2); pw_ue(&w, 0); pw_ue(&w, 0);		/* max dec pic buffering - 1, reorder, latency */
	pw_u(&w, 0, 6); pw_ue(&w, 0);				/* max layer id, num layer sets - 1 */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* timing info, extension */
	if ((o = pw_emit(&w, out, o, cap)) < 0) return -1;

	/* SPS */
	memset(&w, 0, sizeof w);
	pw_nal_head(&w, 33);
	pw_u(&w, 0, 4); pw_u(&w, 0, 3); pw_u(&w, 1, 1);		/* vps id, max sub layers - 1, temporal id nesting */
	pw_profile_tier_level(&w);
	pw_ue(&w, 0); pw_ue(&w, 1);				/* sps id, chroma 4:2:0 */
	pw_ue(&w, width); pw_ue(&w, height);
	pw_u(&w, 0, 1);						/* conformance window */
	pw_ue(&w, 0); pw_ue(&w, 0);				/* bit depths - 8 */
	pw_ue(&w, 6);						/* log2_max_pic_order_cnt_lsb - 4 */
	pw_u(&w, 1, 1); pw_ue(&w, 2); pw_ue(&w, 0); pw_ue(&w, 0);	/* ordering info: dec pic buffering - 1, reorder, latency */
	pw_ue(&w, 0); pw_ue(&w, 2);				/* min CB 8, CTB 32 */
	pw_ue(&w, 0); pw_ue(&w, 3);				/* min TB 4, max TB 32 */
	pw_ue(&w, 1); pw_ue(&w, 1);				/* transform hierarchy depth inter, intra */
	pw_u(&w, 1, 1); pw_u(&w, 0, 1);				/* scaling lists on, default lists */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1);		/* AMP, SAO, PCM */
	pw_ue(&w, 13);
	for (i = 0; i < 13; i++) {
		if (i) pw_u(&w, 0, 1);				/* inter_ref_pic_set_prediction_flag */
		pw_ue(&w, (uint32_t)rps[i][0]); pw_ue(&w, (uint32_t)rps[i][1]);
		if (rps[i][0] || rps[i][1]) { pw_ue(&w, (uint32_t)rps[i][2]); pw_u(&w, (uint32_t)rps[i][3], 1); }
		if (rps[i][0] + rps[i][1] == 2) { pw_ue(&w, (uint32_t)rps2[i][0]); pw_u(&w, (uint32_t)rps2[i][1], 1); }
	}
	pw_u(&w, 0, 1);						/* long-term reference pictures */
	pw_u(&w, 1, 1); pw_u(&w, 1, 1);				/* temporal MVP, strong intra smoothing */
	pw_u(&w, 1, 1);						/* VUI */
	pw_u(&w, 1, 1); pw_u(&w, 1, 8);				/* aspect ratio info, idc 1 (1:1) */
	pw_u(&w, 0, 1);						/* overscan info */
	pw_u(&w, 1, 1); pw_u(&w, 1, 3); pw_u(&w, 0, 1);		/* video signal type: format 1, limited range */
	pw_u(&w, 1, 1); pw_u(&w, 5, 8); pw_u(&w, 5, 8); pw_u(&w, 5, 8);	/* colour description 5/5/5 */
	pw_u(&w, 1, 1); pw_ue(&w, 0); pw_ue(&w, 0);		/* chroma location 0/0 */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1);	/* neutral chroma, field seq, frame field info, display window */
	pw_u(&w, 1, 1); pw_u(&w, 1, 32); pw_u(&w, fps, 32);	/* timing: 1 / fps */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* poc proportional to timing, HRD */
	pw_u(&w, 1, 1);						/* bitstream restriction */
	pw_u(&w, 0, 1); pw_u(&w, 1, 1); pw_u(&w, 1, 1);		/* tiles fixed, mv over boundaries, restricted ref lists */
	pw_ue(&w, 0); pw_ue(&w, 0); pw_ue(&w, 0);		/* min spatial segmentation, max bytes / bits denominators */
	pw_ue(&w, 15); pw_ue(&w, 15);				/* log2 max mv length h, v */
	pw_u(&w, 0, 1);						/* sps extension */
	if ((o = pw_emit(&w, out, o, cap)) < 0) return -1;

	/* PPS */
	memset(&w, 0, sizeof w);
	pw_nal_head(&w, 34);
	pw_ue(&w, 0); pw_ue(&w, 0);				/* pps id, sps id */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 3);		/* dependent slices, output flag, extra slice header bits */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* sign data hiding, cabac init present */
	pw_ue(&w, 0); pw_ue(&w, 0); pw_se(&w, 0);		/* num ref idx l0 / l1 default - 1, init qp - 26 */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* constrained intra, transform skip */
	pw_u(&w, 1, 1); pw_ue(&w, 0);				/* cu qp delta, depth 0 */
	pw_se(&w, 0); pw_se(&w, 0); pw_u(&w, 0, 1);		/* cb, cr qp offsets, slice chroma offsets */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1);		/* weighted pred, bipred, transquant bypass */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* tiles, entropy coding sync */
	pw_u(&w, 1, 1);						/* loop filter across slices */
	pw_u(&w, 1, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1);		/* deblocking control: no override, enabled */
	pw_se(&w, -1); pw_se(&w, -1);				/* beta, tc offsets / 2 */
	pw_u(&w, 0, 1);						/* pps scaling list data */
	pw_u(&w, 1, 1); pw_ue(&w, 0);				/* lists modification present, parallel merge level 2 */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* slice header extension, pps extension */
	return pw_emit(&w, out, o, cap);
}
#endif
