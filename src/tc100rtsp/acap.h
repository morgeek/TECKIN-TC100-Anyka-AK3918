/* acap.h: the microphone read straight from the ALSA kernel interface (no arecord, no libasound), see acap.c */
#ifndef TC100_ACAP_H
#define TC100_ACAP_H

int acap_open(const char *dev);			/* capture device node: fd running at 8 kHz mono S16_LE, or -1 (errno) */
int acap_read(int fd, void *buf, int bytes);	/* bytes read, 0 none yet, -1 the device failed */
int acap_delay_bytes(int fd);			/* captured bytes not read yet */

#endif
