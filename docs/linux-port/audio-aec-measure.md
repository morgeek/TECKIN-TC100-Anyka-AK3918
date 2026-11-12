# Echo cancellation: measuring on the camera (`[audio-aec]`, test-queue AEC-01)

Design: `plans-2026-11-12.md` section 3. Code: `src/tc100rtsp/aec.c` (filter), `apb.c` (playback), `talk.c`, `tc100_rtsp.c`.
Switch: `RTSP_AUDIO_AEC=1` in `/mnt/config/rtsp.env` (default 0). This page is what to run on the camera **before** relying
on the defaults (clock ratio, delay), and how to read the result.

## Settings (all in `/mnt/config/rtsp.env`, read when `tc100_rtsp` starts)

| Key | Default | Meaning |
|---|---|---|
| `RTSP_AUDIO_AEC` | `0` | `1` = two-way audio is played by `tc100_rtsp` (not `aplay`) and its echo is removed from the microphone. Needs `RTSP_ALSA_DIRECT=1` (the default). |
| `RTSP_AUDIO_AEC_RATIO` | `1` | Speaker clock divided by microphone clock: speaker frames played per microphone frame. `625/624` or a ppm value (`1600` = 1.0016 = DAC 0.16 % fast, `-800`). Within +-2 %. |
| `RTSP_AUDIO_AEC_DELAY` | `20` | Milliseconds from the speaker queue (as read by `SNDRV_PCM_IOCTL_DELAY`) to the microphone: DAC, amplifier, air, ADC. The filter covers 32 ms behind it (256 taps). |
| `RTSP_AUDIO_AEC_TAPS` | `256` | 32 to 512 (the CPU is in proportion; the RAM is 18 KB whatever the value, allocated only when the switch is 1). |

The ratio comes from the rates in `dmesg` (`actual sample rate is ...`, printed by the codec driver, patch 0007) and from the
click spacing below. The speaker is opened at 8000 Hz, like the microphone; the driver picks the nearest divider for each.

## 1. The probe file (on the computer)

```sh
python3 v3/dev/aec-probe.py make aec-probe.pcm        # raw S16_LE 8 kHz mono, 16 s, always the same bytes
scp aec-probe.pcm v3/dev/aec-measure.sh root@CAMERA:/tmp/
```

1 s of silence, 5 clicks 1 s apart (-6 dBFS), 5 s of white noise at -12 dBFS rms, 5 s of speech-like signal (-20 dBFS rms).

## 2. On the camera (about 90 s, nothing is written to the flash)

```sh
dmesg | grep -i "actual sample rate"                   # the ADC and DAC rates, write them down
sh /tmp/aec-measure.sh                                 # volumes 50, 90, 100
```

`aec-measure.sh` does exactly this, once per volume (the RTSP server is stopped first because it holds the microphone):

```sh
sh /mnt/controlscripts/rtsp-h26x stop
arecord -q -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw -d 19 /tmp/aec-mic-90.raw &
sleep 1; sh /mnt/scripts/speaker-play.sh /tmp/aec-probe.pcm 90; wait
sh /mnt/controlscripts/rtsp-h26x start                 # rtsp-launch.sh: same arguments and rtsp.env as at boot
```

Do not pass `arecord -F/-B` (I/O errors, see AGENTS.md). Bring the three files and the log back:

```sh
scp root@CAMERA:/tmp/aec-mic-*.raw root@CAMERA:/tmp/aec-measure.txt .
```

Put the camera where it stays during use (the echo depends on the room and on what is near the speaker) and keep the room quiet.

## 3. Evaluate on the computer

```sh
python3 v3/dev/aec-probe.py analyze aec-mic-90.raw aec-probe.pcm
```

It prints: the peak (must be below -3 dBFS: above that the microphone or the amplifier clips and no filter helps; lower the
volume or move the microphone), the clock ratio from the spacing of the five clicks (4 intervals, the value for
`RTSP_AUDIO_AEC_RATIO` in ppm), the length of the response after a click (taps needed), and writes `aec-mic-90.raw.aligned`
(the recording cut so that the first click is at 1.000 s like in the probe). Then the offline filter, built on the host
(`make -C src/tc100rtsp test_aec`), run on the aligned file with the measured ratio and with none:

```sh
src/tc100rtsp/test_aec -f aec-probe.pcm aec-mic-90.raw.aligned +1600 0   # with the measured ratio
src/tc100rtsp/test_aec -f aec-probe.pcm aec-mic-90.raw.aligned 0 0       # without
```

One line per second: the echo reduction in dB over that second (0 = nothing removed). Read it from second 8 on (the clicks
and the first noise teach the filter). Last arguments: `ratio d0 queued`, d0 in samples: try 0, 80, 160 (0, 10, 20 ms) to see how much headroom the first taps need.
What to expect: 20 dB or more on the noise and the speech part at 50 and 90; at 100 the speaker distorts and the reduction
drops (the filter is linear; the suppressor takes some of the rest).

Write in the AEC-01 entry of the test queue: the two `actual sample rate` lines, the peak at 50/90/100, the click spacing and
ppm, the response length, the offline reduction with and without the ratio.

## 4. Then on the live server

Put the measured values in `rtsp.env` and restart (`sh /mnt/controlscripts/rtsp-h26x restart`):

```sh
RTSP_AUDIO_AEC=1
RTSP_AUDIO_AEC_RATIO=+1600        # the ppm from the analysis
RTSP_AUDIO_AEC_DELAY=20           # ms; 10 and 40 if the echo is not removed
```

Log lines (`/tmp/logs/tc100_rtsp.log`): `audio: echo cancellation on (clock ratio ..., delay ... ms)` at start;
`talk: speaker closed (echo canceller: N resets, M realigns)` at the end of each talk session. `resets` above 0 means the
filter diverged and started again (double talk, or a wrong delay); `realigns` above a few per minute means the ratio is
wrong (the reference had to be moved to follow the drift) or the playback queue jumps.
Then the talk test of the queue entry (go2rtc or Home Assistant talk plus a second person in the room).
