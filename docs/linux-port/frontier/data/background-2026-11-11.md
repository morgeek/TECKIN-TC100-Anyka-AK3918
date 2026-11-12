# Background load measured on two cameras, 2026-11-11 (read-only capture)

Two TC100 on the same firmware (3.0.0), daylight, one RTSP client each, H.265 1080p 25 fps, no recording. 25 samples
5 min apart (2 h 05 min, 7485 s) of /proc: meminfo, /proc/stat, and for each process PSS (smaps_rollup), utime +
stime (ticks at 100 Hz), minor faults. Two "bursts" of 136 s polled /proc every ~0.23 s for new processes (name and
parent); a process living less than ~0.2 s is mostly missed, so the bursts show *who* forks, not *how much*.

## Whole system (average over 2 h)

| | .11 | .24 |
|---|---|---|
| CPU busy (100 - idle) | 22.1 % | 24.8 % |
| user / system / softirq | 7.5 / 12.3 / 2.4 % | 8.4 / 13.8 / 2.5 % |
| tc100_rtsp (video) | 16.0 % | 17.1 % |
| all other long-lived processes together | 0.9 % | 1.1 % |
| **not explained by long-lived processes** (busy - softirq - the two lines above) | **~2.8 %** | **~4.1 %** |
| new processes per minute (`processes` in /proc/stat) | 77.5 (63-94 per 5 min) | 99.9 (66-150 per 5 min) |
| context switches / s, interrupts / s | 318 / 817 | 324 / 830 |
| load average (1 min) | 0.65-0.95 | 0.81-1.28 |

The "not explained" share is short-lived processes (fork + exec of busybox applets and shell scripts) plus kernel
threads: CPU spent by a process that dies before the next sample is never seen per process.

## Long-lived processes, CPU over the 2 h (share of one CPU)

| process | .11 | .24 | PSS kB (.11 / .24) |
|---|---|---|---|
| sh:housekeeper.sh (the scheduler loop itself) | 0.44 % | 0.49 % | 709 / 727 |
| tc100-supervisor (C, day/night, 5 s tick) | 0.11 % | 0.19 % | 111 / 130 |
| sh:cfg-persist | 0.13 % | 0.12 % | 220 / 212 |
| tc100-onvifd | 0.09 % | 0.09 % | 150 / 161 |
| tc100-mdnsd | 0.07 % | 0.07 % | 16 / 16 |
| tc100-mqttd | 0.03 % | 0.03 % | 147 / 140 |
| tc100-whep, wpa_supplicant, watchdog, syslogd, ntpd ... | < 0.03 % each | | |

housekeeper.sh also takes ~16 000 minor faults per 2 h in its own process (the ash heap growing and shrinking around
command substitutions).

## Who forks (both bursts on each camera, count of new processes seen, parent in brackets)

| new process (parent) | .11 #1 | .11 #2 | .24 #1 | .24 #2 |
|---|---|---|---|---|
| sh:wifi-quality.sh + its ping, awk, wc, timeout (timeout shows init as parent) | 17 | 12 | 19 | 13 |
| mqtt-bridge.sh subshells (mqtt-bridge.sh), + motion-detection, telnet-server, md5sum | 0 | 19 | 15 | 0 |
| sh:health-snapshot.sh and its subshells, onvif, ssh-server (housekeeper) | 0 | 11 | 9 | 0 |
| sh:wifi-roam.sh (housekeeper) | 1 | 2 | 0 | 2 |
| sh:net-guard.sh (housekeeper) | 1 | 0 | 1 | 1 |
| sh:reboot-tracker.sh + 3 grep + awk | 6 | 0 | 0 | 0 |
| rm, other `sh` (housekeeper), sdinfo-sd, log-persist, cfg-persist, kworker | 6 | 5 | 7 | 1 |
| total seen in 136 s | 31 | 49 | 51 | 17 |
| forks expected in 136 s from the counter | ~176 | ~176 | ~226 | ~226 |

So 70-90 % of the forks are too short to be caught: `$(...)` subshells and one-shot applets. The bursts where
mqtt-bridge.sh and health-snapshot.sh run (every 5 min) see 2-3 times more processes.

Periods from the code: wifi-quality.sh hk every 60 s (one ping to the router, iw station dump, awk); wifi-roam.sh
once every 60 s; net-guard.sh every 3rd minute; health-snapshot.sh every 300 s; the mqtt-bridge.sh slow health
collection (service_script_running_int on each control script) on its health cycle; service-watchdog ticks every 60 s
(pid files checked without a fork unless something failed).

## Memory, for the record (no leak)

| kB | .11 first -> last (min-max) | .24 first -> last (min-max) |
|---|---|---|
| MemTotal | 59976 | 59976 |
| MemAvailable | 22960 -> 22772 (22624-23628) | 21280 -> 22248 (21280-22752) |
| AnonPages | 2088 -> 1872 | 3256 -> 2204 |
| Cached / Shmem | 11796 / 1616 -> 11876 / 1696 | 11364 / 2128 -> 11428 / 2192 |
| Slab (unreclaimable) | 4360 (3588) -> 4356 (3548) | 4276 (3524) -> 4332 (3532) |
| sum of PSS of all processes | 5206 -> 4934 | 6271 -> 5044 |

No process grows over 2 h (PSS within a few kB, except tc100_rtsp which goes up and down with its buffers). Memory is
not the problem; CPU of the short-lived processes is.
