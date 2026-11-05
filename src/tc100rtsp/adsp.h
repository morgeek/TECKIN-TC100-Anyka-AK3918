/* adsp.h: microphone processing of tc100_rtsp (8 kHz mono, 16-bit, fixed point, no libm), see adsp.c */
#ifndef TC100_ADSP_H
#define TC100_ADSP_H
#include <stdint.h>

struct adsp {
	int hpf, agc, duck;		/* switches: high-pass 150 Hz, noise gate + level control + soft clip, mute while
					 * the speaker plays */
	int32_t x1, x2, y1, y2, err;	/* high-pass state, rounding error carried to the next sample */
	int32_t env;			/* level follower, x256 */
	int32_t gain, target;		/* level gain, x4096 */
	int32_t mute;			/* mute gain, x4096 */
	int n;
};

void adsp_init(struct adsp *d, int hpf, int agc, int duck);
int adsp_on(const struct adsp *d);
/* one sample in, one out; speaker = 1 while the speaker plays (push-to-talk, two-way audio, a sound) */
int adsp_sample(struct adsp *d, int s, int speaker);

#endif
