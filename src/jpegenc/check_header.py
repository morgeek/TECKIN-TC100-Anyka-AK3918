#!/usr/bin/env python3
"""Compare the DQT / SOF0 / DHT / SOS segments of `jpegenc --dry` (out.jpg.header) with a vendor JPEG.
Usage: check_header.py out.jpg.header vendor.jpg"""
import sys
def segs(d):
    i = 2; out = []
    while i + 4 <= len(d) and d[i] == 0xff:
        m = d[i + 1]; l = int.from_bytes(d[i + 2:i + 4], 'big')
        out.append((m, bytes(d[i + 4:i + 2 + l])))
        if m == 0xda: break
        i += 2 + l
    return out
mine = segs(open(sys.argv[1], 'rb').read()); ven = segs(open(sys.argv[2], 'rb').read())
ok = True
for m in (0xdb, 0xc0, 0xc4, 0xda):
    a = [b for k, b in mine if k == m]; b = [b for k, b in ven if k == m]
    same = a == b
    print('marker %02x: %d segment(s) %s' % (m, len(a), 'identical to the vendor file' if same else 'DIFFERENT'))
    ok &= same
sys.exit(0 if ok else 1)
