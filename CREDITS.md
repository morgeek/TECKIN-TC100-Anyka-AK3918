# Credits and licences of what this project builds on

This firmware is built on the work of others. Where code is derived, its copyright
headers are kept in the source files. This list names the projects; each one's own
licence applies to its code.

| Project | What we use | Where |
|---|---|---|
| [Linux kernel](https://kernel.org) (GPL-2.0) | 6.6 base for the port | `patches/kernel-6.6/` |
| [OpenIPC](https://openipc.org), `OpenIPC/linux` (GPL-2.0, vendor-derived) | the ISP, camera, USB host and MMC drivers of the 6.6 port derive from its Anyka 4.4 tree, which derives from the vendor's GPL sources; `ipctool` identified the board; the old OpenIPC SD boot kit is kept in `contrib/openipc_sd_kit/` (not used by the build) | `patches/kernel-6.6/series/`, `contrib/openipc_sd_kit/` |
| [Thingino](https://github.com/themactep/thingino-firmware) | the board-port layout (`thingino_port/`) and the prebuilt `thingino-rtsp-server` used by the 6.6 user space; see upstream for its licence | `thingino_port/` |
| [Buildroot](https://buildroot.org) (GPL-2.0) and the [Bootlin](https://toolchains.bootlin.com) toolchains | our base root filesystem (BusyBox, dropbear, wpa_supplicant, curl, jq, alsa-utils, musl) | `v3/buildroot/` |
| Anyka (vendor GPL kernel sources) | origin of the platform code in the OpenIPC tree | via OpenIPC |
| [ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks), `anyka-v4l2rtspserver`, `anyka-software` | the original SD-card hack and the RTSP server of the 2.x firmware | see the README, "Where it comes from" |

No vendor binary is published in this repository. The vendor media libraries are read from the camera itself.
