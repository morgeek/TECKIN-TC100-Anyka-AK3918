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

## Speaker (R12-04): the amplifier enable is active low
- Vendor kernel 3.4.35 (the dump's uImage, xz payload): the codec's speaker function writes the board's speaker pin
  level as given, no polarity mapping; at probe it is set to 1 (high). The app (`anyka_ipc`) calls
  `ak_ao_enable_speaker(1)` at audio init and `ak_ao_enable_speaker(0)` **just before** playing a voice prompt, 1 after;
  `libplat_ao` passes it as ioctl `_IOW('P', 0x81, int)` (IOC_SET_SPEAKER) on `/dev/akpcm_cdev0`. So the speaker plays
  while GPIO 14 is **low**. The 2.x push-to-talk worked once the stock `ak_ao_demo`'s two levels were swapped
  (`scripts/prepare-ptt-player.sh` on the 2.x branch), the same conclusion.
- 3.0 drove it active high (`speak-gpios-en = <1>`): the amplifier was off while playing and on at rest, which matches
  rc7's register reading (bank 0 output 0x8800 at rest, 0xC800 while playing). rc12: `speak-gpios-en = <0>`, the
  amplifier off at rest (a route change or the headphone check no longer switches it on), `ak39_codec.spk_active=0|1`
  overrides the level from the command line.
- The probe mixer defaults (headphone 3, line-in 10, mic 6, route 4) are those of patch 0007.

## ISP: two parameter sets, and the night one was never used (R12-01, R12-02)
- `isp_f23_mipi2lane.conf` (69548 bytes) holds two complete sets of 34774 bytes: set 0 day, set 1 night. Night: manual
  white balance, no colour (`uv_a` 0), exposure up to 2812 lines (2.5 x), `exp_step` 1, AE target 45 (day 38), its
  own noise filters, sharpness, gammas, CCM; frame rate 10 fps fixed. Day: 25 fps, down to 10 fps when the gain goes
  above 14 x, back to 25 under 5 x.
- The stock app reloads the whole set at every switch (`ak_vi_switch_mode`), re-applies the user's effects on top,
  sets the white balance step to 10 for a quick convergence, then asks for a keyframe. Order to night: IR LED on, set 1,
  IR-cut; to day: IR-cut, set 0, IR LED off. IR-cut pulse 10 ms (3.0: 150 ms, `IRCUT_PULSE_MS`).
- 3.0 kept the day set at night and only turned the colour off. rc12: `AK_ISP_SET_TUNING_STYLE` (already in the
  kernel) to the night set when black and white starts (Day/night page switch), the bases re-read after each switch.
- Low light by day (`change_fps_pthread`): total gain = isp x ((a x d) >> 8) >> 16; above 14 -> 10 fps and exposure up
  to 2812 lines, under 5 -> 25 fps and 1125; checked every 100 ms, 5 s between changes; `exp_step` stays one lamp pulse.
  rc12: the same in `tc100_rtsp` (Day/night page switch), every 2 s.
- Colour cast: the stock app applies no colour correction of its own (user effects are relative and 0 by default, the
  day set's extra white balance gains are neutral), and the 3.0 kernel loads the same day modules: the warm cast is not
  something the app fixed. The software white balance stays until an A/B test shows the ISP alone is neutral.

## Day / night: the remaining details (R12-03, R12-05)
- `lum_factor = exp_time * gain_q8 / exp_max`, `gain_q8 = ((a_gain * d_gain) >> 8) * isp_d_gain >> 8`, with exp_max
  the current mode's limit (1125 at 25 fps, 2812 at 10 fps): at full exposure it is the total gain (256 = 1 x). Called
  every second, about 3-4 s of sampling per decision (500 ms wait, 3 agreeing samples, 3 decision samples, 500 ms apart).
- A switch request less than 15 s after the last switch locks the state for `lock_time` (900 s in the stock ini, 1800 s
  library default) unless lum moves by more than 30 % from the value at the switch (or a white balance count by 30 %
  and 10000). Library defaults without ini: 3072 / 2048, night counts 1200, day counts 50000.
- With the 10 fps low-light mode the dim day room of R9-02 gives lum about 2900 (under 3584: day); without it about
  5470 (would be night): the stock thresholds need R12-02.
- IR LED protection (`ir_switch_handler`): after 50400 s (14 h) of IR LEDs, day mode forced; after 600 s, night again.
- rc12: `DAYNIGHT_SOURCE=vendor` reproduces this in `auto-night-daemon.sh` (3 samples 2 s apart), and the IR LED
  protection runs for every source (on by default, 14 h / 10 min, Day/night page).

## Not looked at
- 3D-NR reference size in `akcamera.ko` (3D-NR not kept, R9-01).
- `libakaudiofilter` (echo cancellation and noise reduction for the microphone), for later.
