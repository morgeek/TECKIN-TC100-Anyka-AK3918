# Acceptance bench for the camera (recette)

A test tool for the 3.0.2 final. It runs the scriptable checks of `docs/linux-port/readiness-3.0.2.md` (section 1)
on one camera, so a tester runs one command per camera instead of many hand commands. It is not part of any build:
no squashfs, SD package, update tar or test pack takes this folder (`tests/test_recette.py` checks it).

## Files

- `recette.sh`: runs ON the camera (BusyBox ash, as root). One function per check; prints one line per check,
  `RESULT <ENTRY-ID> <check> PASS|FAIL|SKIP <evidence>`, and writes `results.txt`, `recette.log`, `summary.txt` and
  `done` in a run folder on the camera (`/tmp/recette-<date>/`, RAM).
- `recette-host.sh`: runs on the tester's machine (Linux or macOS: sh, ssh, scp, curl, nc; optional ffprobe,
  avahi-browse, mosquitto_pub / mosquitto_sub). It runs the checks that must come from another LAN address, copies
  `recette.sh` to the camera, starts it detached (`nohup`, so a check that cuts the Wi-Fi does not stop it), waits
  for its `done` file, fetches the results and prints one summary.

## How to run

```sh
sh tests/camera/recette-host.sh --list                    # host checks
sh tests/camera/recette.sh --list                         # camera checks (run on the camera, or from this folder)
sh tests/camera/recette-host.sh --dry-run --camera 192.168.1.50      # what would run; no connection
RECETTE_PASS='...' sh tests/camera/recette-host.sh --camera 192.168.1.50 --only AUDIT-1116-NET
RECETTE_PASS='...' sh tests/camera/recette-host.sh --camera 192.168.1.50 --disruptive --wifi
```

- `--only ID,ID`: run only these entry IDs (for example `HARDEN,FAILCOUNT`).
- `--disruptive`: allows the checks that kill or restart the video server, switch day and night, turn privacy on, or
  stop a process (`dist`). Without it they are SKIPped with "needs --disruptive".
- `--wifi`: allows the Wi-Fi checks (`wlan0` down and up 20 times, five `wpa_cli reassociate`). The camera's Wi-Fi
  is cut for a few seconds at a time; the bench restores it (up, reassociate, 60 s per try, three tries) at the end
  and on interrupt. There is no power action anywhere.
- `--dry-run`: one line per selected check, nothing is run and no connection is made.

Full run: about 45 minutes on the camera plus about 15 minutes on the host (the lockout check waits 5 minutes, the
MQTT and open-time checks wait a minute each). Shorter runs: `RECETTE_KILLS=10 RECETTE_WIFI_CYCLES=3`
(in `RECETTE_CAMERA_ARGS` for the host script, or in the environment of `recette.sh` run by hand).

## Environment

| Variable | Used by | Meaning |
|---|---|---|
| `RECETTE_PASS` | host, camera | the camera's web / RTSP password (root). Sent to the camera on stdin into `/tmp/recette.pass` (umask 077), read and deleted at once. Without it the password checks are SKIPped. |
| `RECETTE_CAMERA` / `--camera` | host | IP or name of the camera. ssh as `RECETTE_CAMERA_USER` (default root), with a key or agent. |
| `RECETTE_ONVIF_PORT` | host | default 8081 (`onvif.conf` ONVIF_PORT) |
| `RECETTE_MQTT_HOST`, `RECETTE_MQTT_PORT`, `RECETTE_MQTT_USER`, `RECETTE_MQTT_PASS`, `RECETTE_MQTT_ROOT` | host | broker and the camera's topic root. Without host and root, R3-MQTT and SMALL-A R5 are SKIPped. |
| `RECETTE_KILLS` | camera | kill -TERM cycles, default 50 |
| `RECETTE_STREAM_CYCLES` | camera | stop/start cycles, default 20 |
| `RECETTE_WIFI_CYCLES` | camera | Wi-Fi down/up cycles, default 20 |
| `RECETTE_CONTROL=1` | camera | the irq_unlazy control run (about 26 more restarts) |
| `RECETTE_DN_CYCLES` | camera | day/night cycles for B4-HUE, default 2 |
| `RECETTE_FORK_WINDOW`, `RECETTE_FORK_MAX` | camera | WIFIQ-FORKS window (600 s) and the limit in forks per minute (no limit: SKIP with the rate) |
| `RECETTE_IDLE_S`, `RECETTE_LOCK_WAIT_S`, `RECETTE_TIMEOUT_S` | host | W3 idle time (60), lockout wait (310), wait for the camera (4 h) |

Nothing is ever printed or logged with a password. The camera's password reaches the bench through a file
(`/tmp/recette.pass`, mode 0600 under umask 077, deleted at once) and the curl calls through a config file; the
MQTT broker settings go to a mosquitto options file in a mode-700 folder (`XDG_CONFIG_HOME`, removed at exit; the
one option per line with its dash, `-h`, `-p`, `-u`, `-P`, as mosquitto 2.x reads them from the file; a password with
spaces does not fit this format). Known
exception, on the tester's own machine only: `ffprobe` takes the stream URL, password included, on its command line,
so it is visible in the process list while it runs. Output that could show the password is masked by a fixed-string
replacement.

## What it covers

Each check prints one result. Evidence is in `recette.log` of the run folder.

- **Kernel and video server (AUDIT-1116-KERNEL, VENCIRQ):** dmesg scan for oops, warnings, lockups, unbalanced
  IRQs; kill -TERM loop with a clean first picture and a counting encoder interrupt; stop/start cycles; the
  `irq_unlazy` switch and the control run; a 60 s interrupt sample against the encoded pictures.
- **Wi-Fi (AUDIT-1116-USB):** down/up loop with timing and ping loss on the gateway; `wpa_cli reassociate` x5; the
  URB counters of `wifi-stall-watch.sh`.
- **Capture stall (AUDIT-1116-RTSP):** `RTSP_CAPTURE_STALL_S=5` with SIGSTOP (exit 3, restart); no spurious
  exit 3 afterwards; `arecord` kill if one runs; SETUP of track2 and track3 gives 404 (host, audio off); a TCP client
  that stops reading is closed (host).
- **Network (AUDIT-1116-NET):** HTTP 431 for an oversized header; normal requests with a large cookie are not 431;
  10 wrong logins lock the host's address for 5 min, the camera's own calls are not locked and the right login
  works after the wait; ONVIF without a token gives NotAuthorized; ssh maps `libnetacl-musl.so`; no "WITHOUT the LAN
  filter" line.
- **Config and state (B1, B2/B3, B4, T1B5, W5):** password file mode 0600 and no temp left; no "is larger than"
  line; hue in the ISP status against the log, and HUE unchanged over day/night cycles; the native `isp_tune` JSON
  equals the CGI; `fullconfig` answers `text/plain`; `hw_state` calls add no audit line.
- **Video (CLEANUP-1124, SMALL-B, W1, W3):** STAT fields in order with pic_fail and cap_stall 0; direct capture
  start lines; ffprobe of the main (`/video0`) and sub (`/video1`) streams; privacy `pp_ms` not higher with the
  privacy file; encoder opens without failed pictures; open time after an idle minute (host, ffprobe).
- **Small fixes (SMALL-A, WIFIQ-FORKS):** daynight.log length, no leftover `*.tmp` in /mnt/config, dropbear pid
  file, memory-hourly freshness; a hold restart when a hold is in the log; wifi-quality file keys and fork rate; the
  mDNS TXT record (host, avahi-browse); two MQTT events at once (host).
- **Counters and hardening (FAILCOUNT, MEMWATCH, HARDEN):** the counters file against the STAT tail; the kill loop
  counts starts +1 with exit3 unchanged; memory-hourly header; grep for "stack smashing" and "illegal instruction";
  two `top` snapshots.
- **Retained MQTT command (R3-MQTT, host):** a retained snapshot is not run, the bridge logs "retained command
  ignored", a live snapshot is answered, the retained message is cleared.

## What stays manual (SKIP with the reason in the result line)

The owner's eye, a power action, the UART, the SD card, a flash write, or a time of more than a session:
web-UI typing (password, Wi-Fi, OSD, slider and hue changes, Settings tabs), the rescue button and the rescue
telnet, power pulls and early-crash safe mode, the Wi-Fi driver unbind/bind (a failed bind needs the UART), the
web update cases, the flash-boot hook check, FTP, the stackbad rescue test, the 3-hour, 12-hour, 24-hour and
3-day soaks, the day/night hour, the ONVIF reconnect after an unplug, a non-private address, MQTT motion and ONVIF
events in Home Assistant, and the walk-in motion checks. The DN-FLAP hold restart (`auto-night-detection restart`, which rewrites the
day/night setting) is manual too. The bench never restarts the camera; the owner does that.

## Safety

- No flash, MTD, U-Boot environment, settings-slot or SD card write; `tests/test_recette.py` checks the scripts for
  the words of those operations.
- `/mnt/config` is detect-only. The bench reads it (an md5 list at the start, no copy, so no secret is left in /tmp),
  compares it at the end and never writes, restores or removes anything in it (a test guards this). Result
  `GLOBAL config-unchanged`: FAIL when a settings file changed or appeared or went (rtspserver.conf, rtsp.env,
  daynight.conf, boot.conf, isp_tune.conf, mqtt.conf, sound_detection.conf, onvif.conf, timezone.conf, user.pwd,
  wpa_supplicant.conf); the files the camera's own daemons write (for example `awb.state` written by tc100_rtsp, the
  net-guard counter) are an `INFO` line, not a FAIL. A web save by the owner during the run is a FAIL too: read it.
- Night cycles run `nightmode.sh` with `NIGHT_KEEP_AUTO=1`, which keeps the automatic mode: nothing is written to
  `rtspserver.conf` (`auto-night-detection` is not stopped). At the end, with automatic mode on (`daynight=2`) and the
  night job running, a new nonce goes into its RAM flag `/var/run/tc100-sv.night` (the way supervisor.sh starts the
  job): the daemon re-decides from the current picture on its next look, with no config write. The tester watches the
  next switch (an `INFO` line says so). Without automatic mode the starting state is restored with the forced switch.
  The hold-restart check (`auto-night-detection restart` rewrites `daynight=3`) is manual.
- The privacy file, the irq switch, the Wi-Fi link with its address and default route, the video server and a
  SIGSTOPped server are restored by the trap at exit, also on interrupt.
- Lockout: only from the host, only against this machine's address; the camera's own calls stay possible.
- Every loop is bounded by a count and a timeout.

## Limits

- The camera-side checks were written against the source and the entries; they have not yet run on a camera.
  A first run may show a wrong path or a wrong log text: read `recette.log` before trusting a PASS.
- The Wi-Fi cycles use `ifconfig` / `ip link` and `wpa_cli reassociate` (no Wi-Fi restart script exists in 3.0 under
  `controlscripts/`). Each cycle saves wlan0's address and default gateway first; after the association the DHCP client
  is asked to renew (SIGUSR1 to udhcpc, 5 s); the saved address and route are put back with `ip` only when no udhcpc
  runs for wlan0 (otherwise it is renewed again). A
  cycle passes only with association, address, default route and a gateway that answers. No GPIO, no restart.
  `wpa_cli` and `iw` are looked for in `/mnt/ext/bin` (PATH); without them the Wi-Fi checks are SKIPped.
- The night-mode state is read with `controlscripts/night-mode status` ("PID: OK" means night).
- The stall-exit check starts the server with `RTSP_CAPTURE_STALL_S=5` in the environment only; `rtsp.env` is not
  written. A server that does not exit is stopped and the server restarted the normal way.
- The host's TCP stall check reads `netstat` on the camera and uses the SSH client address as this host's address.
