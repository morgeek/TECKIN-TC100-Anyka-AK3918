/* alisten.h: listeners of tc100_rtsp's microphone capture (see alisten.c) */
#ifndef TC100_ALISTEN_H
#define TC100_ALISTEN_H
#include <stdint.h>

void lis_init(void);				/* creates the FIFO directory */
void lis_scan(uint64_t now_ms);			/* every 0.5 s or so: picks up new FIFOs, drops finished or stuck listeners */
int lis_count(void);				/* listeners now (the microphone is needed while there is one) */
void lis_write(const unsigned char *pcm, int n);	/* S16_LE mono 8 kHz, whole samples, n <= 4096; never blocks */
void lis_close_all(void);

#endif
