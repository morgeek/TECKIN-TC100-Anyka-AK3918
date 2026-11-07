/*
 * avc.h: the H.264 SPS, PPS and slice headers of the free encoder's sub stream (2026-11-07), written by our code: the
 * same syntax element values as the vendor encoder's 640x360 sub stream (ffmpeg trace_headers of the IPCAM2 captures
 * of 2026-11-07), so the bytes are the same at 640x360, 25 fps, 250 kbit/s (tests/test_h265cmdlist.py AvcHeaders).
 *   SPS: Main profile, level 4.0, log2_max_frame_num 4, POC type 0 (log2_max_poc_lsb 10), one reference frame,
 *        frame_mbs_only, direct_8x8_inference, cropping to the height (368 coded lines), VUI: video format 1, limited
 *        range, colour 5/5/5, chroma location 0, timing 1 / (2 * fps) fixed, a VCL HRD (CBR, the bit rate in units of
 *        128 bit/s, a 3 s CPB in units of 16 bits, delay lengths 32 bits), pic_struct_present
 *   PPS: CABAC, one reference by default, init QP 26, deblocking control present
 *   slice: one per picture, the whole picture (first_mb 0), IDR (nal 5) or P (nal 1, slice_type 0), frame_num 4 bits,
 *        POC lsb = 2 * pictures since the IDR, no reference list changes, no adaptive marking, cabac_init_idc 0,
 *        slice_qp_delta, deblocking on with alpha / beta offsets -1, then cabac_alignment_one_bit to the byte: the core
 *        writes the CABAC slice data from there (list word 0x3e = 0x820 bytes into the stream buffer).
 * License: GPL-2.0-or-later
 */
#ifndef AVC_H
#define AVC_H
#include <stdint.h>
#include <string.h>
#include "paramsets.h"

static inline void avc_nal_head(struct pw *w, int type)
{
	pw_u(w, 0, 1); pw_u(w, 1, 2); pw_u(w, (uint32_t)type, 5);	/* forbidden 0, nal_ref_idc 1 */
}

/* SPS and PPS for width x height (multiples of 8) at fps and kbps, Annex B, into out; their length, or -1 */
static inline int h264_param_sets(uint8_t *out, int cap, uint32_t width, uint32_t height, uint32_t fps, uint32_t kbps)
{
	uint32_t mbw = (width + 15) / 16, mbh = (height + 15) / 16, crop = (mbh * 16 - height) / 2;
	uint32_t br = kbps * 1000 / 128, cpb = kbps * 1000 * 3 / 16;
	struct pw w;
	int o = 0;

	memset(&w, 0, sizeof w);
	avc_nal_head(&w, 7);
	pw_u(&w, 77, 8); pw_u(&w, 0, 8); pw_u(&w, 40, 8);	/* Main, no constraint flags, level 4.0 */
	pw_ue(&w, 0);						/* seq_parameter_set_id */
	pw_ue(&w, 0);						/* log2_max_frame_num - 4 */
	pw_ue(&w, 0); pw_ue(&w, 6);				/* POC type 0, log2_max_pic_order_cnt_lsb - 4 */
	pw_ue(&w, 1); pw_u(&w, 0, 1);				/* max_num_ref_frames, gaps */
	pw_ue(&w, mbw - 1); pw_ue(&w, mbh - 1);
	pw_u(&w, 1, 1); pw_u(&w, 1, 1);				/* frame_mbs_only, direct_8x8_inference */
	pw_u(&w, crop ? 1 : 0, 1);
	if (crop) { pw_ue(&w, 0); pw_ue(&w, 0); pw_ue(&w, 0); pw_ue(&w, crop); }
	pw_u(&w, 1, 1);						/* VUI */
	pw_u(&w, 0, 1); pw_u(&w, 0, 1);				/* aspect ratio, overscan */
	pw_u(&w, 1, 1); pw_u(&w, 1, 3); pw_u(&w, 0, 1);		/* video signal type: format 1, limited range */
	pw_u(&w, 1, 1); pw_u(&w, 5, 8); pw_u(&w, 5, 8); pw_u(&w, 5, 8);	/* colour description 5/5/5 */
	pw_u(&w, 1, 1); pw_ue(&w, 0); pw_ue(&w, 0);		/* chroma location 0/0 */
	pw_u(&w, 1, 1); pw_u(&w, 1, 32); pw_u(&w, 2 * fps, 32); pw_u(&w, 1, 1);	/* timing 1 / (2 fps), fixed */
	pw_u(&w, 0, 1);						/* NAL HRD */
	pw_u(&w, 1, 1);						/* VCL HRD */
	pw_ue(&w, 0); pw_u(&w, 1, 4); pw_u(&w, 0, 4);		/* cpb_cnt - 1, bit_rate_scale, cpb_size_scale */
	pw_ue(&w, br - 1); pw_ue(&w, cpb - 1); pw_u(&w, 1, 1);	/* bit rate, CPB size, CBR */
	pw_u(&w, 31, 5); pw_u(&w, 31, 5); pw_u(&w, 31, 5); pw_u(&w, 0, 5);	/* delay lengths - 1, time_offset_length */
	pw_u(&w, 0, 1);						/* low_delay_hrd */
	pw_u(&w, 1, 1); pw_u(&w, 0, 1);				/* pic_struct_present, bitstream restriction */
	if ((o = pw_emit(&w, out, o, cap)) < 0) return -1;

	memset(&w, 0, sizeof w);
	avc_nal_head(&w, 8);
	pw_ue(&w, 0); pw_ue(&w, 0);				/* pps id, sps id */
	pw_u(&w, 1, 1); pw_u(&w, 0, 1);				/* CABAC, bottom_field_pic_order_in_frame_present */
	pw_ue(&w, 0);						/* slice groups - 1 */
	pw_ue(&w, 0); pw_ue(&w, 0);				/* num_ref_idx l0 / l1 default - 1 */
	pw_u(&w, 0, 1); pw_u(&w, 0, 2);				/* weighted pred, bipred */
	pw_se(&w, 0); pw_se(&w, 0); pw_se(&w, 0);		/* init qp - 26, init qs - 26, chroma qp offset */
	pw_u(&w, 1, 1); pw_u(&w, 0, 1); pw_u(&w, 0, 1);		/* deblocking control, constrained intra, redundant_pic_cnt */
	return pw_emit(&w, out, o, cap);
}

/* start code + NAL header + slice header (to cabac_alignment) into out; its length, or -1. frame: pictures since the
 * IDR (frame_num and POC come from it); idr_id: idr_pic_id of an IDR */
static inline int h264_slice_nal(uint8_t *out, int cap, int idr, int qp, uint32_t frame, uint32_t idr_id)
{
	struct pw w;
	int i, o = 0, zeros = 0, nbytes;

	memset(&w, 0, sizeof w);
	avc_nal_head(&w, idr ? 5 : 1);
	pw_ue(&w, 0);						/* first_mb_in_slice */
	pw_ue(&w, idr ? 2 : 0);					/* slice_type I / P */
	pw_ue(&w, 0);						/* pic_parameter_set_id */
	pw_u(&w, frame & 15, 4);				/* frame_num */
	if (idr) pw_ue(&w, idr_id);
	pw_u(&w, (2 * frame) & 0x3ff, 10);			/* pic_order_cnt_lsb */
	if (!idr) { pw_u(&w, 0, 1); pw_u(&w, 0, 1); }		/* num_ref_idx_active_override, ref_pic_list_modification_l0 */
	if (idr) { pw_u(&w, 0, 1); pw_u(&w, 0, 1); }		/* no_output_of_prior_pics, long_term_reference */
	else pw_u(&w, 0, 1);					/* adaptive_ref_pic_marking_mode */
	if (!idr) pw_ue(&w, 0);					/* cabac_init_idc */
	pw_se(&w, qp - 26);					/* slice_qp_delta */
	pw_ue(&w, 0); pw_se(&w, -1); pw_se(&w, -1);		/* deblocking on, alpha / beta offsets */
	while (w.n & 7) pw_u(&w, 1, 1);				/* cabac_alignment_one_bit */
	nbytes = w.n >> 3;
	if (cap < 4 + 2 * nbytes) return -1;
	out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
	for (i = 0; i < nbytes; i++) {				/* emulation prevention */
		if (zeros >= 2 && w.b[i] <= 3) { out[o++] = 3; zeros = 0; }
		out[o++] = w.b[i];
		zeros = w.b[i] ? 0 : zeros + 1;
	}
	return o;
}
#endif
