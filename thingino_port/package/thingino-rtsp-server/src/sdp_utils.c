#include "rtsp_server.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <arpa/inet.h>

// Generate SDP (Session Description Protocol) for RTSP stream (RFC 2435 JPEG)
int sdp_generate(char *buffer, size_t buffer_size, const rtsp_stream_t *stream, const char *server_ip) {
    if (!buffer || !stream || !server_ip) {
        return -1;
    }

    uint64_t now = get_safe_time_ntp();

    int len = snprintf(buffer, buffer_size,
        "v=0\r\n"
        "o=- %lld %lld IN IP4 %s\r\n"
        "s=%s\r\n"
        "c=IN IP4 %s\r\n"
        "t=0 0\r\n"
        "a=tool:thingino-rtsp-server\r\n"
        "m=video 0 RTP/AVP 26\r\n"
        "b=AS:%d\r\n"
        "a=framerate:%d\r\n"
        "a=rtpmap:26 JPEG/90000\r\n"
        "a=control:track1\r\n",
        now, now, server_ip,
        stream->name,
        server_ip,
        stream->bitrate > 0 ? stream->bitrate : 1500,
        stream->fps > 0 ? stream->fps : 10
    );

    if (len >= (int)buffer_size) {
        return -1;
    }

    return len;
}

int sdp_generate_multi(char *buffer, size_t buffer_size, const rtsp_stream_t *streams,
                      int stream_count, const char *server_ip) {
    if (!buffer || !streams || stream_count <= 0 || !server_ip) {
        return -1;
    }
    return sdp_generate(buffer, buffer_size, &streams[0], server_ip);
}

int sdp_parse(const char *sdp_data, rtsp_stream_t *stream) {
    (void)sdp_data; (void)stream;
    return 0;
}
