/*
 * libfpslock.so — keep the sensor at its configured frame rate.
 *
 * The vendor libplat_vi.so (V1.0.04 on the TC100 / AK3918EV300) starts a
 * "vi_change_fps" thread from ak_vi_set_channel_attr() -> isp_fps_main(),
 * enabled by default. It lowers the sensor frame rate (25 -> ~10 fps) when
 * the AE gain rises in low light and raises it back later, which makes the
 * RTSP frame rate oscillate under Frigate.
 *
 * The library exports ak_vi_set_switch_fps_enable(handle, 0) to turn that
 * thread off, but v4l2rtspserver never calls it. v4l2rtspserver does call
 * ak_vi_set_channel_attr() and then ak_vi_set_fps() once at start-up, so this
 * shim interposes ak_vi_set_fps(): it disables the automatic switch first,
 * then forwards to the real function so the configured rate is applied.
 *
 * Load it for v4l2rtspserver only:  LD_PRELOAD=/mnt/lib/libfpslock.so
 * Build: src/fpslock/build.sh (Anyka arm-anykav200 uClibc toolchain).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

typedef int (*vi_set_fps_fn)(void *handle, int fps);
typedef int (*vi_switch_fn)(void *handle, int enable);

int ak_vi_set_fps(void *handle, int fps)
{
    static vi_set_fps_fn real_set_fps;
    static vi_switch_fn set_switch;
    int rc;

    if (!real_set_fps)
        real_set_fps = (vi_set_fps_fn)dlsym(RTLD_NEXT, "ak_vi_set_fps");
    if (!set_switch)
        set_switch = (vi_switch_fn)dlsym(RTLD_NEXT, "ak_vi_set_switch_fps_enable");

    if (handle && set_switch) {
        rc = set_switch(handle, 0);
        fprintf(stderr, "[fpslock] auto fps switch disabled (rc=%d)\n", rc);
    } else {
        fprintf(stderr, "[fpslock] ak_vi_set_switch_fps_enable unavailable, switch left on\n");
    }

    if (!real_set_fps) {
        fprintf(stderr, "[fpslock] real ak_vi_set_fps not found\n");
        return -1;
    }
    rc = real_set_fps(handle, fps);
    fprintf(stderr, "[fpslock] sensor fps set to %d (rc=%d)\n", fps, rc);
    return rc;
}
