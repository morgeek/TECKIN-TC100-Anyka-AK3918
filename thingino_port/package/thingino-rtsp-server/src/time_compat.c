#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <time.h>

uint32_t get_safe_time_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)ts.tv_sec;
}

uint64_t get_safe_time_ntp(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    uint64_t ntp_sec = (uint64_t)ts.tv_sec + 2208988800ULL;
    uint64_t ntp_frac = ((uint64_t)ts.tv_nsec * 4294967296ULL) / 1000000000ULL;
    return (ntp_sec << 32) | (ntp_frac & 0xFFFFFFFF);
}
