/* talk.h: two-way audio of tc100_rtsp, the speaker side (see talk.c) */
#ifndef TC100_TALK_H
#define TC100_TALK_H
#include <stdint.h>

void talk_init(void);					/* once at start: clears a speaker lock left by a dead instance */
void talk_rtp(int owner, const unsigned char *pkt, int n, uint64_t now_us);	/* one RTP packet (PCMA) of client number owner */
void talk_tick(uint64_t now_us);			/* every loop turn: closes the player 2 s after the last packet, reaps it */
void talk_release(int owner);				/* the client number owner is gone */
int talk_state(void);
struct aec;
void talk_set_aec(struct aec *a);			/* RTSP_AUDIO_AEC: play through the ALSA device and feed the echo canceller (NULL: aplay) */
int talk_hold_active(void);				/* 1 while a session plays through the device (the echo canceller handles the microphone) */
int talk_queued(void);					/* speaker frames written and not yet played, -1 when not playing through the device */					/* 0 idle, 1 playing */
void talk_shutdown(void);

#endif
