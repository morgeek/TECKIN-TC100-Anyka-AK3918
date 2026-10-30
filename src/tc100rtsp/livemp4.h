/* livemp4.h: live H.264 video for the browser (fragmented MP4 into FIFOs, see livemp4.c) */
#ifndef TC100_LIVEMP4_H
#define TC100_LIVEMP4_H
#include <stdint.h>

void live_init(void);			/* once: directory, stale FIFOs removed */
void live_scan(uint64_t now_ms);	/* often (it throttles itself): new FIFOs, viewers to drop, pending data */
int live_count(void);			/* viewers attached: the encoder of the live stream has to run */
/* the stream live.cgi serves: si 0 main / 1 sub, name for the status file, its SPS (the codec string for the page);
 * si < 0: none (both streams are H.265): live.cgi answers 415 */
void live_stream(int si, const char *name, const unsigned char *sps, int sps_len);
int live_wants(int si);			/* 1 when this stream is the live one and a viewer is attached */
/* one access unit (Annex B, as the encoder made it) of stream si, captured at ts_us */
void live_frame(int si, const unsigned char *d, uint32_t len, uint64_t ts_us, int key);
void live_close_all(void);

#endif
