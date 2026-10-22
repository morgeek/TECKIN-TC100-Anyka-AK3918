#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <linux/videodev2.h>
#include "jpge.h"

#define MAIN_W 1920
#define MAIN_H 1080
#define SUB_W  640
#define SUB_H  360

static volatile int g_running = 1;
static void sig_handler(int sig) { (void)sig; g_running = 0; }

static inline void nv12_to_rgb(const unsigned char *y_plane, const unsigned char *uv_plane,
                               int width, int height, unsigned char *rgb_out) {
    for (int y = 0; y < height; y++) {
        const unsigned char *y_row = y_plane + y * width;
        const unsigned char *uv_row = uv_plane + (y / 2) * width;
        unsigned char *rgb_row = rgb_out + y * width * 3;
        for (int x = 0; x < width; x += 2) {
            int y0 = y_row[x];
            int y1 = y_row[x + 1];
            int u = uv_row[x] - 128;
            int v = uv_row[x + 1] - 128;

            int r_term = 409 * v + 128;
            int g_term = -100 * u - 208 * v + 128;
            int b_term = 516 * u + 128;

            int c0 = (y0 - 16) * 298;
            int r0 = (c0 + r_term) >> 8;
            int g0 = (c0 + g_term) >> 8;
            int b0 = (c0 + b_term) >> 8;
            rgb_row[x * 3]     = (unsigned char)(r0 < 0 ? 0 : (r0 > 255 ? 255 : r0));
            rgb_row[x * 3 + 1] = (unsigned char)(g0 < 0 ? 0 : (g0 > 255 ? 255 : g0));
            rgb_row[x * 3 + 2] = (unsigned char)(b0 < 0 ? 0 : (b0 > 255 ? 255 : b0));

            int c1 = (y1 - 16) * 298;
            int r1 = (c1 + r_term) >> 8;
            int g1 = (c1 + g_term) >> 8;
            int b1 = (c1 + b_term) >> 8;
            rgb_row[(x + 1) * 3]     = (unsigned char)(r1 < 0 ? 0 : (r1 > 255 ? 255 : r1));
            rgb_row[(x + 1) * 3 + 1] = (unsigned char)(g1 < 0 ? 0 : (g1 > 255 ? 255 : g1));
            rgb_row[(x + 1) * 3 + 2] = (unsigned char)(b1 < 0 ? 0 : (b1 > 255 ? 255 : b1));
        }
    }
}

struct buffer {
    void *start;
    size_t length;
};

int main(int argc, char **argv) {
    const char *dev_name = argc > 1 && argv[1][0] != '-' ? argv[1] : "/dev/video0";
    int daemonize = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-d") == 0) daemonize = 1;
    }

    if (daemonize) {
        if (daemon(0, 0) < 0) {
            perror("daemon");
            return 1;
        }
    }

    // Immune to OOM Killer
    FILE *f_oom = fopen("/proc/self/oom_score_adj", "w");
    if (f_oom) {
        fputs("-1000\n", f_oom);
        fclose(f_oom);
    }

    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    // Wait for device node to be created by mdev/udev if booting
    int fd = -1;
    for (int retry = 0; retry < 50 && g_running; retry++) {
        fd = open(dev_name, O_RDWR | O_NONBLOCK, 0);
        if (fd >= 0) break;
        usleep(100000); // 100ms
    }

    if (fd < 0) {
        fprintf(stderr, "[-] open %s failed: %s (errno %d)\n", dev_name, strerror(errno), errno);
        return 1;
    }

    // Set format
    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = MAIN_W;
    fmt.fmt.pix.height = MAIN_H;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    ioctl(fd, VIDIOC_S_FMT, &fmt);

    // Request 2 buffers (Double-buffering saves ~7MB DMA memory)
    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = 2;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (ioctl(fd, VIDIOC_REQBUFS, &req) < 0) {
        fprintf(stderr, "[-] VIDIOC_REQBUFS failed: %s\n", strerror(errno));
        close(fd);
        return 1;
    }

    struct buffer *buffers = (struct buffer*)calloc(req.count, sizeof(*buffers));
    for (unsigned int i = 0; i < req.count; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (ioctl(fd, VIDIOC_QUERYBUF, &buf) < 0) {
            perror("VIDIOC_QUERYBUF");
            return 1;
        }
        buffers[i].length = buf.length;
        buffers[i].start = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buf.m.offset);
        if (buffers[i].start == MAP_FAILED) {
            perror("mmap");
            return 1;
        }
        if (ioctl(fd, VIDIOC_QBUF, &buf) < 0) {
            perror("VIDIOC_QBUF");
            return 1;
        }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(fd, VIDIOC_STREAMON, &type) < 0) {
        perror("VIDIOC_STREAMON");
        return 1;
    }

    // Write PID file
    FILE *pfp = fopen("/var/run/tc100_streamer.pid", "w");
    if (pfp) { fprintf(pfp, "%d\n", getpid()); fclose(pfp); }

    // Preallocate encoding buffers
    unsigned char *sub_rgb = (unsigned char*)malloc(SUB_W * SUB_H * 3);
    unsigned char *sub_jpg = (unsigned char*)malloc(128 * 1024);
    unsigned char *main_rgb = (unsigned char*)malloc(MAIN_W * MAIN_H * 3);
    unsigned char *main_jpg = (unsigned char*)malloc(512 * 1024);

    jpge::params p_sub;
    p_sub.m_quality = 65;
    p_sub.m_subsampling = jpge::H2V2;

    jpge::params p_main;
    p_main.m_quality = 80;
    p_main.m_subsampling = jpge::H2V2;

    struct timespec last_snap_time = {0, 0};
    struct timespec last_stream_time = {0, 0};
    struct timespec last_luma_time = {0, 0};

    while (g_running) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv = { .tv_sec = 2, .tv_usec = 0 };
        int r = select(fd + 1, &fds, NULL, NULL, &tv);
        if (r <= 0) continue;

        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        if (ioctl(fd, VIDIOC_DQBUF, &buf) < 0) {
            continue;
        }

        const unsigned char *raw_data = (const unsigned char*)buffers[buf.index].start;

        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);

        // 1. Ambient Luminance Calculation (every 500ms)
        double elapsed_luma = (now.tv_sec - last_luma_time.tv_sec) + (now.tv_nsec - last_luma_time.tv_nsec) / 1e9;
        if (elapsed_luma >= 0.5) {
            last_luma_time = now;
            const unsigned char *sub_y = raw_data + (MAIN_W * MAIN_H * 3 / 2);
            uint32_t sum = 0;
            int samples = 0;
            for (int sy = 10; sy < SUB_H - 10; sy += 16) {
                for (int sx = 10; sx < SUB_W - 10; sx += 16) {
                    sum += sub_y[sy * SUB_W + sx];
                    samples++;
                }
            }
            int avg_luma = samples > 0 ? (int)(sum / samples) : 50;
            FILE *lfp = fopen("/tmp/cam_luma.tmp", "w");
            if (lfp) {
                fprintf(lfp, "%d\n", avg_luma);
                fclose(lfp);
                rename("/tmp/cam_luma.tmp", "/tmp/cam_luma");
            }
        }

        // 2. High-Frequency Live Sub-Stream Frame (/tmp/stream.jpg, ~3-4 FPS)
        double elapsed_stream = (now.tv_sec - last_stream_time.tv_sec) + (now.tv_nsec - last_stream_time.tv_nsec) / 1e9;
        if (elapsed_stream >= 0.25) {
            last_stream_time = now;
            const unsigned char *sub_y = raw_data + (MAIN_W * MAIN_H * 3 / 2);
            const unsigned char *sub_uv = sub_y + (SUB_W * SUB_H);
            nv12_to_rgb(sub_y, sub_uv, SUB_W, SUB_H, sub_rgb);

            int sub_jpg_size = 128 * 1024;
            if (jpge::compress_image_to_jpeg_file_in_memory(sub_jpg, sub_jpg_size, SUB_W, SUB_H, 3, sub_rgb, p_sub)) {
                FILE *sfp = fopen("/tmp/stream.jpg.tmp", "wb");
                if (sfp) {
                    fwrite(sub_jpg, 1, sub_jpg_size, sfp);
                    fclose(sfp);
                    rename("/tmp/stream.jpg.tmp", "/tmp/stream.jpg");
                }
                FILE *ffp = fopen("/tmp/frame_ch0.jpg.tmp", "wb");
                if (ffp) {
                    fwrite(sub_jpg, 1, sub_jpg_size, ffp);
                    fclose(ffp);
                    rename("/tmp/frame_ch0.jpg.tmp", "/tmp/frame_ch0.jpg");
                }
            }
        }

        // 3. 1080p Full HD Snapshot (/tmp/currentpic.cache.jpg, every 2s or on demand)
        int force_snap = (access("/tmp/snapshot_request", F_OK) == 0);
        double elapsed_snap = (now.tv_sec - last_snap_time.tv_sec) + (now.tv_nsec - last_snap_time.tv_nsec) / 1e9;
        if (force_snap || elapsed_snap >= 2.0 || last_snap_time.tv_sec == 0) {
            last_snap_time = now;
            if (force_snap) unlink("/tmp/snapshot_request");

            const unsigned char *main_y = raw_data;
            const unsigned char *main_uv = raw_data + (MAIN_W * MAIN_H);
            nv12_to_rgb(main_y, main_uv, MAIN_W, MAIN_H, main_rgb);

            int main_jpg_size = 512 * 1024;
            if (jpge::compress_image_to_jpeg_file_in_memory(main_jpg, main_jpg_size, MAIN_W, MAIN_H, 3, main_rgb, p_main)) {
                FILE *mfp = fopen("/tmp/currentpic.cache.jpg.tmp", "wb");
                if (mfp) {
                    fwrite(main_jpg, 1, main_jpg_size, mfp);
                    fclose(mfp);
                    rename("/tmp/currentpic.cache.jpg.tmp", "/tmp/currentpic.cache.jpg");
                }
                FILE *tfp = fopen("/tmp/currentpic.cache.ts.tmp", "w");
                if (tfp) {
                    fprintf(tfp, "%ld\n", (long)time(NULL));
                    fclose(tfp);
                    rename("/tmp/currentpic.cache.ts.tmp", "/tmp/currentpic.cache.ts");
                }
            }
        }

        // Requeue buffer
        ioctl(fd, VIDIOC_QBUF, &buf);
    }

    ioctl(fd, VIDIOC_STREAMOFF, &type);
    for (unsigned int i = 0; i < req.count; i++) munmap(buffers[i].start, buffers[i].length);
    free(buffers);
    free(sub_rgb); free(sub_jpg); free(main_rgb); free(main_jpg);
    close(fd);
    unlink("/var/run/tc100_streamer.pid");
    return 0;
}
