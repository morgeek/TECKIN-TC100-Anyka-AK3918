# Credits and licences of what this project builds on

This firmware is built on the work of others. Where code is derived, its copyright
headers are kept in the source files. This list names the projects; each one's own
licence applies to its code. The code of this project itself is under the GPL-2.0
([LICENSE](LICENSE)).

| Project | What we use | Where |
|---|---|---|
| [Linux kernel](https://kernel.org) (GPL-2.0) | 6.6 base for the port | `patches/kernel-6.6/` |
| [OpenIPC](https://openipc.org), `OpenIPC/linux` (GPL-2.0, vendor-derived) | the ISP, camera, USB host and MMC drivers of the 6.6 port derive from its Anyka 4.4 tree, which derives from the vendor's GPL sources; `ipctool` identified the board; the old OpenIPC SD boot kit (`contrib/openipc_sd_kit/`) was removed from the tree and is in the git history | `patches/kernel-6.6/series/` |
| [Thingino](https://github.com/themactep/thingino-firmware) | early inspiration for the board-port layout; the `thingino_port/` folder and its prebuilt `thingino-rtsp-server` were removed on 2026-10-27 (49a2485) and nothing of Thingino is shipped | history only |
| [Buildroot](https://buildroot.org) (GPL-2.0) and the [Bootlin](https://toolchains.bootlin.com) toolchains | our base root filesystem (BusyBox, dropbear, wpa_supplicant, curl, jq, alsa-utils, musl) | `v3/buildroot/` |
| [Pico CSS](https://picocss.com) 2.0.6 (MIT) | the look of the web interface (licence header kept), drawn on the pages' markup by `www/css/pico-shim.css` (Bulma was removed in rc32) | `www/css/pico-2.0.6.min.css` |
| Anyka (vendor GPL kernel sources) | origin of the platform code in the OpenIPC tree | via OpenIPC |
| [ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks](https://github.com/ThatUsernameAlreadyExist/TECKIN-TC100-Anyka-AK3918-camera-hacks), `anyka-v4l2rtspserver`, `anyka-software` | the original SD-card hack and the RTSP server of the 2.x firmware | see the README, "Where it comes from" |

No vendor binary is published in this repository. Since 3.0.1-rc34 (`src/h265enc/freeenc.h` and `src/libakuio`), the
firmware runs on 100% free software and does not load, link or copy any vendor `.so` library from the camera; only the
camera's own sensor calibration table (`isp.conf`, 69.5 KB) is read by the kernel ISP driver from `/vendor/isp.conf`.

Prebuilt ARM programs kept in the repository and copied into the 3.0 image by `v3/build-stack.sh` (uClibc, from the
2.x era): none any more: `bin/monvifd` (the closed ONVIF daemon) was removed in rc32, the free `tc100-onvifd` replaces it.
`bin/isp_flip` (freestanding, no C library), `bin/tc100-logfwd` (`src/logfwd`) and `lib/libnetacl-musl.so`
(`src/netacl`) are rebuilt from their source by the release build; the copies in `bin/` and `lib/` only serve local builds.
Since 3.0.1-rc33/rc34, `tc100_rtsp`, `tc100-mqttd`, `tc100-onvifd`, `tc100-supervisord`, `tc100-logfwd`, `rwconf`, and
`libnetacl-musl.so` are all compiled against the system `musl` C library (`src/musl.mk`), while `httpfront` and `tc100-mdnsd`
are freestanding static binaries. `bin/rwconf` is no longer
versioned (2026-11-05, item 53): `src/rwconf/rwconf.c` is a free C rewrite of the 2.x program (same behaviour, checked
against the original source in `tests/rwconf-original/`, Unlicense) and the release build compiles it into `bin/rwconf`
before `v3/build-stack.sh`. `bin/getflag` and `bin/getimage` were removed: they read the shared memory of the 2.x RTSP
server, which `tc100_rtsp` does not have; no 3.0 script calls them any more. `bin/busybox` is the uClibc BusyBox of the original hack
([BusyBox](https://busybox.net), GPL-2.0, 1.1 MB): only on the SD card, for the stock firmware's SD hook; the 3.0 image
links `/mnt/bin/busybox` to the system BusyBox instead. The other four came with the first commit of
this repository (`99c3112`, 2026-02-02), a copy of the original SD-card hack, whose `bin/` holds the same files
(identified 2026-11-04; the first three are gone from the repository since 2026-11-05, the table keeps their origin):

| Program | Source | Licence |
|---|---|---|
| `rwconf` | [anyka-v4l2rtspserver](https://github.com/ThatUsernameAlreadyExist/anyka-v4l2rtspserver), `libv4l2cpp/src/ReadWriteConfig.cpp` + `ConfigFile.cpp`, built by `tools.sh` of [anyka-software](https://github.com/ThatUsernameAlreadyExist/anyka-software) (`-DBUILD_RWCONFIG=1`) | Unlicense (public domain) |
| `getflag` | same tree, `GetFlag.cpp` + `SharedMemory.cpp` (`-DBUILD_GETFLAG=1`) | Unlicense (public domain) |
| `getimage` | same tree, `GetImage.cpp` + `SharedMemory.cpp` (`-DBUILD_GETIMAGE=1`) | Unlicense (public domain) |
| `monvifd` | "Micro ONVIF discovery service v1.1" by ThatUsernameAlreadyExist, first published as a binary in [JCO-PM203-Fisheye-Ingenic-T20-P2P-camera-hacks](https://github.com/ThatUsernameAlreadyExist/JCO-PM203-Fisheye-Ingenic-T20-P2P-camera-hacks) (2023-05-15), then in the TC100 hack (2023-07-09). **No source published**; neither repository has a licence. | none stated |

`bin/setconf` and `bin/telegram` are shell scripts of this repository (2.x's `setconf` was built from
`SetSharedConfig.cpp`, same tree). The three Unlicense programs can be rebuilt from their public source. `monvifd` was
the ONVIF daemon of 2.x; it was removed from the repository in rc32 (owner, 2026-11-06): the free `tc100-onvifd`
(`src/onvifd`, written for this project, GPL-2.0: WS-Discovery, Device, Media and Media2 services, events) replaces it,
checked on both cameras in rc31.

AAC encoder of the recorder (`src/tc100rtsp/aacenc.c`, `RTSP_REC_AAC=1`): written for this project (GPL-2.0), from the ISO/IEC 14496-3
format description. The only third-party data are the Huffman code tables of the standard in `aacenc_tab.h`, bare numbers read from
FFmpeg `libavcodec/aactab.c` by `aacenc_tab_gen.py` ([FFmpeg](https://ffmpeg.org), (c) 2005-2007 Oded Shimon and Maxim Gavrilov, LGPL-2.1-or-later,
redistributable under the GPL version 2 of this project).
