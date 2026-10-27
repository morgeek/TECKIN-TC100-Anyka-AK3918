/* talk.h: two-way audio of tc100_rtsp, the speaker side (see talk.c) */
#ifndef TC100_TALK_H
#define TC100_TALK_H
#include <stdint.h>

void talk_init(void);					/* once at start: clears a speaker lock left by a dead instance */
void talk_rtp(int owner, const unsigned char *pkt, int n, uint64_t now_us);	/* one RTP packet (PCMA) of client number owner */
void talk_tick(uint64_t now_us);			/* every loop turn: closes the player 2 s after the last packet, reaps it */
void talk_release(int owner);				/* the client number owner is gone */
int talk_state(void);					/* 0 idle, 1 playing */
void talk_shutdown(void);

#endif
