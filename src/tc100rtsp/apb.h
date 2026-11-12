/* apb.h: the speaker played straight through the ALSA kernel interface (no aplay), see apb.c */
#ifndef TC100_APB_H
#define TC100_APB_H
#include <stdint.h>

int apb_open(const char *dev, int rate);		/* playback device node (stereo S16_LE at rate Hz, non-blocking), fd or -1 (errno) */
int apb_write(int fd, const int16_t *mono, int n);	/* queues up to n mono frames (sent to both channels): frames taken (0 when
							 * the buffer is full), -1 when the device failed, -2 when it keeps underrunning (more
							 * than one recovery a second or eight in all). A single underrun is recovered here. */
int apb_queued(int fd);					/* frames queued and not yet played, -1 on error */
void apb_close(int fd);					/* stops at once (what is queued is dropped) */

#endif
