/* aec.h: acoustic echo cancellation of tc100_rtsp (two-way audio), 8 kHz mono, 16-bit, fixed point, see aec.c */
#ifndef TC100_AEC_H
#define TC100_AEC_H
#include <stdint.h>

#define AEC_TAPS_DEFAULT 256
#define AEC_TAPS_MAX 512

struct aec;

struct aec *aec_new(int taps);		/* NULL when out of memory; taps clamped to 32..512 (default 256) */
void aec_free(struct aec *a);
void aec_reset(struct aec *a);		/* weights, history, detectors (not the settings below) */

/* settings, before the first sample */
int aec_set_ratio(struct aec *a, const char *spec);	/* speaker frames played per microphone frame: "625/624" or a ppm
							 * value ("1600" = 1.0016, "-800"); 0 ok, -1 invalid (then 1.0) */
void aec_set_d0(struct aec *a, int samples);		/* constant delay speaker queue -> microphone (DAC, amplifier, air, ADC) */
void aec_set_suppressor(struct aec *a, int on);		/* residual suppressor (default on) */

/* far end: the samples written to the speaker, in the order written (the resampler brings them to the microphone clock) */
void aec_far(struct aec *a, const int16_t *x, int n);
/* before each block of the microphone: queued = speaker frames written and not yet played (-1: nothing plays),
 * unread = microphone frames captured and not yet processed (including the block about to be processed) */
void aec_align(struct aec *a, int queued, int unread);
/* one microphone sample in (high-passed), one out: echo removed. Returns the input at once while the far end is silent. */
int aec_process(struct aec *a, int mic);
int aec_far_active(const struct aec *a);	/* the speaker played something in the last ~150 ms (or its echo is still arriving) */
void aec_counters(const struct aec *a, unsigned *resets, unsigned *realigns);

#endif
