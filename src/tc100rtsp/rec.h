/* rec.h: local recording of tc100_rtsp (see rec.c) */
#ifndef TC100_REC_H
#define TC100_REC_H
#include <stdint.h>

#define REC_OFF		0
#define REC_ALWAYS	1	/* REC_WHEN=always */
#define REC_OFFLINE	2	/* REC_WHEN=offline: while the recorder (Frigate) does not receive the stream */
#define REC_MOTION	3	/* REC_WHEN=motion: while motion (or a sound event) is detected, + post-roll */

struct rec_cfg {
	int mode;		/* REC_* */
	char dir[160];		/* recording directory: /mnt/DCIM (a card, or a link to one) */
	char status[96];	/* status file (/var/run/tc100rec); <status>.pause pauses the recorder */
	int segment_s;		/* file length, cut at the next keyframe */
	int reserve_mb;		/* free space kept on the card: the oldest recordings are deleted */
	int offline_s;		/* REC_OFFLINE: start this long after the stream stopped reaching the recorder */
	int postroll_s;		/* REC_OFFLINE / REC_MOTION: keep recording this long after */
	int ring_kb;		/* frame queue (also the pre-roll); read once, when the recorder starts */
	int audio;		/* REC_AUDIO: a G.711 A-law track (8 kHz mono) next to the video, fed by rec_audio() */
};

/* main thread (the producer) */
int rec_config(const struct rec_cfg *c);	/* (re)configure; starts the writer thread the first time */
int rec_active(void);				/* 1 while frames are wanted (mode on, usable card, not paused) */
int rec_frame(const unsigned char *d, uint32_t len, uint64_t ts_us, int key, int hevc);	/* 0 when queued */
void rec_thumb(const unsigned char *jpg, uint32_t len, uint64_t key_ts_us);	/* picture of keyframe key_ts_us */
int rec_audio_wanted(void);			/* 1 while rec_audio() takes samples (recorder active and REC_AUDIO on) */
/* A-law bytes captured up to ts_us (same clock as rec_frame); gap: the capture was (re)started, bytes are missing before this one. 0 when queued */
int rec_audio(const unsigned char *alaw, uint32_t len, uint64_t ts_us, int gap);
void rec_inputs(int watched, int motion);	/* once a second: a client receives the stream / motion now */
void rec_shutdown(void);			/* finish the file (waits up to 3 s) */
int rec_idle(void);				/* queue empty (tests) */

#endif
