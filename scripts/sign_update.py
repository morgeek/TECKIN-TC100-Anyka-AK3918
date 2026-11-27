#!/usr/bin/env python3
"""Owner's tool: Ed25519 signing of the TC100 update packages (docs/linux-port/upgrade-3.2/sign.md).

  sign_update.py keygen PREFIX            make PREFIX.key (PRIVATE, keep it off the repository) and PREFIX.pub
  sign_update.py sign KEY PACKAGE.tar [-o OUT.tar] [--force]
                                          check SHA256SUMS against the files of a CI-built package, sign it, write
                                          PACKAGE.tar with SHA256SUMS.sig added (default: PACKAGE-signed.tar)
  sign_update.py verify PACKAGE.tar PUB_OR_DIR...
                                          what the camera will do: signature, then every file against SHA256SUMS

The signature tool is src/sigcheck (C, Monocypher), compiled here with the host C compiler (cc, gcc or clang).
The private key never leaves the machine that runs `keygen`; the CI signs nothing.
"""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'sigcheck'
NAMES = ('VERSION', 'stack.sqfs', 'c66.img', 'c66rd.gz', 'MD5SUMS')
SUMS, SIG = 'SHA256SUMS', 'SHA256SUMS.sig'


def build_tool(workdir):
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        sys.exit('no C compiler (cc, gcc or clang) found: install one to build the signing tool')
    exe = Path(workdir) / ('tc100-sigcheck-host' + ('.exe' if os.name == 'nt' else ''))
    srcs = [str(SRC / n) for n in ('sigcheck.c', 'monocypher.c', 'monocypher-ed25519.c')]
    subprocess.run([cc, '-O2', '-std=gnu11', '-DSIGCHECK_HOST', '-o', str(exe)] + srcs, check=True)
    return str(exe)


def read_package(path):
    """{name: (TarInfo, bytes)} in archive order; plain files only, no path tricks."""
    out = {}
    with tarfile.open(path, 'r:') as t:
        for m in t.getmembers():
            if not m.isreg() or '/' in m.name or m.name in ('', '.', '..'):
                sys.exit('%s: unexpected member %r (plain files only)' % (path, m.name))
            out[m.name] = (m, t.extractfile(m).read())
    return out


def check_sums(pkg):
    """SHA256SUMS names exactly NAMES, each once, with the right sum; returns the problems."""
    if SUMS not in pkg:
        return ['%s is missing from the package' % SUMS]
    seen, bad = {}, []
    for line in pkg[SUMS][1].decode('ascii', 'replace').splitlines():
        if not line.strip():
            continue
        parts = line.split('  ', 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            bad.append('malformed line %r' % line)
            continue
        seen[parts[1]] = seen.get(parts[1], 0) + 1
        if parts[1] not in NAMES or parts[1] not in pkg:
            bad.append('%s is not a file of the package' % parts[1])
        elif hashlib.sha256(pkg[parts[1]][1]).hexdigest() != parts[0].lower():
            bad.append('%s does not match its sum' % parts[1])
    for n in NAMES:
        if seen.get(n) != 1:
            bad.append('%s is not listed exactly once' % n)
    return bad


def cmd_keygen(a):
    with tempfile.TemporaryDirectory() as w:
        tool = build_tool(w)
        r = subprocess.run([tool, 'keygen', a.prefix], capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr.strip() or 'keygen failed')
    kid = r.stdout.strip()
    print('key id %s\n  private: %s.key  (KEEP IT PRIVATE: never in the repository, in a chat or in a cloud folder; make a backup)\n'
          '  public : %s.pub  (copy it to v3/install/update-keys/%s.pub and commit it)' % (kid, a.prefix, a.prefix, kid))


def cmd_sign(a):
    pkg = read_package(a.package)
    if SIG in pkg and not a.force:
        sys.exit('the package is already signed (--force to sign again)')
    pkg.pop(SIG, None)
    problems = check_sums(pkg)
    if problems:
        sys.exit('not signing, the package is not consistent:\n  ' + '\n  '.join(problems))
    out = a.output or str(Path(a.package).with_name(Path(a.package).stem + '-signed.tar'))
    with tempfile.TemporaryDirectory() as w:
        tool = build_tool(w)
        sums = Path(w) / SUMS
        sums.write_bytes(pkg[SUMS][1])
        r = subprocess.run([tool, 'sign', a.key, str(sums)], capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr.strip() or 'signing failed')
        sig = r.stdout.encode('ascii')
        pub = Path(a.key).with_suffix('.pub')
        if pub.exists():	# own check before the package leaves this machine
            (Path(w) / SIG).write_bytes(sig)
            v = subprocess.run([tool, 'verify', str(sums), str(Path(w) / SIG), str(pub)], capture_output=True, text=True)
            if v.returncode:
                sys.exit('the new signature does not verify against %s: %s' % (pub, v.stdout.strip()))
    # same members, same order, same times and modes as the CI package, then the signature (reproducible: root-owned)
    with tarfile.open(out, 'w:', format=tarfile.GNU_FORMAT) as t:
        for name, (m, data) in list(pkg.items()) + [(SIG, (None, sig))]:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), (m.mode if m else 0o644)
            ti.mtime = m.mtime if m else max(x[0].mtime for x in pkg.values())
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ''
            t.addfile(ti, io.BytesIO(data))
    print('signed package: %s (%s)' % (out, sig.decode().split()[1]))


def cmd_verify(a):
    pkg = read_package(a.package)
    if SIG not in pkg:
        sys.exit('unsigned: no %s in the package' % SIG)
    with tempfile.TemporaryDirectory() as w:
        tool = build_tool(w)
        (Path(w) / SUMS).write_bytes(pkg.get(SUMS, (None, b''))[1])
        (Path(w) / SIG).write_bytes(pkg[SIG][1])
        r = subprocess.run([tool, 'verify', str(Path(w) / SUMS), str(Path(w) / SIG)] + a.keys, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        sys.exit(1)
    bad = check_sums(pkg)
    if bad:
        sys.exit('signature ok but the files do not match:\n  ' + '\n  '.join(bad))
    print('every file matches SHA256SUMS')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest='cmd', required=True)
    k = s.add_parser('keygen'); k.add_argument('prefix'); k.set_defaults(f=cmd_keygen)
    g = s.add_parser('sign'); g.add_argument('key'); g.add_argument('package'); g.add_argument('-o', '--output')
    g.add_argument('--force', action='store_true'); g.set_defaults(f=cmd_sign)
    v = s.add_parser('verify'); v.add_argument('package'); v.add_argument('keys', nargs='+'); v.set_defaults(f=cmd_verify)
    a = p.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
