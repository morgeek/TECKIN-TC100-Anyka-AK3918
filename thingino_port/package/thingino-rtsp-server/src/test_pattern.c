#define _GNU_SOURCE
#include "rtsp_server.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <time.h>
#include <sys/stat.h>

#define MAX_JPEG_BUF (128 * 1024)
#define MAX_PAYLOAD_SIZE 1400

static void get_jpeg_dimensions(const uint8_t *data, int len, int *w, int *h) {
    *w = 640;
    *h = 360;
    for (int i = 0; i < len - 9; i++) {
        if (data[i] == 0xFF && (data[i+1] == 0xC0 || data[i+1] == 0xC2)) {
            *h = (data[i+5] << 8) | data[i+6];
            *w = (data[i+7] << 8) | data[i+8];
            return;
        }
    }
}

// Optical Live Streamer Thread (RFC 2435 RTP JPEG)
void* streaming_thread_func(void *arg) {
    rtsp_server_t *server = (rtsp_server_t*)arg;
    uint8_t *jpeg_buffer = (uint8_t*)malloc(MAX_JPEG_BUF);
    uint32_t frame_number = 0;
    time_t last_mtime = 0;

    if (!jpeg_buffer) {
        printf("Failed to allocate JPEG streaming buffer\n");
        return NULL;
    }

    printf("[thingino-rtsp] Optical streaming thread active (RFC 2435 JPEG)\n");

    while (server->streaming_active) {
        // 1. Check if any client is actively streaming
        int active_clients = 0;
        for (int i = 0; i < RTSP_MAX_CLIENTS; i++) {
            if (server->clients[i].active && server->clients[i].streaming && server->clients[i].rtp_socket >= 0) {
                active_clients++;
            }
        }

        if (active_clients == 0) {
            usleep(100000); // 100ms idle sleep
            continue;
        }

        // 2. Read live optical frame from /tmp/stream.jpg
        struct stat st;
        const char *stream_path = "/tmp/stream.jpg";
        if (stat(stream_path, &st) < 0 || st.st_size < 100 || st.st_size > MAX_JPEG_BUF) {
            stream_path = "/tmp/currentpic.cache.jpg";
            if (stat(stream_path, &st) < 0 || st.st_size < 100 || st.st_size > MAX_JPEG_BUF) {
                usleep(50000);
                continue;
            }
        }

        // If file hasn't changed and not first frame, wait briefly
        if (st.st_mtime == last_mtime && frame_number > 0) {
            usleep(40000); // 40ms (~25 FPS check)
            continue;
        }
        last_mtime = st.st_mtime;

        FILE *fp = fopen(stream_path, "rb");
        if (!fp) {
            usleep(50000);
            continue;
        }
        size_t file_size = fread(jpeg_buffer, 1, MAX_JPEG_BUF, fp);
        fclose(fp);

        if (file_size < 100) {
            usleep(50000);
            continue;
        }

        int width = 640, height = 360;
        get_jpeg_dimensions(jpeg_buffer, (int)file_size, &width, &height);

        // Calculate 90kHz timestamp for video
        struct timespec ts_now;
        clock_gettime(CLOCK_MONOTONIC, &ts_now);
        uint32_t timestamp = (uint32_t)((ts_now.tv_sec * 90000) + (ts_now.tv_nsec * 9 / 100000));

        // 3. Send RFC 2435 RTP packets to all active streaming clients
        for (int i = 0; i < RTSP_MAX_CLIENTS; i++) {
            if (server->clients[i].active && server->clients[i].streaming && server->clients[i].rtp_socket >= 0) {
                size_t offset = 0;

                while (offset < file_size) {
                    size_t chunk_size = file_size - offset;
                    if (chunk_size > MAX_PAYLOAD_SIZE) {
                        chunk_size = MAX_PAYLOAD_SIZE;
                    }

                    int is_last = (offset + chunk_size >= file_size);

                    // Build RTP Packet (12 bytes RTP header + 8 bytes RFC 2435 JPEG header + payload)
                    uint8_t packet[1500];

                    // RTP Header
                    packet[0] = 0x80; // V=2, P=0, X=0, CC=0
                    packet[1] = (is_last ? 0x80 : 0x00) | 26; // Marker bit on last fragment, Payload Type 26 (JPEG)
                    uint16_t seq = server->clients[i].rtp_sequence++;
                    packet[2] = (seq >> 8) & 0xFF;
                    packet[3] = seq & 0xFF;
                    packet[4] = (timestamp >> 24) & 0xFF;
                    packet[5] = (timestamp >> 16) & 0xFF;
                    packet[6] = (timestamp >> 8) & 0xFF;
                    packet[7] = timestamp & 0xFF;
                    uint32_t ssrc = server->clients[i].rtp_ssrc;
                    packet[8] = (ssrc >> 24) & 0xFF;
                    packet[9] = (ssrc >> 16) & 0xFF;
                    packet[10] = (ssrc >> 8) & 0xFF;
                    packet[11] = ssrc & 0xFF;

                    // RFC 2435 JPEG Header (8 bytes)
                    packet[12] = 0; // Type-specific
                    packet[13] = (offset >> 16) & 0xFF; // Fragment offset high
                    packet[14] = (offset >> 8) & 0xFF;  // Fragment offset mid
                    packet[15] = offset & 0xFF;         // Fragment offset low
                    packet[16] = 1; // Type: 1 (YUV 4:2:2)
                    packet[17] = 65; // Q factor (1-99)
                    packet[18] = (uint8_t)(width / 8);  // Width / 8
                    packet[19] = (uint8_t)(height / 8); // Height / 8

                    // Copy JPEG payload chunk
                    memcpy(packet + 20, jpeg_buffer + offset, chunk_size);

                    rtp_send_packet(server->clients[i].rtp_socket, &server->clients[i].rtp_addr,
                                    packet, 20 + chunk_size);

                    offset += chunk_size;
                }
            }
        }

        frame_number++;
        usleep(40000); // 40ms interval
    }

    printf("[thingino-rtsp] Streaming thread stopped\n");
    free(jpeg_buffer);
    return NULL;
}

int start_streaming_thread(rtsp_server_t *server) {
    if (!server || server->streaming_active) return -1;
    server->streaming_active = 1;
    if (pthread_create(&server->streaming_thread, NULL, streaming_thread_func, server) != 0) {
        server->streaming_active = 0;
        return -1;
    }
    return 0;
}

void stop_streaming_thread(rtsp_server_t *server) {
    if (!server || !server->streaming_active) return;
    server->streaming_active = 0;
    pthread_join(server->streaming_thread, NULL);
}
