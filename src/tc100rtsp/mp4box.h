/* mp4box.h: parameter set parsing and fragmented-MP4 box writers shared by rec.c (recorder) and livemp4.c (live view) */
#ifndef TC100_MP4BOX_H
#define TC100_MP4BOX_H
#include <stddef.h>
#include <stdint.h>

#define MP4_TS		90000ULL	/* media timescale of the video track */
#define MP4_ATS		8000		/* media timescale of the audio track: 1 tick = 1 A-law sample */
#define MP4_PS_MAX	256		/* longest parameter set handled */

enum { C_NONE, C_H264, C_H265 };
struct nal { const unsigned char *p; uint32_t n; };
struct vinfo { int w, h, chroma, depth_l, depth_c; unsigned char ptl[12]; };
struct buf { unsigned char *p; size_t n, cap; int err; };

/* Annex B access unit -> NAL units (start codes and trailing zeros removed); returns the count, at most max */
int mp4_split_nals(const unsigned char *b, uint32_t len, struct nal *out, int max);
int mp4_nal_type(int codec, const struct nal *u);
int mp4_parse_sps264(const struct nal *u, struct vinfo *vi);	/* width and height; 0 when valid */
int mp4_parse_sps265(const struct nal *u, struct vinfo *vi);

void mp4_b_need(struct buf *b, size_t k);
void mp4_b_put(struct buf *b, const void *d, size_t k);
void mp4_b8(struct buf *b, unsigned v);
void mp4_b16(struct buf *b, unsigned v);
void mp4_b32(struct buf *b, uint32_t v);
void mp4_b64(struct buf *b, uint64_t v);
void mp4_bzero_(struct buf *b, size_t k);
size_t mp4_box(struct buf *b, const char *t);			/* open a box: returns its offset for mp4_end */
size_t mp4_fbox(struct buf *b, const char *t, unsigned v, uint32_t f);	/* full box (version, flags) */
void mp4_end(struct buf *b, size_t at);				/* close the box opened at 'at' (writes its size) */

/* ftyp + moov: one video track (avc1 / hvc1 with the parameter sets) and, with audio, an A-law track; fragments by mvex */
void mp4_init_segment(struct buf *b, int codec, const struct vinfo *vi,
		      const struct nal *vps, const struct nal *sps, const struct nal *pps, int audio);

#endif
