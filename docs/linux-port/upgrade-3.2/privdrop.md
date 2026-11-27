# Stream `[up-privdrop]`: network daemons without root (plan phase 6, audit SEC-7)

Before this stream every service ran as root: one memory bug in a network parser gave the whole camera. Now the network
daemons that need no root give it up right after they have bound their ports, behind the switch `PRIVDROP` (default 1 on
this branch). The ones whose job needs root keep it, with the reason below. No function is lost.

## 1. Analysis, daemon by daemon

What each daemon binds, opens, writes, executes, signals. "Root needed" means a privilege that a file mode or a group
cannot give.

| Daemon | Ports | Files and devices | Executes, signals, sockets | Root needed? | Decision |
|---|---|---|---|---|---|
| `httpfront` (`src/httpfront`) | TCP 80 (privileged) | reads `user.pwd`, status files | `execve` of BusyBox `httpd`, one per connection, which runs the CGIs: they write `/mnt/config`, call `cfg-persist` (flash settings slots, `flashw`), `reboot`, mount and format the card, start and stop every service, update (`update66.sh`), write the Wi-Fi and the password (`passwd`) | **Yes**, through the CGIs: the child inherits the identity of the parent | **Keep root.** Dropping it would take every settings save, backup restore, update, Wi-Fi and service switch from the web UI. A narrow root helper would mean reworking the 35 CGIs and their callers |
| `tc100-onvifd` (`src/onvifd`) | TCP 8081, UDP 3702 (not privileged) | reads `rtspserver.conf`, `boot.conf`, `rtsp.env`, `timezone.conf`, `user.pwd` (every 2 s), `/mnt/VERSION`, `/sys/class/net/wlan0/address`, `/sys/module/ak39_vi/parameters/main_scale`, `/tmp/rec_control`; writes nothing | no `exec`, no `system`, no signal sent. **It has no setter**: `SetSystemDateAndTime`, `SystemReboot` and the others are answered with a fault (header of `onvifd.c`) | No | **Drop** (C, after both binds) |
| `tc100-mqttd` (`src/mqttd`) | none (client of the broker) | `mqtt.conf` (secret), status, log, FIFO, pid file | `fork` + `execv` of `scripts/mqtt-bridge.sh` helpers and the controlscripts: `reboot`, telnet, FTP, ssh, services on and off (the admin commands, `MQTT_ADMIN_CMDS`), the day/night, privacy and LED switches; `kill(-pid)` | **Yes**: the commands it runs are root jobs | **Keep root.** A command queue read by a root script would be a second path to reboot and to start services from the network. Not simple, not worth the risk |
| `tc100-mdnsd` (`src/mdnsd`) | UDP 5353 (not privileged) | reads `/proc/sys/kernel/hostname`, `/mnt/VERSION`, `/proc/loadavg`, `/tmp/wifi-signal.avg` | `ioctl(SIOCGIFADDR / SIOCGIFNETMASK)` on its socket, multicast join, which any user may do | No | **Drop** (raw system calls, after bind and join) |
| `tc100-whep` (`src/whep`) | TCP 8889 on 127.0.0.1, UDP 8189 (not privileged) | `whep-key.pem`, `whep-cert.pem` in `/mnt/config` (made once, **as root, before the drop**), `user.pwd` at every request | connects to `tc100_rtsp` on 127.0.0.1:554; no `exec`; leaves by itself after 300 s without a viewer | No (the key and the certificate are read before the drop) | **Drop** (C, after the certificate and both sockets) |
| `tc100-logfwd` (`src/logfwd`) | none (sends UDP from a high port) | reads `/var/log/messages` (`syslogd` writes it 644) with inotify; `/etc/resolv.conf` for the host name | none | No | **Drop** (C, before the loop) |
| `tc100_rtsp` (`src/tc100rtsp`) | TCP 554 (privileged) | `/dev/uio0` (encoder, `libakuio`), `/dev/video0`, `/dev/isp_char`, `/dev/snd/pcmC0D0*`, `/sys/module/ak39_vi/parameters/*` (write: `nr3d`), `/mnt/config` (writes `awb.state`, reads everything), recordings in `/mnt/DCIM` and `/mnt/sd`, `/tmp/rec_control`, `/mnt/log` | the recorder, the motion detector and the web pictures (hardware JPEG) are inside it | Yes in practice: device nodes (`uio0`, `video0`, `isp_char`, ALSA) made by devtmpfs at root 600, one sysfs parameter written (`nr3d`) | **Keep root** for now. Giving it the devices through group permissions needs a rule that sets the mode of the nodes before it starts (kernel side or `mdev`), and the recording and `/mnt/config` writes follow; it is the process with the most code. A candidate for a later round, with the camera next to the owner |

What is dropped: the three that have no need of root and expose a network parser the audit named (ONVIF SOAP and
WS-Discovery, the WebRTC STUN, SDP and DTLS, the mDNS packets) plus the log forwarder, which parses lines of the local log.
What stays root and why: `httpfront` (its CGI children), `tc100-mqttd` (its admin commands), `tc100_rtsp` (the encoder and
video devices). The RTSP parser is the one still exposed as root; it is fuzzed (`fuzz.md`) and a later round can take it.

## 2. Mechanism

**The users.** Two, so that a daemon never has a group it does not need: `tc100svc` (uid and gid 1001) for `tc100-onvifd` and `tc100-whep`, which read the camera password and the RTSP settings, and `tc100net` (1002) for `tc100-mdnsd` and `tc100-logfwd`, which read no secret and are in no group of any settings file. Both: no password, no home, shell `/bin/false`. In the base image:
`v3/buildroot/board/tc100/users.table`, referenced by `BR2_ROOTFS_USERS_TABLES` in `v3/buildroot/configs/tc100_defconfig`
(Buildroot writes `/etc/passwd`, `/etc/group`, `/etc/shadow`). The `/etc` in use at run time is the one of the initramfs
(the base `rootfs.cpio.gz`, which `v3/build-rootfs66.sh` packs); the stack (`/mnt`) never carries an `/etc`. So the name
reaches a camera with the next kernel and initramfs write. Nothing depends on the name: the daemons are started with the
numbers (`-D 1001:1001`), so an update of the stack alone on an older initramfs still works, `ps` showing `1001` instead of
`tc100svc`. The numbers are in `scripts/secret-modes.sh` (`TC100_SVC_UID/GID`, `TC100_NET_UID/GID`) and in `users.table`;
`tests/test_privdrop.py` checks that they are the same.

**The drop, in C, inside the daemon.** Option `-D UID:GID`, given by the start script. After the ports are bound and what
only root can read is open or read (the ONVIF settings once, the WHEP certificate and key, both sockets), the daemon calls
`priv_drop()`: `setgroups(0)`, `setgid`, `setuid`, **each checked**, then it verifies `getuid/geteuid/getgid/getegid` and that
`setuid(0)` now fails. Any failure, and a bad specification (`0:0`, a missing number, a number above 65534), makes the
daemon print `cannot drop root (-D ...): stopping` and exit 1: a half-dropped process is never left running. The function is
the same text in `src/onvifd`, `src/whep` and `src/logfwd` (the whep package builds `src/whep` alone, so it cannot share a
header); `src/mdnsd` has the same logic with raw ARM EABI system calls (`setgroups32` 206, `setuid32` 213, `setgid32` 214 and
the four `get*id32`), as the program has no C library. No `strtol` or `sscanf`: the number is parsed by hand.

**What the dropped daemons read after the drop.** `tc100-onvifd` reads the camera password and `rtspserver.conf` again every
2 s (it follows a password change) and `tc100-whep` reads `user.pwd` at every request. Both files are secrets (mode 600
root, `scripts/secret-modes.sh`). With `PRIVDROP=1` they are now **mode 640, group 1001 (tc100svc)**; with `PRIVDROP=0` they are
600 as before. `tc100-mdnsd` and `tc100-logfwd` run as `tc100net` (1002), which has no group on any of them. The other
secrets (`mqtt.conf`, `wpa_supplicant.conf`, `telegram.conf`, `notify.conf`) stay 600: no dropped daemon reads them.

**Every writer sets owner, group and mode before the rename** (`secret_file_attrs TEMP FINAL` in `scripts/secret-modes.sh`), so
the file never exists with attributes the daemons cannot read. A file of the secret list gets the policy above; any other
file keeps the attributes of the one it replaces. Writers that replace the two shared files:
- `rwconf` (`src/rwconf`, the web actions: volume, motion sensitivity, ...): `fchown` of the temporary file to the owner and
  group of the original, checked (a refused change leaves the old file whole and the status non-zero); asked only when they
  differ from the process's own, so a FAT card (no owners) still works;
- `rewrite_config` (`scripts/common_functions.sh`), `tc_commit_config_files` (`scripts/config-transaction.sh`: settings
  import) and `all_password` (the web password change, `user.pwd`): `secret_file_attrs` on the temporary file, then `mv`;
- the boot (`secret_modes_fix`), the restore (`cfg-persist`) and `privdrop_opt` (a service restarted after the switch was
  changed, without a reboot) fix the modes of files that arrived some other way (`cp` of a `.dist`, a tar restore).

**Fail closed.** A read error never means "no password" and never changes the settings:
- `tc100-onvifd` password: only a missing file (ENOENT) or an empty one read without error means open. Any other read error
  keeps the previous state (at start up, closed) and sets a retry flag: the 2 s poll of the loop looks at the file again, a
  request does not (so a file that stays unreadable costs one reload per poll, not one per request). The file signature now
  includes the status-change time, so a `chgrp` or `chmod` that makes the file readable (it changes only the ctime) is seen;
- `tc100-onvifd` `rtspserver.conf`: the last copy read without error is kept; a re-read that fails (not ENOENT) uses it
  instead of the defaults (port 554, user root, 1080p) and is retried at the poll;
- `tc100-whep`: a file that cannot be read, or a read error, keeps the last credentials (only a missing file clears them; a
  missing password only makes the RTSP request unauthenticated, which `tc100_rtsp` refuses).

**Start scripts.** `controlscripts/onvif` and `controlscripts/whep` add `$(privdrop_opt 2>/dev/null)`;
`controlscripts/mdns` and `syslogd_start` (`scripts/common_functions.sh`, which starts `tc100-logfwd`) add
`$(privdrop_opt net 2>/dev/null)`. `privdrop_opt [svc|net]` (in `scripts/secret-modes.sh`, which `common_functions.sh`
sources) prints `-D 1001:1001` or `-D 1002:1002`, or nothing when `PRIVDROP=0`; if the library is missing it is not defined
and the daemon starts as root. Logs and pid files are opened or written by the root shell before the daemon starts
(`>> $LOGPATH`, `/var/run/*.pid`), so no runtime directory needed a new owner. `httpfront`, `tc100-mqttd` and `tc100_rtsp`
are started exactly as before.

## 3. The switch

`PRIVDROP` in `config/boot.conf.dist` (single source, in the file's comment style): `1` (default on this branch) = the four
daemons run as `tc100svc` (onvif, whep) or `tc100net` (mdns, log forwarding); `0` (also `no`, `off`, `false`) = all of them as
root as before. The value may be quoted and followed by a comment (`PRIVDROP=0 # why`, `PRIVDROP='0'`). Read when each daemon starts
(restart the service on the Services page, or reboot); `privdrop_enabled` of `scripts/secret-modes.sh` is the one reader
(`tests/test_privdrop.py` fails if a second reader appears).

## 4. Tests (host)

`tests/test_privdrop.py` (38 tests, including the writers, the group of rwconf and the fail-closed ones; run with the secret-mode, onvifd and rwconf modules: 112 tests as root, OK): the order drop-after-bind in each of the
four sources and the abort on failure; the same function in the three libc programs and the raw-syscall one for mdnsd; the
three that stay root carry none; the switch (default on, off values, last line wins, comments ignored); the modes follow the
switch; the start scripts of `mdns` and `whep` run with a fake daemon and show `-D 1001:1001` or nothing (onvif and the log
forwarder: the line is checked in the source); the image (`users.table` and the defconfig line); and real processes built
with the host compiler: `tc100-onvifd` and `tc100-logfwd` stop on a bad specification and on a failing setuid (an ordinary
user), and as root (or `sudo -n`) really run as 65000:65001 with no supplementary group, still answer (ONVIF call, log line
forwarded by UDP), keep the UDP socket bound before the drop, refuse the credential-less call when the password file is
unreadable (also after the 2 s reload) and follow a password change through the 640 group file. `tests/docker/local-ci.sh
tests` runs this module once as root and the whole suite as an ordinary user. `tests/test_secret_modes.py` now sets
`PRIVDROP=0` for its 600 rules. The fuzz harnesses compile the daemons' sources (`onvifd.c`, `httpfront.c`): `local-ci.sh
fuzz` stays green.

## 5. Camera test (owner, from the SD card in RAM, nothing written to the flash)

The kernel and initramfs of this branch's CI run boot from the SD card (`pack66/boot66b.sh`). The new initramfs carries the
user `tc100svc`; with an older one the same test works and `ps` shows 1001.

1. `ps -o user,pid,comm` (or `ps | grep`): `tc100-onvifd` (if ONVIF is on), `tc100-mdnsd`, `tc100-logfwd` (if syslog
   forwarding is configured) and, after the first live view, `tc100-whep` run as `tc100svc` (or 1001), `tc100-mdnsd` and `tc100-logfwd` as `tc100net` (or 1002); `httpfront`,
   `httpd` children, `tc100-mqttd` (if on), `tc100_rtsp` as root. `ls -ln /mnt/config/user.pwd /mnt/config/rtspserver.conf`:
   `-rw-r----- 1 0 1001`; set a volume and a motion sensitivity on the web page, and check that `rtspserver.conf` is still `0 1001` 640 and that the ONVIF stream URIs are unchanged (no restart of onvif).
2. Web UI: log in, save a setting on several pages, make a settings backup and restore it, change the password (then check
   ONVIF and the live view with the new one, no restart), a reboot from the page.
3. Live view with WebRTC (the page's default), then RTSP in Frigate / VLC.
4. ONVIF (service on): discovery from an ONVIF client or ODM, profiles and stream, snapshot, events on motion; an
   unauthenticated `GetProfiles` is refused. `SetSystemDateAndTime` and `SystemReboot` were never supported (fault).
5. MQTT (service on): state topics, a command, the admin commands if `MQTT_ADMIN_CMDS` is on (still root).
6. mDNS: `ping <name>.local`, the DNS-SD listing if `MDNS_SERVICES=1`.
7. Syslog forwarding (if configured): a line arrives at the server after `logger -p user.err test`.
8. `PRIVDROP=0` in `/mnt/config/boot.conf`, restart onvif, mdns, whep (or reboot): all of them back as root, and
   `user.pwd` back to 600; `PRIVDROP=1` again: the user returns. Any daemon that cannot drop stops and logs
   `cannot drop root`: that line, and what `ps` shows, is the report to send.

## 6. Open points

- `tc100_rtsp` (the largest parser still running as root) and `httpfront`: see section 1; the next step for the first is
  group permissions on the device nodes (a rule in `S39tc100-linux66` or the kernel), tested with the camera near.
- The name `tc100svc` reaches a camera with the next write of the initramfs; the numbers work without it.
- `FAT` card config folders (`/mnt/sd/config`) have no modes: the dropped daemons read them through the mount options.
- `dropbear`, `telnetd`, `ftpd` and `ntpd` are BusyBox / third-party daemons outside this stream.
