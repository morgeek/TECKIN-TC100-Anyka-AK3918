#!/usr/bin/env python3
"""Check the table block written by `jpegenc --dry` (out.jpg.tables) against jpeg_hw_tables.py.
Usage: check_tables_block.py out.jpg.tables [quality]"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jpeg_hw_tables as t

blk = open(sys.argv[1], 'rb').read()
Q = int(sys.argv[2]) if len(sys.argv) > 2 else 35
ok = True
def chk(name, cond):
    global ok
    print('%-34s %s' % (name, 'ok' if cond else 'FAILED')); ok &= cond
ql, qc = t.quant_zigzag(Q, t.LUMA), t.quant_zigzag(Q, t.CHROMA)
chk('luma quant (zigzag) @0x000', list(blk[0:64]) == ql)
chk('chroma quant (zigzag) @0x040', list(blk[64:128]) == qc)
chk('luma reciprocals @0x080', list(struct.unpack('<64H', blk[0x80:0x100])) == t.quant_recip(ql))
chk('chroma reciprocals @0x100', list(struct.unpack('<64H', blk[0x100:0x180])) == t.quant_recip(qc))
def words(off, n): return list(struct.unpack('<%dI' % n, blk[off:off + 4 * n]))
chk('AC luma @0x1c8', words(0x1c8, 162) == t.huffman_words(*t.AC_LUMA, True))
chk('DC luma @0x450', words(0x450, 12) == t.huffman_words(*t.DC_LUMA, False))
chk('AC chroma @0x480', words(0x480, 162) == t.huffman_words(*t.AC_CHROMA, True))
chk('DC chroma @0x708', words(0x708, 12) == t.huffman_words(*t.DC_CHROMA, False))
chk('tail 0x738..0x800 zero', not any(blk[0x738:0x800]))
chk('size 0x800', len(blk) == 0x800)
sys.exit(0 if ok else 1)
