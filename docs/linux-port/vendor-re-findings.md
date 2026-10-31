# What the stock firmware does: findings from its binaries (2026-10-31)

The owner asked to read the original binaries instead of guessing vendor structures. Sources: the full 8 MiB SPI
dump of the stock firmware (2026-02-21, git history `bootloader.bin`, commit 1302d89; kernel "Linux-3.4.35" uImage at
0x39000, root squashfs at 0x23B000, application squashfs at 0x438000, JFFS2 settings at 0x3BB000), and the
`libmpi_venc_ex.so` of the 2.x firmware (`libmpi_venc V1.0.07`, the library `tc100_rtsp` loads). Analysis with Ghidra
11.4 headless and the stock `factory_cfg.ini`. **No vendor file or decompiled code is in this repository**: only the
facts below (call shapes, values, the logic in words). The binaries stay on the owner's PC, outside git.

## Encoder smart mode (R9-04 -> R11-01)
- `ak_venc_set_smart_config(void *handle, int cfg[4])`, `cfg = {mode, gop_len, quality, static_value}`. The library
  logs `setting smart mode=%d, gop=%d, q=%d, v=%d`, reads the encoder's parameter block, stores the four values as
  16-bit fields and writes the block back (under the encoder mutex). Returns 0, or -1 for a null handle or config.
- `factory_cfg.ini`: "on vbr model: 0 is normal vbr, 1 is LTR, 2 is variable-gop"; stock values `smart_mode = 0`,
  `smart_goplen = 300`, `smart_quality_264/265 = 100` ("[1,100]"), `smart_static_value = 550`,
  `smart_target_ratio = 90`. Smart mode only means something in VBR.
- The stock firmware itself streamed **VBR** (`main_video_mode = 1`), H.265 (`main_enc_type = 2`), GOP 2 s,
  VBR target 90 % of the maximum bit rate. `tc100_rtsp` streams CBR unless `RTSP_VBR=1`.
- `tc100_rtsp` (rc11): `RTSP_SMART=1|2` calls it after every encoder open, with the stock values
  (`RTSP_SMART_GOP`, `_Q`, `_V` override them), only when `RTSP_VBR=1`.

## Anti-flicker (R9-03): our method is the vendor's
- `libplat_vi.so` `isp_set_force_anti_flicker_flag`: reads the AE attributes, computes
  `exp_step = exp_time_max * sensor_fps / (2 * mains_hz)` (12-13 fps: 125 / 1000 or 1200), writes it to `exp_step`,
  and in "forced" mode also sets `exp_time_min` to that step (no exposure shorter than one lamp pulse, even outdoors);
  unforced, `exp_time_min` keeps its saved value.
- `tc100_rtsp` computes the same step with `exp_time_max * fps` = 1125 x 25 = 28125 lines a second, unforced. The
  IPCAM2 tuning file already holds 281 lines, so "Camera default" is 50 Hz. The stock `factory_cfg.ini` says
  `power_frequency = 60`, which the app overrode with the user's setting.

## Day / night (R9-02, R11-02)
`libplat_vpss.so` `ak_vpss_isp_get_auto_day_night_level` (stock `[autoir]` values in brackets):
- **The light metric:** `lum = lum_factor * 40 / avg_lumi`, where `lum_factor` is the exposure time times the
  analogue, digital and ISP gains (each in 1/256, as our exposure index) divided by a normalising value of the ISP
  context, and `avg_lumi` is the AE run info's current mean luminance (40 if zero). Dividing by the picture's own
  brightness is what separates a dim day room from the night when the exposure is at its limit: IPCAM2 shows
  index 30031 in both, but `lumi` 50 by day and 9-10 at night with the IR LEDs (5 without), so `index * 40 / lumi` is
  about 24000 against 120000-240000.
- First it waits for a steady reading: three samples 500 ms apart that agree (above, below or between the thresholds).
- **Day -> night:** `lum > day_to_night_lum` [3584] **and** the white balance does not see daylight: none of the 10
  `total_cnt[]` of `AK_ISP_AWB_STAT_INFO` (averaged over two reads) above `day_cnt0..9` [300000].
- **Night -> day:** `lum < night_to_day_lum` [1536] **and** the white balance sees visible light: one of
  `total_cnt[0..4]` above `night_cnt0..4` [15000] (under IR alone these counts stay low). Thresholds: "do not set more
  than 4096" for the lum values.
- A lock after a switch (`lock_time` [900000 ms]) and a check that the night state did not change meanwhile; IR LED
  protection: `ir_led_on_max_time` [50400 s], `ir_led_off_max_time` [600 s].
- **3.0 so far:** the `ae` source uses the plain exposure index (no division by `lumi`, no white balance check), which
  R9-02 showed cannot separate a dim day room from the night. rc11 logs the white balance counts (`/tmp/cam_awb`,
  `awb=` in the calibration log) so that the vendor's two-part test can be set from tonight's dusk and dawn lines.

## Not looked at yet
- 3D-NR reference size in `akcamera.ko` (3D-NR not kept, R9-01).
- The speaker path (`libplat_ao.so`, `ak_ao_demo`) for the silent speaker.
