#!/usr/bin/env python3
"""v3/dev/aec-probe.py: the probe file and the evaluation of the echo cancellation measurements (docs/linux-port/audio-aec-measure.md).

  aec-probe.py make [FILE]                 write the probe (default aec-probe.pcm: raw S16_LE, 8 kHz, mono, 16 s):
                                           1 s silence, 5 clicks 1 s apart (-6 dBFS, 2 samples), 5 s white noise at -12 dBFS
                                           rms, 5 s speech-like signal (voiced pulses through three formants, 4 syllables a
                                           second, -20 dBFS rms). Deterministic: the same file every time.
  aec-probe.py analyze MIC.raw [PROBE]     what the recording of the probe (same raw format, recorded while the probe played)
                                           tells: peak level, delay of the first click, click spacing (the clock ratio:
                                           speaker frames per microphone frame, as ppm for RTSP_AUDIO_AEC_RATIO), length of
                                           the response after a click, and the d0 / ratio to give to test_aec -f.

Python 3 standard library only; run it on the computer, not on the camera."""
import array
import math
import random
import sys

RATE = 8000


def tone_free_speech(n, rng):
    """voiced pulse train (pitch 100-140 Hz, wandering) through three resonators, syllable envelope"""
    out = [0.0] * n
    res = [(700, 80), (1200, 90), (2600, 120)]
    st = [[0.0, 0.0] for _ in res]
    coef = []
    for f, bw in res:
        r = math.exp(-math.pi * bw / RATE)
        coef.append((2 * r * math.cos(2 * math.pi * f / RATE), -r * r))
    phase, pitch = 0.0, 120.0
    for i in range(n):
        pitch += rng.uniform(-0.05, 0.05)
        pitch = min(140.0, max(100.0, pitch))
        phase += pitch / RATE
        x = 0.0
        if phase >= 1.0:
            phase -= 1.0
            x = 1.0
        y = 0.0
        for k, (a1, a2) in enumerate(coef):
            v = x + a1 * st[k][0] + a2 * st[k][1]
            st[k][1], st[k][0] = st[k][0], v
            y += v
        env = max(0.0, math.sin(2 * math.pi * 4 * i / RATE)) ** 0.5
        out[i] = y * env
    return out


def rms_scale(x, dbfs):
    r = math.sqrt(sum(v * v for v in x) / len(x)) or 1.0
    g = 32768.0 * 10 ** (dbfs / 20.0) / r
    return [v * g for v in x]


def make(path):
    rng = random.Random(20261112)
    pcm = [0.0] * RATE                                   # 1 s of silence
    for _ in range(5):                                   # 5 clicks, 1 s apart
        c = [0.0] * RATE
        c[0] = c[1] = 32768.0 * 0.5
        pcm += c
    pcm += rms_scale([rng.gauss(0, 1) for _ in range(5 * RATE)], -12)
    pcm += rms_scale(tone_free_speech(5 * RATE, rng), -20)
    a = array.array('h', (max(-32768, min(32767, int(round(v)))) for v in pcm))
    if sys.byteorder == 'big':
        a.byteswap()
    with open(path, 'wb') as f:
        a.tofile(f)
    print('%s: %d samples, %.0f s' % (path, len(a), len(a) / RATE))


def load(path):
    a = array.array('h')
    with open(path, 'rb') as f:
        data = f.read()
    a.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder == 'big':
        a.byteswap()
    return a


def db(v):
    return 20 * math.log10(max(v, 1) / 32768.0)


def analyze(mic_path, probe_path):
    mic, probe = load(mic_path), load(probe_path)
    n = len(mic)
    print('recording: %d samples, %.1f s' % (n, n / RATE))
    peak = max(abs(v) for v in mic)
    print('peak %.1f dBFS%s' % (db(peak), '   (clipped: lower the volume)' if peak >= 32000 else ''))
    head = mic[:min(n, int(5.5 * RATE) + 4000)]
    m = max(abs(v) for v in head)
    if m < 300:
        print('no click heard (peak %d): wrong volume, amplifier off, or the recording did not run during the playback' % m)
        return 1
    first = next(i for i, v in enumerate(head) if abs(v) > 0.5 * m)
    # the probe has its first click at 1.0 s: first - 8000 is the delay between the start of the recording and the playback
    # (not the delay of the speaker path: the recorder and the player were started by different processes)
    pos = [first]
    for k in range(1, 5):
        c = first + k * RATE
        win = range(max(0, c - 600), min(n, c + 600))
        pos.append(max(win, key=lambda i: abs(mic[i])) if len(win) else c)
    spacing = (pos[4] - pos[0]) / 4.0
    ratio = RATE / spacing
    ppm = (ratio - 1.0) * 1e6
    print('first click at sample %d (%.3f s); spacing of the 5 clicks %.2f samples (4 intervals)' % (first, first / RATE, spacing))
    print('clock ratio, speaker frames per microphone frame: %.6f = %+.0f ppm  ->  RTSP_AUDIO_AEC_RATIO=%+.0f' % (ratio, ppm, ppm))
    if abs(spacing - RATE) > 80:
        print('   (spacing far from 8000: a click was missed, run again at a lower noise level)')
    # response after the first click: windows of 2 ms, from the peak until 30 dB below it
    p0 = max(range(first, min(n, first + 400)), key=lambda i: abs(mic[i]))
    win = 16
    levels = []
    for s in range(p0, min(n, p0 + RATE // 4), win):
        seg = mic[s:s + win]
        levels.append(max(abs(v) for v in seg))
    ref = levels[0] or 1
    length = 0
    for i, v in enumerate(levels):
        if v > ref * 0.0316:                              # -30 dB
            length = i
    print('response after a click: %.1f ms until 30 dB below the peak (taps needed at least %d, 256 = 32 ms)' %
          (length * win / RATE * 1000, (length + 1) * win))
    # the recorder and the player are two processes: the recording starts some time before the probe. The click puts the
    # start of the probe in the recording (plus the delay of the speaker path, which is what the first click then defines
    # as zero): the aligned file starts there, and the delay of the path between the speaker queue and the microphone is
    # removed from it (it is set by RTSP_AUDIO_AEC_DELAY, the filter then covers 32 ms of room response behind it).
    start = max(0, first - RATE)
    aligned = mic_path + '.aligned'
    out = array.array('h', mic[start:])
    if sys.byteorder == 'big':
        out.byteswap()
    with open(aligned, 'wb') as f:
        out.tofile(f)
    print()
    print('aligned recording (starts %d samples in, the first click at 1.000 s like in the probe): %s' % (start, aligned))
    print('evaluate offline (echo reduction per second, 0 = nothing removed; needs src/tc100rtsp/test_aec built on the host):')
    print('  src/tc100rtsp/test_aec -f %s %s %+.0f 0' % (probe_path, aligned, ppm))
    print('  without the skew correction for comparison:  src/tc100rtsp/test_aec -f %s %s 0 0' % (probe_path, aligned))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == 'make':
        make(argv[2] if len(argv) > 2 else 'aec-probe.pcm')
        return 0
    if len(argv) >= 3 and argv[1] == 'analyze':
        return analyze(argv[2], argv[3] if len(argv) > 3 else 'aec-probe.pcm')
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
