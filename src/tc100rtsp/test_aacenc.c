/* test_aacenc.c: the AAC encoder alone. tests/test_aacenc.py (and the cross CI under qemu-arm) drive it.
 *   test_aacenc adts in.s16 out.aac [bitrate [sf_floor]]   16-bit mono 8 kHz samples in, ADTS stream out (ffmpeg decodes it)
 *   test_aacenc raw  in.s16 out.bin [bitrate [sf_floor]]   access units only, each preceded by its length (2 bytes)
 *   test_aacenc sine out.s16 hz amp seconds                a test tone
 *   test_aacenc bench in.s16 [bitrate]                     encode and print the frames and the average size
 * Without a file argument "-" means stdin / stdout. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "aacenc.h"

static struct aacenc enc;

int main(int argc, char **argv)
{
	FILE *in, *out = stdout;
	int16_t buf[160];
	uint8_t au[AAC_OUT_MAX];
	size_t n;
	unsigned long frames = 0, bytes = 0;
	int mode;

	if (argc < 3) { fprintf(stderr, "usage: see the top of test_aacenc.c\n"); return 2; }
	if (!strcmp(argv[1], "sine")) {
		double hz = atof(argv[3]), amp = atof(argv[4]), sec = atof(argv[5]);
		long i, total = (long)(sec * 8000);

		out = fopen(argv[2], "wb");
		for (i = 0; i < total; i++) {
			int16_t s = (int16_t)lrint(amp * sin(2 * M_PI * hz * (double)i / 8000.0));

			fwrite(&s, 2, 1, out);
		}
		fclose(out);
		return 0;
	}
	mode = !strcmp(argv[1], "adts") ? 1 : !strcmp(argv[1], "raw") ? 2 : 0;
	in = strcmp(argv[2], "-") ? fopen(argv[2], "rb") : stdin;
	if (!in) { perror(argv[2]); return 1; }
	if (mode && argc > 3 && strcmp(argv[3], "-")) out = fopen(argv[3], "wb");
	aacenc_init(&enc, argc > (mode ? 4 : 3) ? (unsigned)atoi(argv[mode ? 4 : 3]) : 24000);
	if (argc > (mode ? 5 : 4)) enc.sf_floor = atoi(argv[mode ? 5 : 4]);
	aacenc_reset(&enc);
	while ((n = fread(buf, 2, 160, in)) > 0) {
		int k = aacenc_feed(&enc, buf, (int)n, au);

		if (!k) continue;
		frames++; bytes += (unsigned)k;
		if (mode == 1) {
			uint8_t h[7];
			unsigned len = (unsigned)k + 7;

			h[0] = 0xff; h[1] = 0xf1; h[2] = (1 << 6) | (11 << 2) | 0; h[3] = (uint8_t)((1 << 6) | (len >> 11));
			h[4] = (uint8_t)(len >> 3); h[5] = (uint8_t)(((len & 7) << 5) | 0x1f); h[6] = 0xfc;
			fwrite(h, 1, 7, out); fwrite(au, 1, (size_t)k, out);
		} else if (mode == 2) {
			uint8_t h[2] = { (uint8_t)(k >> 8), (uint8_t)k };

			fwrite(h, 1, 2, out); fwrite(au, 1, (size_t)k, out);
		} else {
			printf("frame %lu: %d bytes sf %d bits %u\n", frames, k, enc.last_sf, enc.last_bits);
		}
	}
	if (mode && out != stdout) fclose(out);
	fprintf(stderr, "%lu frames, %lu bytes, %.0f bit/s\n", frames, bytes, frames ? bytes * 8.0 * 8000 / (frames * 1024.0) : 0.0);
	return 0;
}
