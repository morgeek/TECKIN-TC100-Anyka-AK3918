#!/usr/bin/env python3
"""Every akuio_* symbol imported by the vendor media libraries must be exported
by the free libakuio (src/libakuio).  Usage: check_akuio_symbols.py VENDOR_LIB_DIR [OUR_LIB]"""
import subprocess, sys, os

def nm(path, undefined):
    out = subprocess.run(['nm', '-D'] + (['--undefined-only'] if undefined else ['--defined-only']) + [path],
                         capture_output=True, text=True).stdout
    return {l.split()[-1] for l in out.splitlines() if 'akuio' in l}

def main(libdir, ours):
    have = nm(ours, False)
    bad = 0
    for f in sorted(os.listdir(libdir)):
        if not f.endswith('.so') or f == 'libakuio.so':
            continue
        need = nm(os.path.join(libdir, f), True)
        miss = need - have
        if need:
            print('%-22s needs %d, missing %s' % (f, len(need), sorted(miss) or 'none'))
        bad += len(miss)
    return 1 if bad else 0

if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, '..', 'src/libakuio/libakuio.so')))
