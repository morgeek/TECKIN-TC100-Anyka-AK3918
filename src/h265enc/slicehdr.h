/*
 * slicehdr.h: the NAL unit header and slice segment header of a picture, as the vendor encoder writes them for its
 * SPS/PPS (seen with ffmpeg's trace_headers on the IPCAM2 captures of 2026-11-07), up to byte_alignment(): the core
 * then writes the slice data. One slice per picture, PPS 0, no SAO, deblocking from the PPS, loop filter across
 * slices on.
 *   IDR (IDR_W_RADL, 19): first_slice 1, no_output_of_prior_pics 0, pps ue(0), slice_type ue(2 = I),
 *        slice_qp_delta se(qp - 26), loop_filter_across 1
 *   P (TRAIL_R, 1): first_slice 1, pps ue(0), slice_type ue(1 = P), poc_lsb u(10), short_term_ref_pic_set_sps 0,
 *        st_ref_pic_set(13): inter_ref_pic_set_prediction 0, num_negative ue(1), num_positive ue(0),
 *        delta_poc_s0_minus1 ue(1) (the reference is POC - 2), used 1; slice_temporal_mvp 1,
 *        num_ref_idx_active_override 1, num_ref_idx_l0_active_minus1 ue(0), five_minus_max_num_merge_cand ue(0),
 *        slice_qp_delta se(qp - 26), loop_filter_across 1
 * then alignment_bit_equal_to_one and zeros to the byte. Emulation prevention bytes are inserted.
 * License: GPL-2.0-or-later
 */
#ifndef SLICEHDR_H
#define SLICEHDR_H
#include <stdint.h>

struct bw { uint8_t b[48]; int n; };	/* bits written */

static inline void bw_u(struct bw *w, uint32_t v, int bits)
{
	while (bits-- > 0) {
		if ((v >> bits) & 1) w->b[w->n >> 3] |= (uint8_t)(0x80 >> (w->n & 7));
		w->n++;
	}
}

static inline void bw_ue(struct bw *w, uint32_t v)
{
	uint32_t x = v + 1;
	int len = 0;

	while ((x >> len) > 1) len++;
	bw_u(w, 0, len);
	bw_u(w, x, len + 1);
}

static inline void bw_se(struct bw *w, int v)
{
	bw_ue(w, v > 0 ? (uint32_t)(2 * v - 1) : (uint32_t)(-2 * v));
}

/* start code + NAL header + slice header into out; its length, or -1 */
static inline int h265_slice_nal(uint8_t *out, int cap, int idr, int qp, uint32_t poc)
{
	struct bw w = { { 0 }, 0 };
	int i, o = 0, zeros = 0, nbytes;

	bw_u(&w, 0, 1); bw_u(&w, idr ? 19 : 1, 6); bw_u(&w, 0, 6); bw_u(&w, 1, 3);	/* NAL unit header */
	bw_u(&w, 1, 1);								/* first_slice_segment_in_pic */
	if (idr) bw_u(&w, 0, 1);						/* no_output_of_prior_pics */
	bw_ue(&w, 0);								/* slice_pic_parameter_set_id */
	bw_ue(&w, idr ? 2 : 1);							/* slice_type I / P */
	if (!idr) {
		bw_u(&w, poc & 0x3ff, 10);					/* slice_pic_order_cnt_lsb */
		bw_u(&w, 0, 1);							/* short_term_ref_pic_set_sps_flag */
		bw_u(&w, 0, 1);							/* inter_ref_pic_set_prediction_flag */
		bw_ue(&w, 1); bw_ue(&w, 0);					/* num_negative_pics, num_positive_pics */
		bw_ue(&w, 1); bw_u(&w, 1, 1);					/* delta_poc_s0_minus1 (= -2), used */
		bw_u(&w, 1, 1);							/* slice_temporal_mvp_enabled */
		bw_u(&w, 1, 1); bw_ue(&w, 0);					/* override, num_ref_idx_l0_active_minus1 */
		bw_ue(&w, 0);							/* five_minus_max_num_merge_cand */
	}
	bw_se(&w, qp - 26);							/* slice_qp_delta (init_qp 26) */
	bw_u(&w, 1, 1);								/* slice_loop_filter_across_slices_enabled */
	bw_u(&w, 1, 1);								/* alignment_bit_equal_to_one */
	while (w.n & 7) bw_u(&w, 0, 1);
	nbytes = w.n >> 3;
	if (cap < 4 + 2 * nbytes) return -1;
	out[o++] = 0; out[o++] = 0; out[o++] = 0; out[o++] = 1;
	for (i = 0; i < nbytes; i++) {						/* emulation prevention */
		if (zeros >= 2 && w.b[i] <= 3) { out[o++] = 3; zeros = 0; }
		out[o++] = w.b[i];
		zeros = w.b[i] ? 0 : zeros + 1;
	}
	return o;
}
#endif
