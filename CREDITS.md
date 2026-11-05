# Credits and licences of what this project builds on

This firmware is built on the work of others. Where code is derived, its copyright
headers are kept in the source files. This list names the projects; each one's own
licence applies to its code. The code of this project itself is under the GPL-2.0
([LICENSE](LICENSE)).

| Project | What we use | Where |
|---|---|---|
| [Linux kernel](https://kernel.org) (GPL-2.0) | 6.6 base for the port | `patches/kernel-6.6/` |
| [OpenIPC](https://openipc.org), `OpenIPC/linux` (GPL-2.0, vendor-derived) | the ISP, camera, USB host and MMC drivers of the 6.6 port derive from its Anyka 4.4 tree, which derives from the vendor's GPL sources; `ipctool` identified the board; the old OpenIPC SD boot kit (`contrib/openipc_sd_kit/`) was removed from the tree and is in the git history | `patches/kernel-6.6/series/` |
| [Thingino](https://github.com/themactep/thingino-firmware) | early inspiration for the board-port layout; the `thingino_port/` folder and its prebuilt `thingino-rtsp-server` were removed on 2026-10-27 (f3d846d) and nothing of Thingino is shipped | history only |
| [Buildroot](https://buildroot.org) (GPL-2.0) and the [Bootlin](https://toolchains.bootlin.com) toolchains | our base root filesystem (BusyBox, dropbear, wpa_supplicant, curl, jq, alsa-utils, musl) | `v3/buildroot/` |
| Anyka (vendor GPL kernel sources) | origin of the platform code in the OpenIPC tree | via OpenIPC |
| [ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks), `anyka-v4l2rtspserver`, `anyka-software` | the original SD-card hack and the RTSP server of the 2.x firmware | see the README, "Where it comes from" |

No vendor binary is published in this repository. The vendor media libraries are read from the camera itself.

Prebuilt ARM programs kept in the repository and copied into the 3.0 image by `v3/build-stack.sh` (uClibc, from the
2.x era): `bin/getflag`, `bin/getimage`, `bin/isp_flip`, `bin/monvifd` (ONVIF), `bin/rwconf`, `bin/tc100-logfwd`, `lib/libnetacl.so`.
`tc100-logfwd`, `isp_flip` and `libnetacl` have their source in `src/`. The other four came with the first commit of
this repository (`99c3112`, 2026-02-02), a copy of the original SD-card hack, whose `bin/` holds the same files
(identified 2026-11-04):

| Program | Source | Licence |
|---|---|---|
| `rwconf` | [anyka-v4l2rtspserver](https://github.com/ThatUsernameAlreadyExist/anyka-v4l2rtspserver), `libv4l2cpp/src/ReadWriteConfig.cpp` + `ConfigFile.cpp`, built by `tools.sh` of [anyka-software](https://github.com/ThatUsernameAlreadyExist/anyka-software) (`-DBUILD_RWCONFIG=1`) | Unlicense (public domain) |
| `getflag` | same tree, `GetFlag.cpp` + `SharedMemory.cpp` (`-DBUILD_GETFLAG=1`) | Unlicense (public domain) |
| `getimage` | same tree, `GetImage.cpp` + `SharedMemory.cpp` (`-DBUILD_GETIMAGE=1`) | Unlicense (public domain) |
| `monvifd` | "Micro ONVIF discovery service v1.1" by ThatUsernameAlreadyExist, first published as a binary in [JCO-PM203-Fisheye-Ingenic-T20-P2P-camera-hacks](https://github.com/ThatUsernameAlreadyExist/JCO-PM203-Fisheye-Ingenic-T20-P2P-camera-hacks) (2023-05-15), then in the TC100 hack (2023-07-09). **No source published**; neither repository has a licence. | none stated |

`bin/setconf` and `bin/telegram` are shell scripts of this repository (2.x's `setconf` was built from
`SetSharedConfig.cpp`, same tree). The three Unlicense programs can be rebuilt from their public source; `monvifd`
stays the default ONVIF daemon until the free replacement `tc100-onvifd` (`src/onvifd`, written for this project, GPL-2.0:
WS-Discovery, Device, Media and Media2 services) is tested on the camera (`ONVIF_IMPL=c` in `onvif.conf`; ONVIF is off by default).
