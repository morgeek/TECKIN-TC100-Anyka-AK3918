# Security policy

This is a free, non-commercial hobby firmware for the TECKIN TC100 camera. Security reports are welcome and handled
on a best-effort basis.

## Supported versions

| Version | Security fixes |
|---|---|
| Latest 3.0.x release | yes |
| `main` (release candidates) | yes, fixed in the next release candidate |
| 2.x (branch `2.x`, vendor kernel 3.4) | no |
| The camera's original (stock) firmware | out of scope |

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability.

Use GitHub's private reporting: the **Security** tab of this repository, then **Report a vulnerability**. Include the
firmware version (shown in the web interface, or `cat /mnt/VERSION` over ssh), the affected service (web, RTSP, ONVIF, MQTT, WebRTC, ssh...),
the steps to reproduce, and what an attacker gains.

Never include your camera's password, Wi-Fi key, MQTT or Telegram credentials, or a copy of the flash
(`flash-stock.bin`) in a report.

What to expect, best effort:
- an acknowledgement within 7 days;
- a first assessment within 30 days;
- a fix in a release candidate on `main`, then in the next release, credited to you unless you prefer otherwise;
- a coordinated disclosure date agreed with you, normally once the fixed release is out.

## Scope and security model

The firmware is designed for a **trusted local network**. By default only private network addresses may connect
(`NET_LAN_ONLY=1`), the camera has no cloud connection and no telemetry, and services such as ONVIF, FTP and telnet
are off.

In scope: everything built from this repository (kernel patches, initramfs, user space, web interface, the free
programs in `src/`, the install and update scripts).

Known limits, documented and not treated as new vulnerabilities on their own:
- the web interface uses plain HTTP and RTSP uses Digest authentication: never forward the camera's ports from the
  internet; for HTTPS use a reverse proxy;
- the default password is public until you change it (the setup wizard asks for a new one);
- the bootloader (U-Boot) is never modified, so there is no verified boot;
- update packages are checked for integrity (MD5), not yet signed.

The current assessment and the planned improvements are in
[docs/linux-port/audit-2026-11-27-security.md](docs/linux-port/audit-2026-11-27-security.md).
