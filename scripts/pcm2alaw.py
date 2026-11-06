#!/usr/bin/env python3
"""pcm2alaw.py DIR: the built-in speaker clips of the flash image as G.711 A-law (audit 2026-11-06 S7, owner).

Build tool (v3/build-stack.sh), never run on the camera. Each DIR/NAME.pcm (raw 8 kHz mono signed 16-bit little
endian, as the sound generator of scripts/ makes them) becomes DIR/NAME.alaw (one byte a sample: half the size; the siren's
32,000 bytes of noise-like PCM did not compress in the xz squashfs) and the .pcm is removed. The 1 kHz test tones
(test-1k-*.pcm) are left as they are: bench only, and left out of the flash image anyway.
scripts/speaker-play.sh plays *.alaw with `aplay -t raw -f A_LAW` (the alaw plugin of the base's alsa-lib).
Python's audioop (removed in 3.13) is not used: the encoder below is the G.711 reference algorithm.
"""
import os
import struct
import sys

SEG_END = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)   # 13-bit segment ends (A-law)


def linear2alaw(sample):
    """G.711 A-law of one signed 16-bit sample (ITU-T G.711, as in the Sun reference g711.c)."""
    pcm = sample >> 3                       # 13-bit magnitude range
    if pcm >= 0:
        mask = 0xD5                         # sign bit set, even bits inverted
    else:
        mask = 0x55
        pcm = -pcm - 1
    seg = 0
    while seg < 8 and pcm > SEG_END[seg]:
        seg += 1
    if seg >= 8:
        return 0x7F ^ mask
    aval = seg << 4
    aval |= (pcm >> 1) & 0x0F if seg < 2 else (pcm >> seg) & 0x0F
    return aval ^ mask


def alaw2linear(a):
    """Inverse, for the tests (ITU-T G.711)."""
    a ^= 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t += 0x108
        t <<= seg - 1
    return t if a & 0x80 else -t


def convert(path_in, path_out):
    data = open(path_in, 'rb').read()
    if len(data) % 2:
        raise SystemExit('pcm2alaw: %s: odd length, not 16-bit PCM' % path_in)
    samples = struct.unpack('<%dh' % (len(data) // 2), data)
    open(path_out, 'wb').write(bytes(linear2alaw(s) for s in samples))


def main(d):
    n = 0
    for name in sorted(os.listdir(d)):
        if not name.endswith('.pcm') or name.startswith('test-1k-'):
            continue
        src = os.path.join(d, name)
        convert(src, src[:-4] + '.alaw')
        os.remove(src)
        n += 1
    print('pcm2alaw: %d clips in %s' % (n, d))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: pcm2alaw.py DIR')
    main(sys.argv[1])
