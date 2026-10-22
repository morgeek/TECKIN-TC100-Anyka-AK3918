#!/usr/bin/env python3
"""Command list of the AK3918EV300 H.264/H.265 encoder core (Allegro DVT "Enc1/Enc2" registers).

One list is 112 words (448 bytes), in DMA memory; its physical address goes to 0x20028080 and
0x20028084 = 2 starts it. The vendor control software keeps two lists and alternates them.

  words 0x00-0x1f  parameter registers   (SliceParamToCmdRegsEnc1: 0x00-0x13, 0x19; Enc2: 0x1b-0x1f)
  words 0x20-0x3f  DMA addresses and strides (source, reconstructed / reference frames, side buffers)
  words 0x40-0x6f  status written back by the core (sizes, statistics)

FIELDS gives, for each parameter word, the bit fields exactly as the vendor's SliceParamToCmdRegs
packs them (transcribed from the decompiled library). Names are the offset of the byte in the
vendor's slice-parameter structure (`sp_xx`), with a meaning when the recorded frames make it
certain. `check_coverage` verifies the table against recorded lists (no unexplained bit set).
"""
import json, sys

LIST_WORDS = 112
PARAM_WORDS = 0x20
ADDR_FIRST, ADDR_LAST = 0x20, 0x3f
STATUS_FIRST = 0x40

# (word, low bit, number of bits, name)
FIELDS = [
 (0x00, 0, 3, 'sp_00'), (0x00, 4, 3, 'sp_01'), (0x00, 8, 2, 'sp_02_m2'), (0x00, 10, 2, 'sp_03_m2'),
 (0x00, 12, 2, 'sp_04_m2'), (0x00, 14, 3, 'sp_05'), (0x00, 17, 3, 'sp_06'), (0x00, 20, 3, 'sp_07_m4'),
 (0x00, 24, 3, 'sp_08_m4'), (0x00, 28, 2, 'slice_type_c'), (0x00, 31, 1, 'last_entry'),
 (0x01, 0, 11, 'width_8px_m1'), (0x01, 12, 11, 'height_8px_m1'), (0x01, 24, 4, 'sp_16'), (0x01, 28, 4, 'sp_17'),
 (0x02, 0, 3, 'sp_18'), (0x02, 3, 1, 'sp_20_b0'), (0x02, 4, 3, 'sp_19'), (0x02, 7, 1, 'sp_1a'), (0x02, 8, 2, 'sp_1b'),
 (0x02, 10, 1, 'sp_1c'), (0x02, 11, 4, 'sp_1d_bit13_forced_1'), (0x02, 15, 1, 'sp_24'),
 (0x02, 16, 2, 'sp_25'), (0x02, 18, 2, 'sp_26'), (0x02, 20, 2, 'sp_28'), (0x02, 22, 1, 'sp_2c'), (0x02, 23, 1, 'sp_2d'),
 (0x02, 24, 1, 'sp_2e'), (0x02, 25, 1, 'sp_2f'), (0x02, 26, 1, 'sp_30'), (0x02, 27, 1, 'sp_31'), (0x02, 28, 1, 'sp_32'),
 (0x02, 29, 1, 'sp_33'), (0x02, 30, 1, 'sp_34'), (0x02, 31, 1, 'sp_35'),
 (0x03, 0, 5, 'sp_36'), (0x03, 8, 5, 'sp_37'), (0x03, 16, 8, 'qp'), (0x03, 24, 2, 'sp_3b'), (0x03, 26, 1, 'sp_3c'),
 (0x03, 27, 1, 'sp_3d'), (0x03, 28, 2, 'sp_40'), (0x03, 30, 1, 'sp_50_zero'), (0x03, 31, 1, 'sp_44'),
 (0x04, 0, 5, 'sp_45'), (0x04, 8, 6, 'sp_46'), (0x04, 16, 1, 'sp_47'), (0x04, 17, 1, 'sp_48'), (0x04, 18, 1, 'sp_49'),
 (0x04, 19, 1, 'sp_4a'),
 (0x05, 0, 10, 'sp_50_rem'), (0x05, 12, 10, 'sp_50_quot'), (0x05, 22, 1, 'sp_a2'), (0x05, 23, 1, 'sp_aa'),
 (0x05, 24, 4, 'sp_55'), (0x05, 28, 4, 'sp_54'),
 (0x06, 0, 10, 'sp_58_rem'), (0x06, 12, 10, 'sp_58_quot'), (0x06, 22, 1, 'sp_5c'), (0x06, 23, 1, 'sp_5d'),
 (0x06, 24, 4, 'sp_a0'), (0x06, 28, 4, 'sp_a8'),
 (0x07, 0, 11, 'sp_5e_m1'), (0x07, 12, 11, 'sp_60_m1'), (0x07, 24, 1, 'sp_62'), (0x07, 25, 1, 'sp_63'),
 (0x07, 26, 1, 'sp_64'), (0x07, 27, 1, 'sp_65'), (0x07, 28, 1, 'sp_66'), (0x07, 31, 1, 'sp_67'),
 (0x08, 0, 11, 'sp_68_rem'), (0x08, 12, 11, 'sp_68_quot'), (0x08, 24, 3, 'sp_6c_m1'), (0x08, 27, 1, 'sp_70'),
 (0x08, 28, 3, 'sp_6e_m1'), (0x08, 31, 1, 'sp_71'),
 (0x09, 0, 5, 'sp_72'), (0x09, 5, 5, 'sp_73'), (0x09, 11, 1, 'sp_78'), (0x09, 12, 3, 'sp_74_(p)'),
 (0x09, 15, 3, 'sp_76_or_75'), (0x09, 18, 1, 'sp_77_or_7b'),
 (0x09, 19, 1, 'sp_7c'), (0x09, 20, 1, 'sp_7d'), (0x09, 21, 1, 'sp_7e'), (0x09, 22, 1, 'sp_7f'), (0x09, 23, 1, 'sp_80'),
 (0x09, 24, 1, 'sp_81'), (0x09, 25, 1, 'sp_82'), (0x09, 26, 1, 'sp_83'), (0x09, 27, 1, 'sp_84'), (0x09, 28, 1, 'sp_85'),
 (0x09, 29, 1, 'sp_86'), (0x09, 30, 1, 'sp_87'), (0x09, 31, 1, 'sp_88'),
 (0x0a, 0, 16, 'sp_8a'),
 (0x0b, 0, 11, 'sp_8e'), (0x0b, 12, 11, 'sp_90_m1'), (0x0b, 24, 4, 'sp_92_m1'), (0x0b, 30, 1, 'sp_93'), (0x0b, 31, 1, 'sp_94'),
 (0x0c, 0, 32, 'sp_98'), (0x0d, 0, 32, 'sp_9c'), (0x0e, 0, 32, 'sp_a4'), (0x0f, 0, 32, 'sp_ac'),
 (0x10, 0, 32, 'sp_b4'), (0x11, 0, 32, 'sp_b8'),
 (0x12, 0, 10, 'sp_bc_6_m1'), (0x12, 12, 10, 'sp_be_3_m1'), (0x12, 30, 1, 'sp_c1'), (0x12, 31, 1, 'sp_c0'),
 (0x13, 0, 16, 'sp_c4'), (0x13, 16, 16, 'sp_c8_m1'),
 (0x19, 0, 16, 'sp_cc'), (0x19, 16, 8, 'sp_ce'),
 (0x1b, 0, 16, 'sp_8a_b'), (0x1b, 16, 10, 'sp_8c'), (0x1b, 28, 2, 'sp_25_b'), (0x1b, 30, 1, 'sp_26_b'),
 (0x1c, 2, 1, 'sp_cf'), (0x1c, 3, 1, 'sp_7c_b'), (0x1c, 1, 1, 'chroma_flag_2'), (0x1c, 8, 2, 'sp_1b_b'), (0x1c, 10, 1, 'sp_1c_b'),
 (0x1c, 11, 4, 'sp_1d_b'), (0x1c, 16, 7, 'sp_38'), (0x1c, 24, 2, 'sp_28_b'), (0x1c, 28, 2, 'sp_40_b'),
 (0x1d, 0, 11, 'sp_50_quot_b'), (0x1d, 12, 11, 'half_width_8px_m1'), (0x1d, 24, 4, 'sp_55_b'), (0x1d, 28, 4, 'sp_54_b'),
 (0x1e, 0, 20, 'sp_d4_m1'), (0x1e, 24, 5, 'sp_d1'),
 (0x1f, 0, 32, 'sp_d8'),
]
FIELDS = [f for f in FIELDS if f[2] > 0]


def mask(lo, n): return ((1 << n) - 1) << lo if n < 32 else 0xffffffff


def decode(words):
    """{name: value} for the parameter words, from a 112-word list"""
    return {name: (words[w] >> lo) & ((1 << n) - 1) for (w, lo, n, name) in FIELDS}


def covered(word):
    m = 0
    for (w, lo, n, name) in FIELDS:
        if w == word: m |= mask(lo, n)
    return m


def unexplained_bits(lists):
    """bits set in some recorded parameter word that no field covers"""
    out = {}
    for w in range(PARAM_WORDS):
        seen = 0
        for L in lists: seen |= L[w]
        extra = seen & ~covered(w) & 0xffffffff
        if extra: out[w] = extra
    return out


def overlaps():
    bad = []
    for w in range(PARAM_WORDS):
        used = 0
        for (ww, lo, n, name) in FIELDS:
            if ww != w: continue
            m = mask(lo, n)
            if used & m: bad.append((w, name))
            used |= m
    return bad



def encode(fields, words=None):
    """set the named fields into a 112-word list (other bits untouched)"""
    words = list(words) if words else [0] * LIST_WORDS
    byname = {f[3]: f for f in FIELDS}
    for name, val in fields.items():
        w, lo, n, _ = byname[name]
        m = mask(lo, n)
        words[w] = (words[w] & ~m & 0xffffffff) | ((val << lo) & m)
    return words


# ---- a profile: 1920x1080 HEVC, as recorded from the vendor encoder (see the README) ----
# Constant fields (P frame); the meaning of most is the vendor slice-parameter byte, see FIELDS.
PROFILE_1080P = {
    'sp_00': 1, 'sp_01': 1, 'sp_03_m2': 3, 'sp_04_m2': 3, 'sp_05': 3, 'sp_06': 5, 'sp_07_m4': 7, 'sp_08_m4': 1,
    'slice_type_c': 1, 'last_entry': 1, 'width_8px_m1': 239, 'height_8px_m1': 134, 'sp_16': 8, 'sp_17': 8,
    'sp_19': 5, 'sp_1c': 1, 'sp_1d_bit13_forced_1': 5, 'sp_24': 1, 'sp_28': 1, 'sp_34': 1, 'sp_3b': 1,
    'sp_50_zero': 1, 'sp_45': 31, 'sp_46': 63, 'sp_4a': 1, 'sp_58_rem': 59, 'sp_58_quot': 33, 'sp_5e_m1': 59,
    'sp_60_m1': 33, 'sp_67': 1, 'sp_76_or_75': 1, 'sp_77_or_7b': 1, 'sp_83': 1, 'sp_84': 1, 'sp_85': 1, 'sp_86': 1,
    'sp_87': 1, 'sp_88': 1, 'sp_8a': 20480, 'sp_90_m1': 59, 'sp_b8': 0xffffffff, 'sp_8a_b': 20480, 'sp_cf': 1,
    'chroma_flag_2': 1, 'sp_1c_b': 1, 'sp_1d_b': 1, 'sp_28_b': 1, 'half_width_8px_m1': 119, 'sp_d4_m1': 2039,
}
# frame-type dependent fields: slice_type 2 = I (IDR), 1 = P
IDR_FIELDS = {'sp_2d': 0, 'sp_40': 2, 'sp_40_b': 2, 'sp_6c_m1': 7, 'sp_6e_m1': 7, 'sp_bc_6_m1': 1023, 'sp_be_3_m1': 1023}
P_FIELDS = {'sp_2d': 1, 'sp_40': 1, 'sp_40_b': 1, 'sp_6c_m1': 3, 'sp_6e_m1': 3, 'sp_bc_6_m1': 29, 'sp_be_3_m1': 27}

FRAME_PLANE_OFFSETS = {'uv': 0x1fe000, 'mvinfo': 0x2fd000, 'colinfo': 0x300400}	# inside a 0x340000-byte frame buffer
SRC_STRIDE = 1920
REC_PITCH = 0x1e00


def build_list(idr, qp, poc, src_y, src_uv, rec, ref, tables, work, small, stream, stream_alloc=0x7e900,
               stream_offset=0x820, profile=PROFILE_1080P):
    """Input words (0x00-0x3f) of one command list; the status words are left zero.

    idr         True for an IDR picture (no reference), False for a P picture
    qp          slice QP chosen by the rate control (caller's job)
    poc         picture order count in the vendor's units (2 per frame, 0 at an IDR)
    src_y/uv    physical addresses of the NV12 source planes (stride 1920)
    rec, ref    physical addresses of the reconstructed and the reference frame buffer (ref ignored for an IDR)
    tables      the 0x4040-byte buffer, work the 0x6400-byte buffer, small the 256-byte buffer
    stream      physical address of the stream buffer (stream_alloc bytes)
    """
    f = dict(profile)
    f.update(IDR_FIELDS if idr else P_FIELDS)
    f.update({'qp': qp, 'sp_38': qp, 'sp_98': poc, 'sp_9c': max(0, poc - 2), 'sp_ac': max(0, poc - 2),
              'sp_b4': poc - 4 if poc >= 4 else 0xffffffff})
    w = encode(f)
    size = stream_alloc - 0x200
    w[0x20], w[0x21], w[0x22] = src_y, src_uv, SRC_STRIDE
    w[0x23] = tables
    w[0x24], w[0x25], w[0x26], w[0x27] = rec, rec + FRAME_PLANE_OFFSETS['uv'], REC_PITCH, work
    if not idr:
        w[0x28], w[0x29] = ref, ref + FRAME_PLANE_OFFSETS['uv']
        w[0x2c] = ref + FRAME_PLANE_OFFSETS['colinfo']
        w[0x38] = ref + FRAME_PLANE_OFFSETS['mvinfo']
    w[0x2e] = rec + FRAME_PLANE_OFFSETS['colinfo']
    w[0x2f] = small
    w[0x37] = rec + FRAME_PLANE_OFFSETS['mvinfo']
    for base in (0x30, 0x3c):
        w[base], w[base + 1], w[base + 2], w[base + 3] = stream, size, stream_offset, size - 2 * stream_offset
    return w


def replay(frames, bufs=(0x80f395a0, 0x812795a0), tables=0x815b95a0, work=0x80f331a0, small=0x815bd5e0,
           stream=0x80eae100):
    """Rebuild the lists of recorded frames [{'pre': words}] from what the rate control and the
    capture side decide (QP, source addresses); returns the list of mismatching (frame, word)."""
    bad = []; last_idr = 0; prev_rec = None
    for n, fr in enumerate(frames):
        rec_words = fr['pre']
        idr = c_is_idr(rec_words)
        if idr:
            last_idr = n
            rec = prev_rec if prev_rec is not None else bufs[0]
            ref = 0
        else:
            ref = prev_rec
            rec = bufs[1] if prev_rec == bufs[0] else bufs[0]
        qp = decode(rec_words)['qp']
        w = build_list(idr, qp, 2 * (n - last_idr), rec_words[0x20], rec_words[0x21], rec, ref, tables, work, small, stream)
        for i in range(0x40):
            if w[i] != rec_words[i]: bad.append((n, i, w[i], rec_words[i]))
        prev_rec = rec
    return bad


def c_is_idr(words):
    return decode(words)['sp_40'] == 2


if __name__ == '__main__':
    with open(sys.argv[1]) as fh:
        frames = json.load(fh)
    lists = [f['pre'] for f in frames]
    print('overlaps:', overlaps())
    for w, b in unexplained_bits(lists).items():
        print('word 0x%02x: unexplained bits %08x' % (w, b))
    bad = replay(frames)
    print('replay: %d frames, %d mismatching words' % (len(frames), len(bad)))
    for b in bad[:10]:
        print('  frame %d word 0x%02x: built %08x recorded %08x' % b)
