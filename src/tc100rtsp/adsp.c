/* adsp.c: microphone processing of tc100_rtsp, item 11 of the implementer list. 8 kHz mono, 16-bit, integers only
 * (no libm: the camera's uClibc build of tc100_rtsp has no libm import), a few multiplications a sample: well under
 * 1 % of the CPU. Applied to the sound that leaves the camera (RTSP audio track, recordings, the Listen button),
 * not to the level meter of the sound detection (its thresholds stay what they are).
 *
 * - high-pass (RTSP_AUDIO_HPF=1): 2nd-order Butterworth at 150 Hz (-3 dB), -19 dB at 50 Hz (mains hum), -8 dB at 100 Hz
 *   (rumble, wind), 0 dB above 300 Hz (voice): biquad, coefficients x16384, direct form I with a 64-bit sum and the
 *   rounding error fed back (no DC offset left);
 * - noise gate + level control + soft clip (RTSP_AUDIO_AGC=1): a peak follower (fast attack, ~0.25 s release); below
 *   about -55 dBFS the gain goes down to x0.25 (-12 dB: the room hiss of a quiet room), above it the gain brings the
 *   peaks towards -12 dBFS, x1 to x8 at most (+18 dB: a far voice), going down fast and up slowly; above 24000 the
 *   samples are compressed 4:1 instead of clipping hard;
 * - mute while the speaker plays (RTSP_AUDIO_DUCK=1): no echo of the speaker back to the listener (half duplex),
 *   faded in ~8 ms, back ~60 ms after.
 */
#include "adsp.h"

#define HPF_B0 15074
#define HPF_B1 (-2 * HPF_B0)	/* exactly -2 b0: no DC gets through (the rounded -30149 let -46 dBFS of it) */
#define HPF_B2 15074
#define HPF_A1 (-30044)
#define HPF_A2 13870

#define GATE (55 << 8)		/* peak level x256 below which the gate closes: ~-55 dBFS */
#define TARGET 8000		/* peak level the control aims at: ~-12 dBFS */
#define G1 4096			/* gain x1 */
#define GMAX (8 * G1)
#define GGATE (G1 / 4)
#define KNEE 24000

void adsp_init(struct adsp *d, int hpf, int agc, int duck)
{
	d->hpf = hpf; d->agc = agc; d->duck = duck;
	d->x1 = d->x2 = d->y1 = d->y2 = d->err = 0;
	d->env = 0; d->gain = d->target = G1; d->mute = G1; d->n = 0;
}

int adsp_on(const struct adsp *d)
{
	return d->hpf || d->agc || d->duck;
}

int adsp_sample(struct adsp *d, int s, int speaker)
{
	int32_t y = s;

	if (d->hpf) {
		int64_t acc = (int64_t)HPF_B0 * s + (int64_t)HPF_B1 * d->x1 + (int64_t)HPF_B2 * d->x2
			      - (int64_t)HPF_A1 * d->y1 - (int64_t)HPF_A2 * d->y2 + d->err;

		y = (int32_t)(acc >> 14);
		/* the part the shift drops goes into the next sample (error feedback): the feedback path multiplies a
		 * truncation bias by ~78 at DC, which left -54 dBFS of offset */
		d->err = (int32_t)(acc - ((int64_t)y << 14));
		if (y > 65535) y = 65535;
		if (y < -65536) y = -65536;
		d->x2 = d->x1; d->x1 = s; d->y2 = d->y1; d->y1 = y;
	}
	if (d->agc) {
		int32_t a = (y < 0 ? -y : y) << 8;

		if (a > d->env) d->env += (a - d->env) >> 4;		/* attack ~2 ms */
		else d->env -= d->env >> 11;				/* release ~0.25 s */
		if (++d->n >= 16) {					/* the target every 2 ms: one division */
			d->n = 0;
			if (d->env < GATE) d->target = GGATE;
			else {
				int32_t t = (int32_t)(((int64_t)TARGET << 20) / d->env);	/* (TARGET / level) x4096 */

				d->target = t < G1 ? G1 : t > GMAX ? GMAX : t;
			}
		}
		if (d->target < d->gain) d->gain -= (d->gain - d->target + 63) >> 6;	/* down in ~8 ms */
		else d->gain += (d->target - d->gain) >> 10;			/* up in ~130 ms */
		y = (int32_t)(((int64_t)y * d->gain) >> 12);
	}
	if (d->duck) {
		int32_t want = speaker ? 0 : G1;

		if (want < d->mute) d->mute -= (d->mute - want + 63) >> 6;
		else d->mute += (want - d->mute + 511) >> 9;
		y = (int32_t)(((int64_t)y * d->mute) >> 12);
	}
	if (d->agc) {								/* soft clip */
		if (y > KNEE) y = KNEE + (y - KNEE) / 4;
		else if (y < -KNEE) y = -KNEE + (y + KNEE) / 4;
	}
	return y > 32767 ? 32767 : y < -32768 ? -32768 : (int)y;
}
