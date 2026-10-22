#!/usr/bin/env python3
"""Register sequence of one H.265 frame on the encoder core, as done by the vendor control software.

Offsets are inside the window at 0x20020000. `cycle()` returns the operations between two starts
('RD', offset, None) / ('WR', offset, value | callable(read values)); `check_trace()` replays a
recorded trace (vtparse format: records of the vendor encoder's hardware callbacks) against it.

Sequence (frame n, list_paddr = physical address of its command list):
  WR 0x8084 = 2                         start (done at the end of the previous cycle)
  wait for the interrupt twice
  RD 0x8014 ; WR 0x8014 = same          mask (bit 0 and bit 18 stay set)
  RD 0x8020 (0x10001) ; WR 0x8020 = 0x10000    acknowledge
  ... the CPU reads the status words of the list from memory ...
  RD 0x801c ; RD 0x8020 (0) ; WR 0x8020 = 1
  WR 0x8010 = 0x1000007 ; WR 0x822c = 0
  RD 0x8014 ; WR 0x8014 = same
  RD 0xc004 ; WR 0xc004 = v | 0x8e00     (the JPEG path clears bit 15 instead: (v & ~0x8000) | 0xe00)
  RD 0x8300
  WR 0x8080 = list_paddr
  WR 0x8084 = 2                         start of the next frame
"""
import struct, sys

R_START, R_LIST, R_MASK, R_IRQ_EN, R_STAT, R_ACK, R_CLK, R_UNK = 0x8084, 0x8080, 0x8014, 0x8010, 0x801c, 0x8020, 0xc004, 0x8300
R_CLR = 0x822c


def cycle(list_paddr):
    same = lambda v: v          # write back what was read
    return [
        ('IRQ', 0, None), ('IRQ', 0, None),
        ('RD', R_MASK, None), ('WR', R_MASK, same),
        ('RD', R_ACK, 0x10001), ('WR', R_ACK, 0x10000),
        ('RD', R_STAT, None), ('RD', R_ACK, 0), ('WR', R_ACK, 1),
        ('WR', R_IRQ_EN, 0x1000007), ('WR', R_CLR, 0),
        ('RD', R_MASK, None), ('WR', R_MASK, same),
        ('RD', R_CLK, None), ('WR', R_CLK, lambda v: v | 0x8e00),
        ('RD', R_UNK, None),
        ('WR', R_LIST, list_paddr),
        ('WR', R_START, 2),
    ]


def load(path):
    with open(path, 'rb') as fh:
        d = fh.read()
    assert d[:8] == b'TC100VTR'
    out = []; i = 16
    while i + 16 <= len(d):
        t, ty, aux, a, b = struct.unpack('<IHHII', d[i:i + 16]); i += 16
        if ty == 9: i += ((b + 15) // 16) * 16
        out.append((t, ty, a, b))
    return out


def ops_between_starts(rec):
    """list of (value written to 0x8084, [ops]) for each start, ops = those before the next start"""
    segs = []; cur = None
    for t, ty, a, b in rec:
        if ty == 2 and a == 0x20028084:
            cur = [b, []]; segs.append(cur)
        elif cur is not None:
            if ty == 1: cur[1].append(('RD', a & 0xffff, b))
            elif ty == 2: cur[1].append(('WR', a & 0xffff, b))
            elif ty == 5: cur[1].append(('IRQ', 0, None))
    return segs


def match(ops, expect):
    """True when the recorded ops (without the start itself) follow `expect`"""
    if len(ops) != len(expect): return False
    last_read = {}
    for (k, o, v), (ek, eo, ev) in zip(ops, expect):
        if k != ek or o != eo: return False
        if k == 'RD':
            last_read[o] = v
            if ev is not None and v != ev: return False
        elif k == 'WR':
            want = ev(last_read.get(o, 0)) if callable(ev) else ev
            if v != want: return False
    return True


def check_trace(path):
    segs = ops_between_starts(load(path))
    ok = bad = 0; skipped = 0; notes = []
    for n in range(len(segs) - 1):
        val, ops = segs[n]; nval = segs[n + 1][0]
        if val != 2 or nval != 2:        # only H.265 -> H.265 cycles (JPEG starts are 0x10)
            skipped += 1; continue
        ops = [o for o in ops if True]
        lp = [v for (k, o, v) in ops if k == 'WR' and o == R_LIST]
        exp = cycle(lp[0] if lp else 0)[:-1]
        if match(ops, exp): ok += 1
        else:
            bad += 1; notes.append(n)
    return ok, bad, skipped, notes


if __name__ == '__main__':
    ok, bad, skipped, notes = check_trace(sys.argv[1])
    print('H.265 cycles matching the sequence: %d, not matching: %d (frames %s), skipped (JPEG in between): %d' % (ok, bad, notes[:10], skipped))
