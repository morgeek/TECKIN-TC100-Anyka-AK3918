# Credits and licences of what this project builds on

This firmware is built on the work of others. Where code is derived, its copyright
headers are kept in the source files. This list names the projects; each one's own
licence applies to its code.

| Project | What we use | Where |
|---|---|---|
| [Linux kernel](https://kernel.org) (GPL-2.0) | 6.6 base for the port | `patches/kernel-6.6/` |
| [OpenIPC](https://openipc.org), `OpenIPC/linux` (GPL-2.0, vendor-derived) | the ISP, camera, USB host and MMC drivers of the 6.6 port derive from its Anyka 4.4 tree, which derives from the vendor's GPL sources; `ipctool` identified the board; the old OpenIPC SD boot kit is kept in `contrib/openipc_sd_kit/` (not used by the build) | `patches/kernel-6.6/series/`, `contrib/openipc_sd_kit/` |
| [Thingino](https://github.com/themactep/thingino-firmware) | early inspiration for the board-port layout; the `thingino_port/` folder and its prebuilt `thingino-rtsp-server` were removed on 2026-10-27 (f3d846d) and nothing of Thingino is shipped | history only |
| [Buildroot](https://buildroot.org) (GPL-2.0) and the [Bootlin](https://toolchains.bootlin.com) toolchains | our base root filesystem (BusyBox, dropbear, wpa_supplicant, curl, jq, alsa-utils, musl) | `v3/buildroot/` |
| Anyka (vendor GPL kernel sources) | origin of the platform code in the OpenIPC tree | via OpenIPC |
| [ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks), `anyka-v4l2rtspserver`, `anyka-software` | the original SD-card hack and the RTSP server of the 2.x firmware | see the README, "Where it comes from" |

No vendor binary is published in this repository. The vendor media libraries are read from the camera itself.

Prebuilt ARM programs kept in the repository and copied into the 3.0 image by `v3/build-stack.sh` (uClibc, from the
2.x era): `bin/getflag`, `bin/getimage`, `bin/isp_flip`, `bin/monvifd` (ONVIF), `bin/rwconf`, `bin/tc100-logfwd`, `lib/libnetacl.so`.
`tc100-logfwd`, `isp_flip` and `libnetacl` have their source in `src/`; for `monvifd`, `rwconf`, `getflag` and `getimage` the
origin is the original SD-card hack (row above) and their source and licence still have to be written down here, or
the programs rebuilt from source (audit of 2026-11-03, `docs/linux-port/audit-2026-11-03.md`, C2).
