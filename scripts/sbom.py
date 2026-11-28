#!/usr/bin/env python3
"""Software bill of materials of a TC100 build: sbom.cdx.json (CycloneDX 1.5) and sbom.md (readable table).

  python3 scripts/sbom.py --show-info base-rootfs/show-info.json --out output/sbom

Inputs (nothing is hardcoded about a Buildroot or kernel version, they are read from here):
  --show-info FILE   `make show-info` JSON of the Buildroot base build (optional: without it the base system is
                     listed as "not available" in the notes and the rest is still written)
  --pins FILE        .github/ci-pins.sh (LINUX_TAG, LINUX_COMMIT, firmware, standalone Mbed TLS, Buildroot tag)
  --root DIR         repository root (VERSION, src/, patches/kernel-6.6/series, v3/musl/build-musl.sh)
  --commit SHA       git commit of the build (default: git rev-parse HEAD, else "unknown")
  --out PREFIX       writes PREFIX.cdx.json and PREFIX.md (default ./sbom -> sbom.cdx.json, sbom.md)

Nothing here runs on the camera. The files carry no local path, no user name and no secret: only names, versions,
licences, public source URLs and the repository-relative place of each component.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# free programs of src/: directory -> (name, kind, where in the image, description). Directories not listed here
# (musl.mk, ssp-freestanding.h are files; h265enc and jpegenc are research and host tools; webui is handled apart)
# are not components of the image.
FREE_PROGRAMS = {
    'tc100rtsp':  ('tc100_rtsp', 'application', 'stack: tc100test/tc100_rtsp', 'RTSP server, free H.264/H.265 encoder (src/h265enc/freeenc.h) linked in'),
    'httpfront':  ('httpfront', 'application', 'stack: tc100test/httpfront', 'web front (freestanding, no libc)'),
    'mdnsd':      ('tc100-mdnsd', 'application', 'stack: tc100test/tc100-mdnsd', 'mDNS responder (freestanding)'),
    'mqttd':      ('tc100-mqttd', 'application', 'stack: tc100test/tc100-mqttd', 'MQTT client daemon'),
    'onvifd':     ('tc100-onvifd', 'application', 'stack: tc100test/tc100-onvifd', 'ONVIF daemon'),
    'supervisord': ('tc100-supervisord', 'application', 'stack: tc100test/tc100-supervisord', 'service supervisor'),
    'logfwd':     ('tc100-logfwd', 'application', 'stack: bin/tc100-logfwd', 'log forwarder'),
    'rwconf':     ('rwconf', 'application', 'stack: bin/rwconf', 'settings reader/writer'),
    'netacl':     ('libnetacl', 'library', 'stack: lib/libnetacl-musl.so', 'accept/bind filter preloaded into busybox telnetd/ftpd'),
    'ispflip':    ('isp_flip', 'application', 'stack: bin/isp_flip', 'image flip helper (freestanding)'),
    'libakuio':   ('libakuio', 'library', 'linked into tc100_rtsp', 'user-space access to the encoder kernel driver'),
    'whep':       ('tc100-whep', 'application', 'base image: /usr/bin/tc100-whep', 'WebRTC (WHEP) gateway, built by Buildroot'),
    'httpsd':     ('tc100-httpsd', 'application', 'base image: /usr/bin/tc100-httpsd', 'Low-CPU native HTTPS reverse proxy, built by Buildroot'),
}

SPDX_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.+-]*$')


def read(path):
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        return f.read()


def parse_pins(path):
    """KEY=value lines of ci-pins.sh (no shell is run); $NAME references to earlier keys are expanded"""
    pins = {}
    for line in read(path).splitlines():
        m = re.match(r'^([A-Z][A-Z0-9_]*)=(.*)$', line)
        if not m:
            continue
        v = m.group(2).strip().strip('"').strip("'")
        v = re.sub(r'\$\{?([A-Z][A-Z0-9_]*)\}?', lambda k: pins.get(k.group(1), ''), v)
        pins[m.group(1)] = v
    return pins


def git_commit(root):
    try:
        out = subprocess.run(['git', '-C', root, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20)
        c = out.stdout.strip()
        if out.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}', c):
            return c
    except (OSError, subprocess.SubprocessError):
        pass
    return 'unknown'


def load_show_info(path):
    """the JSON object of `make show-info` (leading make noise is skipped); None when missing or unreadable"""
    if not path or not os.path.isfile(path):
        return None
    t = read(path)
    i = t.find('{')
    if i < 0:
        return None
    try:
        d = json.loads(t[i:])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def kernel_version(tag):
    v = tag[1:] if tag.startswith('v') else tag
    return v + '.0' if re.fullmatch(r'\d+\.\d+', v) else v


def licences(text):
    out = []
    for part in re.split(r',\s*', text or ''):
        part = part.strip()
        if part:
            out.append(part)
    return out


def lic_objects(names):
    return [{'license': {'name': n}} for n in names]


def purl_for(uris, name, version):
    """pkg:github/... only when the source is a GitHub repository; nothing invented otherwise"""
    for u in uris or []:
        m = re.search(r'github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/|$)', u)
        if m and version:
            return 'pkg:github/%s/%s@%s' % (m.group(1).lower(), m.group(2).lower(), version)
    return None


def clean_url(u):
    """show-info URIs look like 'http+https://host/path' or 'git+https://...': keep the scheme after the '+'"""
    m = re.match(r'^(?:[a-z]+\+)?(https?|git|ftp)(?:\+(https?))?://(.*)$', u or '')
    if not m:
        return None
    scheme = m.group(2) or m.group(1)
    if scheme == 'git':
        scheme = 'https'
    return '%s://%s' % (scheme, m.group(3))


def buildroot_components(info):
    comps = []
    for key in sorted(info):
        p = info[key]
        if not isinstance(p, dict) or p.get('type') not in (None, 'target'):
            continue
        if p.get('virtual') or p.get('type') == 'rootfs':
            continue
        name = p.get('name') or key
        ver = p.get('version')
        if not ver:
            continue
        srcs = []
        for d in p.get('downloads') or []:
            for u in d.get('uris') or []:
                cu = clean_url(u)
                if cu and cu not in srcs:
                    srcs.append(cu)
        comps.append({
            'name': name, 'version': str(ver), 'kind': 'library', 'origin': 'buildroot',
            'licenses': licences(p.get('licenses')), 'sources': srcs, 'cpe': p.get('cpe-id') or None,
            'where': 'base image (Buildroot): rootfs.cpio.gz',
            'purl': purl_for(srcs, name, str(ver)),
        })
    return comps


def musl_info(root):
    p = os.path.join(root, 'v3', 'musl', 'build-musl.sh')
    if not os.path.isfile(p):
        return None
    t = read(p)
    v = re.search(r'(?m)^VER=(\S+)', t)
    u = re.search(r'(?m)^URL=\$\{MUSL_URL:-(\S+?)\}', t)
    if not v:
        return None
    url = (u.group(1) if u else '').replace('$VER', v.group(1))
    return v.group(1), url


def npm_esbuild(root):
    p = os.path.join(root, 'src', 'webui', 'package-lock.json')
    try:
        d = json.loads(read(p))
        return d['packages']['node_modules/esbuild']['version']
    except (OSError, ValueError, KeyError):
        return None


def build_components(root, pins, info, commit, version):
    comps = []
    br = buildroot_components(info) if info else []
    br_names = {c['name'] for c in br}

    tag = pins.get('LINUX_TAG', '')
    if tag:
        kv = kernel_version(tag)
        patches = sorted(os.path.basename(f) for f in glob.glob(os.path.join(root, 'patches', 'kernel-6.6', 'series', '[0-9]*.patch')))
        comps.append({
            'name': 'linux', 'version': kv, 'kind': 'operating-system', 'origin': 'kernel',
            'licenses': ['GPL-2.0-only WITH Linux-syscall-note'],
            'sources': [u for u in (pins.get('LINUX_URLS') or '').split() if u.startswith('http')][:1],
            'cpe': 'cpe:2.3:o:linux:linux_kernel:%s:*:*:*:*:*:*:*' % kv, 'purl': None,
            'where': 'kernel partition: oipc.img (uImage)', 'patches': patches,
            'props': {'tc100:upstream-tag': tag, 'tc100:upstream-commit': pins.get('LINUX_COMMIT', '')},
        })
    if pins.get('RTL8188FU_FW_SHA256'):
        comps.append({
            'name': 'rtl8188fufw', 'version': pins.get('LINUX_FIRMWARE_TAG', 'unknown'), 'kind': 'firmware', 'origin': 'firmware',
            'licenses': ['Redistributable firmware (linux-firmware WHENCE)'],
            'sources': ['https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git'],
            'cpe': None, 'purl': None, 'where': 'embedded in the kernel image (oipc.img)',
            'hash': pins['RTL8188FU_FW_SHA256'], 'props': {'tc100:file': 'rtlwifi/rtl8188fufw.bin'},
        })
    m = musl_info(root)
    if m:
        comps.append({
            'name': 'musl', 'version': m[0], 'kind': 'library', 'origin': 'musl',
            'licenses': ['MIT'], 'sources': [m[1]] if m[1] else [],
            'cpe': 'cpe:2.3:a:musl-libc:musl:%s:*:*:*:*:*:*:*' % m[0], 'purl': None,
            'where': 'linked into the free programs (v3/musl/build-musl.sh); the image carries the libc of the Buildroot musl package',
            'scope': 'excluded',
        })
    if pins.get('MBEDTLS_VERSION'):
        comps.append({
            'name': 'mbedtls-standalone', 'version': pins['MBEDTLS_VERSION'], 'kind': 'library', 'origin': 'pin',
            'licenses': ['Apache-2.0 OR GPL-2.0-or-later'], 'sources': [pins.get('MBEDTLS_URL', '')] if pins.get('MBEDTLS_URL') else [],
            'cpe': 'cpe:2.3:a:arm:mbed_tls:%s:*:*:*:*:*:*:*' % pins['MBEDTLS_VERSION'], 'purl': None,
            'where': 'host and ARM test builds of tc100-whep only (tests/docker); the image uses the Buildroot mbedtls package',
            'hash': pins.get('MBEDTLS_SHA256'), 'scope': 'excluded',
        })
    if pins.get('BUILDROOT_TAG'):
        comps.append({
            'name': 'buildroot', 'version': pins['BUILDROOT_TAG'], 'kind': 'application', 'origin': 'pin',
            'licenses': ['GPL-2.0-or-later'], 'sources': ['https://github.com/buildroot/buildroot'],
            'cpe': None, 'purl': None, 'where': 'build system of the base image (not in the image)', 'scope': 'excluded',
            'props': {'tc100:upstream-commit': pins.get('BUILDROOT_COMMIT', '')},
        })
    comps.extend(br)

    for d in sorted(FREE_PROGRAMS):
        name, kind, where, desc = FREE_PROGRAMS[d]
        if not os.path.isdir(os.path.join(root, 'src', d)) or name in br_names:
            continue
        comps.append({
            'name': name, 'version': '%s+%s' % (version, commit[:12]) if commit != 'unknown' else version, 'kind': kind,
            'origin': 'free', 'licenses': ['GPL-2.0-only'], 'sources': [], 'cpe': None, 'purl': None,
            'where': where, 'desc': desc, 'props': {'tc100:source-dir': 'src/' + d, 'tc100:git-commit': commit},
        })
    if os.path.isdir(os.path.join(root, 'www')) or os.path.isdir(os.path.join(root, 'src', 'webui')):
        comps.append({
            'name': 'tc100-webui', 'version': '%s+%s' % (version, commit[:12]) if commit != 'unknown' else version,
            'kind': 'application', 'origin': 'free', 'licenses': ['GPL-2.0-only'], 'sources': [],
            'cpe': None, 'purl': None, 'where': 'stack: web UI (www/, built in, minified)',
            'desc': 'V3 web UI, no third-party runtime library', 'props': {'tc100:source-dir': 'www'},
        })
    ev = npm_esbuild(root)
    if ev:
        comps.append({
            'name': 'esbuild', 'version': ev, 'kind': 'application', 'origin': 'npm',
            'licenses': ['MIT'], 'sources': ['https://github.com/evanw/esbuild'], 'cpe': None,
            'purl': 'pkg:npm/esbuild@%s' % ev, 'where': 'build tool of the web UI minification (src/webui/package-lock.json), not in the image',
            'scope': 'excluded',
        })
    return comps


def bom_ref(c, seen):
    base = '%s-%s@%s' % (c['origin'], c['name'], c['version'])
    base = re.sub(r'[^A-Za-z0-9_.@+:-]', '_', base)
    ref, n = base, 2
    while ref in seen:
        ref = '%s~%d' % (base, n)
        n += 1
    seen.add(ref)
    return ref


def to_cyclonedx(comps, version, commit, notes):
    seen = set()
    out = []
    for c in comps:
        ref = bom_ref(c, seen)
        c['bom-ref'] = ref
        o = {'type': c['kind'], 'bom-ref': ref, 'name': c['name'], 'version': c['version'],
             'scope': c.get('scope', 'required')}
        if c.get('desc'):
            o['description'] = c['desc']
        if c['licenses']:
            o['licenses'] = lic_objects(c['licenses'])
        if c.get('cpe'):
            o['cpe'] = c['cpe']
        if c.get('purl'):
            o['purl'] = c['purl']
        if c.get('hash') and re.fullmatch(r'[0-9a-f]{64}', c['hash']):
            o['hashes'] = [{'alg': 'SHA-256', 'content': c['hash']}]
        refs = [{'type': 'distribution', 'url': u} for u in c['sources'] if u.startswith('http')]
        if refs:
            o['externalReferences'] = refs
        props = [{'name': 'tc100:origin', 'value': c['origin']}, {'name': 'tc100:where', 'value': c['where']}]
        for k, v in sorted((c.get('props') or {}).items()):
            if v:
                props.append({'name': k, 'value': v})
        for p in c.get('patches') or []:
            props.append({'name': 'tc100:patch', 'value': p})
        o['properties'] = props
        out.append(o)
    epoch = os.environ.get('SOURCE_DATE_EPOCH', '')
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(epoch) if epoch.isdigit() else time.time()))
    serial = uuid.uuid5(uuid.NAMESPACE_URL, 'tc100:%s:%s' % (version, commit))
    meta_props = [{'name': 'tc100:git-commit', 'value': commit}]
    for n in notes:
        meta_props.append({'name': 'tc100:note', 'value': n})
    return {
        '$schema': 'http://cyclonedx.org/schema/bom-1.5.schema.json',
        'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'serialNumber': 'urn:uuid:%s' % serial, 'version': 1,
        'metadata': {
            'timestamp': ts,
            'tools': {'components': [{'type': 'application', 'name': 'tc100-sbom', 'version': '1', 'description': 'scripts/sbom.py'}]},
            'component': {'type': 'firmware', 'bom-ref': 'tc100-firmware', 'name': 'tc100-firmware', 'version': version,
                          'description': 'Free firmware for the TECKIN TC100 camera (Anyka AK3918EV300)'},
            'properties': meta_props,
        },
        'components': out,
        'dependencies': [{'ref': 'tc100-firmware', 'dependsOn': [c['bom-ref'] for c, o in zip(comps, out) if o['scope'] == 'required']}],
    }


def md_cell(s):
    return str(s).replace('|', '\\|').replace('\n', ' ')


def to_markdown(comps, version, commit, notes):
    L = ['# Software bill of materials: TC100 firmware %s' % version, '',
         'Commit `%s`. Generated by `scripts/sbom.py` (CycloneDX 1.5 in `sbom.cdx.json`).' % commit, '']
    if notes:
        L += ['Notes:'] + ['- ' + n for n in notes] + ['']
    groups = [('In the image', [c for c in comps if c.get('scope', 'required') == 'required']),
              ('Build-time only (not in the image)', [c for c in comps if c.get('scope') == 'excluded'])]
    for title, cs in groups:
        L += ['## %s (%d)' % (title, len(cs)), '', '| Component | Version | Licence | Source | Where |', '|---|---|---|---|---|']
        for c in cs:
            src = c['sources'][0] if c['sources'] else ('this repository' if c['origin'] == 'free' else '')
            L.append('| %s | %s | %s | %s | %s |' % (md_cell(c['name']), md_cell(c['version']), md_cell('; '.join(c['licenses']) or 'unknown'),
                                                    md_cell(src), md_cell(c['where'])))
        L.append('')
    k = [c for c in comps if c.get('patches')]
    if k:
        L += ['## Kernel patch series (%d patches on %s)' % (len(k[0]['patches']), k[0]['props'].get('tc100:upstream-tag', '')), '']
        L += ['- `%s`' % p for p in k[0]['patches']] + ['']
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--show-info')
    ap.add_argument('--pins')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--commit')
    ap.add_argument('--out', default='sbom')
    a = ap.parse_args(argv)
    root = a.root
    pins = parse_pins(a.pins or os.path.join(root, '.github', 'ci-pins.sh'))
    vf = os.path.join(root, 'VERSION')
    version = read(vf).splitlines()[0].strip() if os.path.isfile(vf) and read(vf).strip() else 'unknown'
    commit = a.commit or git_commit(root)
    info = load_show_info(a.show_info)
    notes = []
    if info is None:
        notes.append('Buildroot show-info not available: the base system packages are NOT listed in this SBOM.')
    comps = build_components(root, pins, info, commit, version)
    bom = to_cyclonedx(comps, version, commit, notes)
    d = os.path.dirname(a.out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out + '.cdx.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(bom, f, indent=2, sort_keys=False)
        f.write('\n')
    with open(a.out + '.md', 'w', encoding='utf-8', newline='\n') as f:
        f.write(to_markdown(comps, version, commit, notes) + '\n')
    print('sbom: %d components -> %s.cdx.json, %s.md' % (len(comps), a.out, a.out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
