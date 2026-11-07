#!/usr/bin/env python3
"""Analysis of the captures of the vendor H.265 encoder on Linux 6.6 (step 2 of the free encoder, 2026-11-07).

On the camera, tc100_rtsp restarted with
    AKUIO_CAPTURE=/tmp/cap/c      (libakuio: PREFIX.<n>.cap after each of the first 12 encoder interrupts)
    RTSP_SAVE_FRAMES=/tmp/cap/f   (tc100_rtsp: PREFIX.<n>.h26x = the pictures the vendor library returned, PREFIX.log)
then, on a computer:
    python3 capture.py DIR [--out DIR2]

It answers the open questions of README.md:
  1. where the size of a coded picture is: each saved picture is located in the stream buffer of a capture (by its
     address, PREFIX.log), then its length is searched for in the status words of the list, the registers and the
     first 0x820 bytes of the stream buffer (as is, in bits, in 32-bit units, minus a header);
  2. whether the core writes the parameter sets and the slice header itself (the stream buffer at the picture's address
     against the returned bytes; the NAL types of the returned picture);
  3. whether the 0x4040-byte table buffer, the work and small buffers change from picture to picture;
  4. whether the lists of the 3.0 vendor library (libmpi_venc_ex.so) are still what cmdlist.build_list makes.
With --out, the inputs of h265enc.c for its first run are written: list.bin (the input words of the first IDR list),
tables.bin, work.bin, small.bin (that IDR's buffers), params.bin (the VPS/SPS/PPS NALs of the first saved IDR) and
in.nv12 (the source of that IDR: h265enc encodes the same picture, so its stream can be compared byte for byte) and
plist.bin (a P list for the same buffers, from cmdlist.build_list, for h265live).
Those files are data read from the camera's vendor encoder: they stay on the test machine, never in git.
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cmdlist  # noqa: E402

TAGS = ('REGS', 'CLK ', 'LIST', 'TABL', 'WORK', 'SMAL', 'STRM')


def read_cap(path):
    with open(path, 'rb') as fh:
        d = fh.read()
    if d[:8] != b'TC100CAP':
        raise ValueError('%s: not a TC100CAP file' % path)
    ver, pool_paddr, pool_vaddr, pool_size, wait = struct.unpack_from('<5I', d, 8)
    cap = {'path': path, 'version': ver, 'pool_paddr': pool_paddr, 'pool_vaddr': pool_vaddr, 'pool_size': pool_size,
           'wait': wait, 'rec': {}}
    i = 28
    while i + 12 <= len(d):
        tag = d[i:i + 4].decode('latin-1'); paddr, n = struct.unpack_from('<II', d, i + 4)
        cap['rec'][tag] = (paddr, d[i + 12:i + 12 + n])
        i += 12 + n + (-n & 3)
    return cap


def words(b):
    return list(struct.unpack('<%dI' % (len(b) // 4), b[:len(b) // 4 * 4]))


def nals(data):
    """[(offset of the start code, nal type, length up to the next start code)] of an Annex B H.265 stream"""
    out = []; i = 0; n = len(data); starts = []
    while i + 3 <= n:
        if data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 1:
            s = i - 1 if i > 0 and data[i - 1] == 0 else i
            starts.append((s, i + 3)); i += 3
        else:
            i += 1
    for k, (s, h) in enumerate(starts):
        e = starts[k + 1][0] if k + 1 < len(starts) else n
        out.append((s, (data[h] >> 1) & 0x3f if h < n else -1, e - s))
    return out


def load(dirpath):
    caps = []; frames = []
    for name in sorted(os.listdir(dirpath)):
        p = os.path.join(dirpath, name)
        if name.endswith('.cap'):
            caps.append(read_cap(p))
    caps.sort(key=lambda c: c['wait'])
    for name in sorted(os.listdir(dirpath)):
        if name.endswith('.log') and os.path.exists(os.path.join(dirpath, name[:-4] + '.0.h26x')):
            pre = os.path.join(dirpath, name[:-4])
            with open(os.path.join(dirpath, name)) as fh:
                for line in fh:
                    f = line.split()
                    if len(f) != 3:
                        continue
                    n, va, ln = int(f[0]), int(f[1], 16), int(f[2])
                    hp = '%s.%d.h26x' % (pre, n)
                    data = open(hp, 'rb').read() if os.path.exists(hp) else b''
                    frames.append({'n': n, 'vaddr': va, 'len': ln, 'data': data})
    return caps, frames


def size_candidates(cap, length, hdr=0x820):
    """places in the capture holding the picture length in some unit"""
    want = {length: 'bytes', length * 8: 'bits', (length + 3) // 4: 'words', length - hdr: 'bytes - 0x820',
            length + hdr: 'bytes + 0x820'}
    found = []
    lp, lb = cap['rec'].get('LIST', (0, b''))
    for i, w in enumerate(words(lb)):
        for v, unit in want.items():
            if w == v or (w & 0xffffff) == v and v > 0xff:
                found.append(('list word 0x%02x' % i, w, unit))
    rp, rb = cap['rec'].get('REGS', (0, b''))
    for i, w in enumerate(words(rb)):
        for v, unit in want.items():
            if w == v:
                found.append(('register 0x%04x' % (0x8000 + 4 * i), w, unit))
    sp, sb = cap['rec'].get('STRM', (0, b''))
    for i, w in enumerate(words(sb[:hdr])):
        for v, unit in want.items():
            if w == v:
                found.append(('stream head +0x%03x' % (4 * i), w, unit))
    return found


def report(caps, frames, out=sys.stdout):
    w = out.write
    if not caps:
        w('no .cap file\n'); return
    c0 = caps[0]
    w('pool %08x (+%x bytes) mapped at %08x in the encoder process; %d captures, %d saved pictures\n'
      % (c0['pool_paddr'], c0['pool_size'], c0['pool_vaddr'], len(caps), len(frames)))
    seen = {}
    for c in caps:
        lp, lb = c['rec'].get('LIST', (0, b''))
        lw = words(lb)
        if len(lw) < 0x40:
            w('wait %d: no list\n' % c['wait']); continue
        f = cmdlist.decode(lw)
        idr = f['sp_40'] == 2
        built = cmdlist.build_list(idr, f['qp'], f['sp_98'], lw[0x20], lw[0x21], lw[0x24], lw[0x28], lw[0x23], lw[0x27],
                                   lw[0x2f], lw[0x30], stream_alloc=lw[0x31] + 0x200, stream_offset=lw[0x32])
        bad = [i for i in range(0x40) if built[i] != lw[i] and not (idr and i in (0x28, 0x29, 0x2c, 0x38))]
        hs = {t: hashlib.sha1(c['rec'][t][1]).hexdigest()[:10] for t in ('TABL', 'WORK', 'SMAL') if t in c['rec']}
        for t, h in hs.items():
            seen.setdefault(t, set()).add(h)
        w('wait %2d: list %08x %s qp %2d poc %3d  model %s  status %s  tables %s\n'
          % (c['wait'], lp, 'IDR' if idr else 'P  ', f['qp'], f['sp_98'],
             'same' if not bad else 'differs in words ' + ' '.join('0x%02x' % i for i in bad),
             ' '.join('%08x' % x for x in lw[0x40:0x48]), hs.get('TABL', '-')))
    for t, hs in sorted(seen.items()):
        w('%s buffer: %s\n' % (t, 'the same in every capture' if len(hs) == 1 else '%d different contents' % len(hs)))
    for fr in frames:
        pa = fr['vaddr'] - c0['pool_vaddr'] + c0['pool_paddr']
        kinds = [t for (_, t, _) in nals(fr['data'])]
        w('picture %d: %d bytes at %08x (pool +%x), NAL types %s\n' % (fr['n'], fr['len'], pa, pa - c0['pool_paddr'], kinds))
        for c in caps:
            sp, sb = c['rec'].get('STRM', (0, b''))
            sl = [(s, t, n) for (s, t, n) in nals(fr['data']) if t in (1, 19, 20)]
            if sl and len(sb) > 0x860:
                body = fr['data'][sl[0][0]:sl[0][0] + sl[0][2]]
                for k in range(4, 32):
                    if body[k:k + 64] == sb[0x820:0x820 + 64]:
                        lw = words(c['rec']['LIST'][1])
                        w('    slice data written by the core at stream +0x820 of wait %d: %d bytes (list word 0x41 = %d); '
                          'the %d bytes before it come from the software: %s\n'
                          % (c['wait'], len(body) - k, lw[0x41], k, body[:k].hex()))
                        break
            if sp <= pa < sp + len(sb):
                off = pa - sp
                same = sb[off:off + fr['len']] == fr['data'][:len(sb) - off]
                w('    in the stream buffer of wait %d at +0x%x, bytes %s; length found at: %s\n'
                  % (c['wait'], off, 'identical' if same else 'DIFFERENT',
                     '; '.join('%s = %d (%s)' % x for x in size_candidates(c, fr['len'])) or 'nowhere'))


def write_inputs(caps, frames, outdir):
    os.makedirs(outdir, exist_ok=True)
    # the IDR list of a capture after the core finished (stream buffer captured, status words set): at the first of the
    # two interrupts of a picture the list memory is not the picture's yet (IPCAM2 2026-11-07, wait 0)
    for c in sorted(caps, key=lambda c: ('STRM' not in c['rec'], c['wait'])):
        lw = words(c['rec'].get('LIST', (0, b''))[1])
        if len(lw) >= 0x40 and cmdlist.decode(lw)['sp_40'] == 2:
            open(os.path.join(outdir, 'list.bin'), 'wb').write(struct.pack('<64I', *lw[:0x40]))
            # the P list for the same buffers (cmdlist.build_list: the 3.0 IDR list matched it word for word), for h265live
            q = cmdlist.decode(lw)['qp']
            pl = cmdlist.build_list(False, q, 2, lw[0x20], lw[0x21], lw[0x24], lw[0x24] ^ 0x340000, lw[0x23], lw[0x27],
                                    lw[0x2f], lw[0x30], stream_alloc=lw[0x31] + 0x200, stream_offset=lw[0x32])
            open(os.path.join(outdir, 'plist.bin'), 'wb').write(struct.pack('<64I', *pl[:0x40]))
            for t, n in (('TABL', 'tables.bin'), ('WORK', 'work.bin'), ('SMAL', 'small.bin')):
                if t in c['rec']:
                    open(os.path.join(outdir, n), 'wb').write(c['rec'][t][1])
            break
    for c in caps:
        if 'SRCY' in c['rec'] and 'SRCU' in c['rec']:
            # the picture the vendor encoded: h265enc encodes it again, and the two streams can be compared
            open(os.path.join(outdir, 'in.nv12'), 'wb').write(c['rec']['SRCY'][1] + c['rec']['SRCU'][1])
            break
    for fr in frames:
        # the start code, NAL header and slice header the vendor SOFTWARE writes before the core's slice data (the core
        # writes from stream +0x820; IPCAM2 2026-11-07: 9 bytes, 00 00 00 01 26 01 + 3 header bytes, IDR qp 36)
        sl = [(s, t, n) for (s, t, n) in nals(fr['data']) if t in (19, 20)]
        if sl:
            body = fr['data'][sl[0][0]:sl[0][0] + sl[0][2]]
            for c in caps:
                sb = c['rec'].get('STRM', (0, b''))[1]
                for k in range(4, 32):
                    if len(sb) > 0x820 and body[k:k + 64] == sb[0x820:0x820 + 64]:
                        open(os.path.join(outdir, 'slicehead.bin'), 'wb').write(body[:k])
                        break
            break
    for fr in frames:
        ps = b''.join(fr['data'][s:s + n] for (s, t, n) in nals(fr['data']) if t in (32, 33, 34))
        if ps:
            open(os.path.join(outdir, 'params.bin'), 'wb').write(ps)
            break
    return sorted(os.listdir(outdir))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    caps, frames = load(sys.argv[1])
    report(caps, frames)
    if '--out' in sys.argv:
        print('h265enc inputs:', write_inputs(caps, frames, sys.argv[sys.argv.index('--out') + 1]))
