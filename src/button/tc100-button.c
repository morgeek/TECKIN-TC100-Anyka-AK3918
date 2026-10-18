/*
 * tc100-button — the reset button while the camera runs (same rules as
 * scripts/button-watch.sh, which stays as the fallback). One small process
 * blocked in read() instead of a shell loop with a dd | od pipeline (four
 * processes, ~230 KB of private memory, measured on a TC100).
 *
 *   held  3–7 s    open the rescue Wi-Fi access point (scripts/wifi-rescue.sh)
 *   held  8–19 s   reboot
 *   held 20 s +    firmware from flash: back to the code built into /usr
 *                  (flash-code.sh clear), then reboot; from the SD card: reboot
 *
 * Events: struct input_event of the 32-bit kernel (16 bytes: seconds,
 * microseconds, type, code, value), read from BUTTON_DEV (/dev/input/event0).
 * The actions run through /bin/sh, with the same environment overrides as the
 * shell version (tests): BUTTON_REBOOT_SECONDS, BUTTON_RESTORE_SECONDS,
 * BUTTON_RESCUE_SECONDS, BUTTON_FLASH_CODE, BUTTON_REBOOT_CMD, BUTTON_RESCUE,
 * TC100_STORAGE_FILE, BUTTON_TRACKER, BUTTON_LOGGER.
 */
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static const char *env(const char *k, const char *d) { const char *v = getenv(k); return v && v[0] ? v : d; }
static long envn(const char *k, long d) { const char *v = getenv(k); return v && v[0] ? atol(v) : d; }

/* sh -c "<cmd>" with the arguments as $1.. (no quoting problems); wait unless bg */
static void run(int bg, const char *cmd, const char *a1, const char *a2)
{
    pid_t p = fork();
    if (p == 0) {
        int fd = open("/dev/null", O_RDWR);
        if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
        if (bg) setsid();
        execl("/bin/sh", "sh", "-c", cmd, "sh", a1 ? a1 : "", a2 ? a2 : "", (char *)NULL);
        _exit(127);
    }
    if (p > 0 && !bg) waitpid(p, NULL, 0);
}

static void logmsg(const char *msg)
{
    run(0, "${BUTTON_LOGGER:-logger} -t tc100-event -p user.err \"button: $1\"", msg, NULL);
}

static int from_flash(void)
{
    char b[16] = "";
    FILE *f = fopen(env("TC100_STORAGE_FILE", "/tmp/tc100-storage"), "r");
    if (f) { if (!fgets(b, sizeof(b), f)) b[0] = 0; fclose(f); }
    return !strncmp(b, "flash", 5);
}

static void reboot_now(long held, const char *why)
{
    char m[96], intent[64];
    if (why) { snprintf(m, sizeof(m), "held %lds: %s", held, why); logmsg(m); }
    snprintf(intent, sizeof(intent), "reset button held %lds", held);
    run(0, "sh \"${BUTTON_TRACKER:-/mnt/scripts/reboot-tracker.sh}\" intent \"$1\"", intent, NULL);
    sync();
    run(0, "$1", env("BUTTON_REBOOT_CMD", "/sbin/reboot"), NULL);
}

int main(void)
{
    const char *dev = env("BUTTON_DEV", "/dev/input/event0");
    long reboot_s = envn("BUTTON_REBOOT_SECONDS", 8), restore_s = envn("BUTTON_RESTORE_SECONDS", 20);
    long rescue_s = envn("BUTTON_RESCUE_SECONDS", 3), pressed = -1;
    unsigned char ev[16];
    int fd = open(dev, O_RDONLY);
    signal(SIGCHLD, SIG_DFL);
    if (fd < 0) { fprintf(stderr, "no %s\n", dev); return 1; }
    for (;;) {
        ssize_t n = 0, r;
        long sec, held;
        unsigned type, value;
        while (n < 16 && (r = read(fd, ev + n, (size_t)(16 - n))) > 0) n += r;
        if (n < 16) return 0;                                   /* end of input */
        while (waitpid(-1, NULL, WNOHANG) > 0) ;                /* reap the access point starter */
        sec = (long)((uint32_t)ev[0] | (uint32_t)ev[1] << 8 | (uint32_t)ev[2] << 16 | (uint32_t)ev[3] << 24);
        type = (unsigned)(ev[8] | ev[9] << 8);
        value = (unsigned)(ev[12] | ev[13] << 8);
        if (type != 1) continue;                                /* EV_KEY only */
        if (value) { if (pressed < 0) pressed = sec; continue; }
        if (pressed < 0) continue;
        held = sec - pressed; pressed = -1;
        if (held >= restore_s) {
            if (from_flash() && access(env("BUTTON_FLASH_CODE", "/usr/tc100/scripts/flash-code.sh"), X_OK) == 0) {
                char m[64];
                snprintf(m, sizeof(m), "held %lds: back to the built-in code, reboot", held);
                logmsg(m);
                run(0, "sh \"$1\" clear", env("BUTTON_FLASH_CODE", "/usr/tc100/scripts/flash-code.sh"), NULL);
                reboot_now(held, NULL);
            } else
                reboot_now(held, "reboot");
        } else if (held >= reboot_s) {
            reboot_now(held, "reboot");
        } else if (held >= rescue_s) {
            char m[64];
            snprintf(m, sizeof(m), "held %lds: rescue access point", held);
            logmsg(m);
            run(1, "sh \"$1\" start-ap \"reset button\"", env("BUTTON_RESCUE", "/mnt/scripts/wifi-rescue.sh"), NULL);
        }
    }
}
