import math
import os
import struct

# The camera's clips: raw 8 kHz mono signed 16-bit little endian (scripts/speaker-play.sh).
# R12-04: the speaker played the old full-scale (0 dBFS) tones weak and crackling at every volume; the clips are now
# at -6 dBFS with 5 ms fades (no click at the start and end), and the test-*.pcm tones (1 kHz at -6, -12 and -20 dBFS)
# tell clipping (cleaner when lower) from a playback path fault (crackling whatever the level).

def generate_pcm(filename, duration_sec=1.0, freq=440, sample_rate=8000, dbfs=-6.0, fade_ms=5):
    num_samples = int(duration_sec * sample_rate)
    amp = 32767 * 10 ** (dbfs / 20.0)
    fade = max(1, int(sample_rate * fade_ms / 1000))
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as f:
        for i in range(num_samples):
            g = min(1.0, i / fade, (num_samples - 1 - i) / fade)
            f.write(struct.pack('<h', int(round(amp * g * math.sin(2.0 * math.pi * freq * i / sample_rate)))))


if __name__ == "__main__":
    # Success sound: double beep
    generate_pcm("sounds/startup.pcm", duration_sec=0.2, freq=800)
    generate_pcm("sounds/startup_2.pcm", duration_sec=0.2, freq=1200)

    # Combined sound file for startup
    with open("sounds/startup_complete.pcm", "wb") as outfile:
        for f in ["sounds/startup.pcm", "sounds/startup_2.pcm"]:
            with open(f, "rb") as infile:
                outfile.write(infile.read())

    # Motion detected: three 1 kHz beeps (R16: one 0.5 s 400 Hz tone was missed at the default volume)
    generate_pcm("sounds/beep.tmp", duration_sec=0.3, freq=1000)
    beep = open("sounds/beep.tmp", "rb").read()
    gap = b"\x00\x00" * int(0.15 * 8000)
    with open("sounds/alert.pcm", "wb") as f:
        f.write(beep + gap + beep + gap + beep)
    os.remove("sounds/beep.tmp")

    # Speaker test tones (test queue R15-02)
    for db in (6, 12, 20):
        generate_pcm("sounds/test-1k-m%d.pcm" % db, duration_sec=3.0, freq=1000, dbfs=-db)

    print("Generated PCM files in sounds/ directory.")
