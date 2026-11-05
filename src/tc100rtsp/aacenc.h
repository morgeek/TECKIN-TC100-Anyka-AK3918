/* aacenc.h: small fixed-point AAC-LC encoder for 8 kHz mono (see aacenc.c) */
#ifndef TC100_AACENC_H
#define TC100_AACENC_H
#include <stdint.h>

#define AAC_FRAME	1024		/* samples per access unit (128 ms at 8 kHz) */
#define AAC_RATE	8000
#define AAC_OUT_MAX	1024		/* longest access unit it writes */

struct aacenc {
	int16_t hist[AAC_FRAME];	/* the previous 1024 samples (the other half of the 2048-sample window) */
	int16_t cur[AAC_FRAME];		/* the samples collected for the next frame */
	int fill;
	int sf_floor;			/* finest quantizer step it uses (scale factor units of 1.5 dB); noise floor of the picture */
	int bits_frame;			/* average bit budget of a frame */
	int credit;			/* bits saved by the small frames: a loud one may use them */
	int32_t X[AAC_FRAME];		/* spectrum (scratch) */
	uint32_t P[AAC_FRAME];		/* |X|^0.75, 6 fractional bits (scratch) */
	int16_t q[AAC_FRAME];		/* quantized spectrum (scratch) */
	unsigned last_bits;		/* bits of the last frame, last_sf its quantizer (statistics) */
	int last_sf;
};

void aacenc_init(struct aacenc *e, unsigned bitrate);	/* bitrate: the average, bits per second (about 12000 to 40000) */
void aacenc_reset(struct aacenc *e);			/* the next sample starts a new run (zero history) */
/* n <= 1024 samples in; returns the length of an access unit written to out (raw_data_block, no ADTS header) when this
 * call completed a frame, else 0 */
int aacenc_feed(struct aacenc *e, const int16_t *pcm, int n, uint8_t *out);
int16_t aac_alaw(unsigned char a);			/* G.711 A-law byte -> 16-bit sample */

#endif
