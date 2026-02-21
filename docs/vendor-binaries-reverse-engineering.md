# Vendor Binaries Reverse-Engineering Notes

This document captures practical reverse-engineering results for closed vendor binaries used by this project.

Scope:
- `bin/setconf`
- `bin/v4l2rtspserver`
- `bin/monvifd`

Method:
- Static inspection with `objdump`, `nm`, `strings`.
- Cross-check against project runtime wrappers in `controlscripts/*` and `www/cgi-bin/*`.
- No full decompilation in this pass.

Limitations:
- ARM binaries cannot be executed on this host directly (no `qemu-arm` in environment), so runtime probing of CLI error paths was not performed here.

## Binary Overview

| Binary | Arch | Strip State | Notes |
|---|---|---|---|
| `bin/setconf` | ELF32 ARM | stripped | Small IPC/config control tool with clear key help strings. |
| `bin/v4l2rtspserver` | ELF32 ARM | not stripped, has debug info | Main media daemon; rich symbols and option/help strings present. |
| `bin/monvifd` | ELF32 ARM | stripped | ONVIF discovery/device/media responder; SOAP templates embedded. |

## `setconf` key map (confirmed)

Source of truth: embedded usage/help strings in `bin/setconf` and usage in `config/autostart/00_system-config`.

CLI behavior:
- `Usage %s -g -k KEY -v VALUE`
- `g` and `k` cannot be used together.
- Option parser string: `g:k:v:`

### Confirmed keys

| Key | Meaning |
|---|---|
| `q` | Config file path |
| `n` | Night mode (`1` on, `0` off, `2` auto, `3` disable/manual config) |
| `v` | Video day mode on/off |
| `f` | Flip image |
| `r` | Day-to-night AWB threshold |
| `a` | Day-to-night luminance threshold |
| `b` | Night-to-day AWB threshold |
| `d` | Night-to-day luminance threshold |
| `e` | IR cut on/off |
| `g` | IR LED on/off |
| `o` | OSD text |
| `c` | OSD front color |
| `s` | OSD high font size |
| `x` | OSD high X position |
| `y` | OSD high Y position |
| `z` | OSD low font size |
| `w` | OSD low X position |
| `t` | OSD low Y position |
| `h` | OSD alpha |
| `i` | OSD back color |
| `j` | OSD edge color |
| `l` | OSD on/off |
| `m` | Motion detect sensitivity |
| `p` | Motion detect on/off |

## `v4l2rtspserver` findings

### High-confidence CLI options (confirmed from embedded help + optstring)

Embedded optstring:

`v::Q:O:b:I:P:p:m::u:M::ct:S::x:R:U:rwBsf::F:W:H:G:A:C:a:Vh`

Help text confirms:
- Verbosity and queueing: `-v`, `-vv`, `-Q`
- Output/webroot: `-O`, `-b`
- RTSP/RTP: `-I`, `-P`, `-p`, `-u`, `-m`, `-M`, `-U`, `-R`, `-t`, `-c`
- Streaming extras: `-S[duration]` (HLS + MPEG-DASH), `-x <sslkeycert>` (RTSPS + SRTP)
- V4L2 capture: `-r`, `-w`, `-B`, `-s`, `-f[format]`, `-W`, `-H`, `-F`, `-G`
- ALSA capture: `-A`, `-C`, `-a`
- Utility flags exist in optstring: `-V`, `-h`

### Built-in capabilities (confirmed from symbols/strings)

- Codecs and payloads exposed in strings/symbols:
  - Video: `H264`, `H265`, `JPEG`, `VP8`, `VP9`, raw modes.
  - Audio: `AAC`, `PCMA`, `PCMU` and PCM formats.
- Built-in HTTP handlers include:
  - `getVersion`
  - `getSnapshot`
  - `getStreamList`
  - HLS playlist (`.m3u8`)
  - MPEG-DASH MPD (`.mpd`)
- Network/session stack:
  - RTSP over HTTP tunneling
  - Optional TLS/SRTP path (`setTLSState`, `-x`)
- Stream labels include at least:
  - `video0`
  - `video1`
- Detected config keys parsed by daemon include:
  - Stream/video/audio: `PORT`, `width`, `height`, `codec`, `profile`, `brmode`, `goplen`, `samplerate`, `volume`
  - OSD/motion/daynight: `osd*`, `mdenabled`, `mdsens`, `daynight*`, `nightday*`, `irled`, `ircut`, `videoday`
  - Rate control: `smartmode`, `smartquality`, `smartstatic`, `maxkbps`, `targetkbps`
  - Other: `jpegstream`, `imageflip`
- Uses Anyka media/ISP functions directly (from dynamic relocations), including:
  - VI/VENC control
  - OSD rendering
  - Motion detection controls
  - ISP stats access

### HTTP route surface (confirmed static pass)

- Built-in commands:
  - `getVersion`
  - `getSnapshot`
  - `getStreamList`
- Playlist/segment serving:
  - HLS playlist (`.m3u8`)
  - MPEG-DASH MPD (`.mpd`)
  - Segment query form: `?segment=<n>` (`video/mp2t`)
- Static web root support:
  - Default file: `index.html`
  - MIME hints present for `html`, `javascript`, DASH (`application/dash+xml`), HLS (`application/vnd.apple.mpegurl`)

Inference:
- The HTTP side is primarily a lightweight stream/playlist helper plus a tiny diagnostics API, not a large control API.

## `monvifd` findings

### Confirmed from embedded strings

- Banner:
  - `Micro ONVIF discovery service v1.1`
  - `Provides: network discovery, RTSP streaming description (IPv4)`
- ONVIF SOAP templates include responses for:
  - `GetCapabilities`
  - `GetProfiles`
  - `GetStreamUri`
  - `GetDeviceInformation`
  - `GetNetworkInterfaces`
  - `GetSystemDateAndTime`
  - Discovery `ProbeMatches`
- Endpoint path is present:
  - `/onvif/device_service`
- Fault template exists for unknown/unimplemented methods.

### Template placeholders (confirmed)

`monvifd` uses token placeholders inside SOAP templates that are replaced at runtime. Observed tokens:

- Device/network identity:
  - `XX=mpx1=XX`, `XX=mpx2=XX` (port/IP in XAddr templates)
  - `XX=mji1=XX`, `XX=mji2=XX`, `XX=mji3=XX`, `XX=mji4=XX` (hardware/vendor/location/model-ish fields)
- Stream URI/profile:
  - `XX=xur1=XX`, `XX=xur2=XX`
  - `XX=mwh1=XX`, `XX=mwh2=XX`, `XX=mwh3=XX`
- Discovery fields:
  - `XX=prb1=XX`, `XX=prb2=XX`, `XX=prb3=XX`, `XX=prb4=XX`
- Date/time fields:
  - `XX=gtd1=XX` ... `XX=gtd14=XX`
- Fault/method field:
  - `XX=mtd1=XX`

### CLI arguments (deeper recovery, high confidence)

The parser strings are encoded as UTF-32LE blocks (not plain ASCII optstrings).  
Recovered from `bin/monvifd` at vaddr range around `0x3b0a0` (file offset `0x330a0`).

Recovered option/help labels:

- Core ports:
  - `-p` ONVIF listen port
  - `-w` standalone web port
  - `-wp` web protocol (`http`/`https`)
  - `-r` standalone RTSP port
- Identity metadata:
  - `-hwn` hardware name
  - `-vnn` vendor name
  - `-loc` location
  - `-dn` device name
  - `-mod` model
- Stream profile 1:
  - `-rp1`, `-vw1`, `-vh1`, `-vc1`, `-vcb1`, `-fps1`
- Stream profile 2:
  - `-en2`, `-rp2`, `-vw2`, `-vh2`, `-vc2`, `-vcb2`, `-fps2`
- Combined size variants:
  - `-vwh1`, `-vwh2` (width-height form)
- Help:
  - `-h`, `--help`

Semantic labels in same block confirm intent:
- `show help`
- `enable rtsp stream 2 (1/0)`
- `rtsp stream N path/width/height/codec/bitrate/fps`
- `rtsp stream 1 width-height` with example `-W1600 -H900`

Confidence on CLI map: high for both compatibility and completeness of primary runtime options.

## Practical conclusions

- `setconf` is now sufficiently mapped for all currently used image/OSD/motion controls.
- `v4l2rtspserver` is highly reversible and exposes many latent capabilities (TLS, HLS, DASH, HTTP helpers, codec paths).
- `monvifd` protocol behavior and option surface are now mapped well enough to safely expose more metadata fields in project config/scripts.

### H264/H265 server separation feasibility

- `v4l2rtspserver` currently owns:
  - capture (`ak_vi_*`)
  - encoder/session control (`ak_venc_*`)
  - OSD (`ak_osd_*`)
  - motion detection (`ak_md_*`)
- Because these subsystems are tightly integrated in one process path, splitting H264/H265 into separate daemons is not a low-risk shell-level change.

Practical CPU-saving strategy instead:
- keep one daemon, but reduce active workload:
  - disable substream (`RTSP_SUBSTREAM=0`) when not needed
  - disable audio (`RTSP_AUDIO=0`) if not required
  - use ONVIF stream policy `main-only` or `sub-only`
  - lower FPS/bitrate via existing RTSP config/profile controls

## Recommended next RE steps

1. On-device dynamic probing:
   - Launch `monvifd` with bad/missing args and capture stderr/help output.
   - Capture `/proc/<pid>/cmdline` and runtime socket bindings.
2. Deep static pass:
   - Import `monvifd` into Ghidra/IDA and confirm semantics of `-vwh1/-vwh2`.
3. Feature extraction:
   - Determine exact URL path patterns used for `.m3u8`/`.mpd`/`?segment=` per stream name.
