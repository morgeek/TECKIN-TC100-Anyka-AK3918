# Hardware acceleration: what the AK3918EV300 does, what 3.0 uses (2026-10-29)

Measured on IPCAM2 (3.0.1-rc1, flash mode): the CPU is busy 84 to 100 %, `tc100_rtsp` alone about 76 %. The
hardware encoders are used; the CPU time goes into per-frame passes over the 3 MB picture that the ISP could do,
on a capture memory that the CPU reads uncached.

## The blocks and their use

| Block | Use in 3.0 | CPU work it could remove |
|---|---|---|
| Video encoder (H.264 / H.265) | yes: vendor libraries on the free `libakuio` | - |
| JPEG engine | yes: snapshots, stream.jpg, thumbnails (`jpeg_hw`) | - |
| ISP: demosaic, AE, AWB, noise filters, gamma, CCM | yes, from the camera's own tuning file (`isp.conf`) | - |
| ISP contrast / saturation / hue / Y gamma (`AK_ISP_SET_CONTRAST`, `_SAT`, `_HUE`, `_Y_GAMMA` on `/dev/isp_char`) | **no**: done by a table on every byte (`post_copy`) when Live image tuning is on | a 3 MB pass per frame |
| ISP white balance | yes, but `tc100_rtsp` adds a **software grey-world white balance** (on by default, `config/awb.off` turns it off) because of a colour cast: a chroma table on 1.5 MB per frame | a 1.5 MB pass per frame; the cast itself comes from the tuning file missing at start (dmesg: `Direct firmware load for anyka/isp.conf failed`) |
| ISP privacy masks (`AK_ISP_SET_MAIN_CHAN_MASK_AREA`, `_SUB_CHAN_MASK_AREA`, `_MASK_COLOR`) | **no**: painted by the CPU | small (only the masked areas) |
| ISP black and white (`AK_ISP_SET_YUV_EFFECT` or saturation 0) | **no**: `memset` of the chroma | 1 MB write per frame in B/W |
| ISP flip / mirror (`AK_ISP_SET_FLIP_MIRROR`) | **now**: `bin/isp_flip` (was missing, Settings orientation did nothing) | - |
| ISP sub channel (hardware scaler, 640x360 second output) | **no**: `sub_scale` samples the 1080p picture on the CPU; `ak39_vi.sub_channel=1` crashed the kernel on 2026-10-23 (variant B) and must be fixed first | 345 600 scattered reads per frame |
| ISP 3D noise reduction | **no**: its reference buffers (2 x 3 MB) do not fit the CMA area, it is forced off | quality and bit rate, not CPU |
| ISP statistics (Y histogram, AE info) | **no**: the light level is a CPU sample of the picture | small |
| Capture DMA into cached memory (kernel patch 0012, `RTSP_CACHED=1`) | **new, to test** | every CPU read above becomes a cache-line fill instead of a bus access |
| Capture straight into the encoder pool (kernel patch 0011, `RTSP_ZEROCOPY=1`) | **new, to test** | the 3 MB copy itself |

## Order of work (quality kept, each step measured with `v3/dev/try-rtsp.sh`)

1. Load the tuning file before the first video start (no colour cast), then the software white balance can stay
   off (`config/awb.off`) with the same picture: removes the 1.5 MB chroma pass. Until then, `post_copy` now
   reads and writes 4 bytes at a time and skips identity tables (fewer bus accesses for the same result).
2. `RTSP_CACHED=1` (kernel with 0012): the copy and the sub picture read cached memory.
3. `RTSP_ZEROCOPY=1` (kernel with 0011): no copy at all; compare with 2.
4. Live image tuning, masks and black and white through `/dev/isp_char` instead of the CPU.
5. The ISP sub channel (hardware 640x360), once the variant B crash is understood.
