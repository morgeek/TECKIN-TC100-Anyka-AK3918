#!/usr/bin/env python3
"""Front -> back wiring, end to end, static (item 57 of docs/linux-port/a-faire-implementeur.md).

Every endpoint the pages call is extracted from: www/*.html, www/cgi-bin/*.cgi (pages printed by CGIs, inline
scripts), www/scripts/*.js and src/webui/index/*.js (fetch, XMLHttpRequest.open, csrfFetch, form action=, href=,
data-target= / data-checked= / data-unchecked=: all of them are "cgi-bin/<name>.cgi?..." strings). Then:

  1. the CGI file exists (and a data-target to a page points at a page that exists);
  2. a literal cmd= value has a branch in the CGI (for action.cgi: it is in the dispatch table AND the group file
     scripts/action.d/<group>.sh has a branch);
  3. every other query parameter the page sends is read by the CGI;
  4. CSRF: a call that the CGI refuses without the per-boot token (action.cgi csrf_check on every command that is
     not in its read-only list, whatever the method; mutation_guard / csrf_guard POST checks in the other CGIs;
     update.cgi and flashinstall.cgi POSTs) must go through csrfFetch / X-CSRF-Token / a helper that adds it, and
     with POST where the CGI demands POST.

A URL built at run time cannot be resolved statically: it goes in DYNAMIC below, with the reason and the commands
it can produce (those are checked like literal ones). Run: python3 -m unittest tests.test_wiring_e2e
"""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / 'www'
CGI = WWW / 'cgi-bin'
ACTION_D = ROOT / 'scripts' / 'action.d'

REF = re.compile(r"cgi-bin/([A-Za-z_]+)\.cgi([^\"'`\s<>)\\]*)")
# a token that makes the client send the per-boot CSRF token (csrfFetch adds it, the others are page-local helpers)
CSRF_AWARE = re.compile(r"csrfFetch|X-CSRF-Token|csrf|\bcf\(|postForm", re.I)

# Dynamic URLs: (file, cgi, extracted query) -> (reason, commands it can produce). Commands are checked like literals.
DYNAMIC = {
    ('settings.html', 'action', '?cmd='): (
        'cmd chosen with a ternary on the button id (btnRecEject / btnRecResume)',
        ['local_rec_eject', 'local_rec_resume']),
    ('80-camera-controls.js', 'scripts', '?cmd='): (
        'cmd is the toggle state: start or stop (service switch of the main page)', ['start', 'stop']),
    ('index.bundle.min.js', 'scripts', '?cmd='): ('minified copy of 80-camera-controls.js', ['start', 'stop']),
    ('scripts.bundle.min.js', 'scripts', '?cmd='): ('start or stop from the service state (dataset.target)',
                                                     ['start', 'stop']),
    ('hardware.html', 'action', '?cmd='): (
        'cmd(name) of the hardware test panel: one of the LED / IR / IR-cut buttons',
        ['front_led_on', 'front_led_off', 'red_led_on', 'red_led_off', 'ir_led_on', 'ir_led_off', 'ir_cut_on',
         'ir_cut_off']),
    ('logs.html', 'action', '?cmd='): ('showlog, or clearlog when the Clear button is used', ['showlog', 'clearlog']),
    ('settings.html', 'update', '?cmd='): ('run(cmd) of the update box: install or discard', ['install', 'discard']),
    ('settings.html', 'flashinstall', '?cmd='): ('post(cmd): install only (the 2.x prepare step was removed)',
                                                 ['install']),
    ('95-settings-page.js', 'action', '?cmd='): ('post(command) of the presence card: the two callers pass a literal name',
                                                 ['presence_profiles_save', 'presence_apply']),
    ('index.bundle.min.js', 'action', '?cmd='): ('minified copy of 95-settings-page.js', ['presence_profiles_save', 'presence_apply']),
    ('settings.html', 'sounds', '?'): ('post(q) of the Sounds card builds the query: play, delete, boot, upload',
                                       ['play', 'delete', 'boot', 'upload']),
}

# Calls that reach a CGI without the token on purpose (the CGI does not ask for it for that command).
NO_TOKEN_OK = {
    # wizard.cgi enforces the token itself on its own POST; pre-login first run, see wizard.cgi csrf block
    'wizard',
}


# Keys the web UI / HTTP API writes (rewrite_config in action.cgi, scripts/action.d, the CGIs) that the configuration
# export does not carry, with the reason. A new key must either get a row in config_exchange.cgi or be listed here.
NOT_EXPORTED = {
    ('boot.conf', 'ENABLE_NTP'): 'first-run wizard only; the NTP server itself is exported (ntp_srv.conf)',
    ('boot.conf', 'SETUP_WIZARD_DONE'): 'wizard state marker, not a setting',
    ('boot.conf', 'SETUP_WIZARD_EPOCH'): 'wizard state marker (written, informational only: nothing reads it)',
    ('boot.conf', 'ENABLE_CROND'): 'set by the reboot-schedule command itself; the schedule is exported',
    ('boot.conf', 'LOW_CPU_PROFILE'): 'derived by the performance / client profile commands (API), not a setting of its own',
    ('boot.conf', 'LOW_RAM_PROFILE'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'LOW_CPU_DISABLE_AUDIO'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'LOW_CPU_DISABLE_JPEG'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'LOW_CPU_DISABLE_MOTION'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'LOW_CPU_DISABLE_OSD'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'LOW_CPU_DISABLE_SUBSTREAM'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'MEM_GUARD_ENABLE'): 'derived by set_performance_profile (API)',
    ('boot.conf', 'MEM_GUARD_WARN_KB'): 'API-only tuning (set_advanced_tuning)',
    ('boot.conf', 'MEM_GUARD_CRITICAL_KB'): 'API-only tuning (set_advanced_tuning)',
    ('boot.conf', 'MEM_GUARD_INTERVAL_SECONDS'): 'API-only tuning (set_advanced_tuning)',
    ('rtspserver.conf', 'USERNAME'): 'camera credentials: exported as secrets.camera_password (user.pwd)',
    ('rtspserver.conf', 'USERPASSWORD'): 'camera credentials: exported as secrets.camera_password (user.pwd)',
}
NOT_EXPORTED_MQTT = (
    'MQTT_CLIENT_ID MQTT_QOS MQTT_TOPIC_COMMAND MQTT_COMMAND_REPEAT_WINDOW_SECONDS MQTT_COMMAND_WAIT_SECONDS '
    'MQTT_HEALTH_INTERVAL_SECONDS MQTT_HEALTH_SLOW_CACHE_TTL_SECONDS MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS '
    'MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER POWER_ESTIMATE_ENABLE '
    'POWER_ESTIMATE_BASE_MW POWER_ESTIMATE_CPU_SCALE_MW POWER_ESTIMATE_IR_LED_MW POWER_SENSOR_PATH').split()
for _k in NOT_EXPORTED_MQTT:
    NOT_EXPORTED[('mqtt.conf', _k)] = 'advanced MQTT tuning, API-only fields of set_mqtt_config (docs/api.md), not in Settings'


def read(p):
    return p.read_text(errors='ignore')


def sources():
    files = list(WWW.glob('*.html')) + list(CGI.glob('*.cgi')) + list((WWW / 'scripts').glob('*.js')) \
        + list((ROOT / 'src/webui/index').glob('*.js'))
    return sorted(files)


def action_table():
    """cmd -> group, from the dispatch table of action.cgi."""
    a = read(CGI / 'action.cgi')
    i = a.index('# Each command lives in scripts/action.d')
    j = a.index('*) _action_group= ;;', i)
    table = {}
    for m in re.finditer(r'^\s+([A-Za-z0-9_|.-]+)\)\s*\n\s+_action_group=([a-z]+)', a[i:j], re.M):
        for c in m.group(1).split('|'):
            table[c] = m.group(2)
    return table, a


def action_readonly(a):
    m = re.search(r'case "\$F_cmd" in\n\s+([A-Za-z0-9_|]+)\) ;;\n\s+\*\) csrf_check', a)
    assert m, 'action.cgi read-only list not found'
    return set(m.group(1).split('|'))


def label_before(lines, idx):
    """case label that opens the branch containing line idx (nearest `label)` line above, same indentation or less)."""
    for k in range(idx, -1, -1):
        m = re.match(r'\s*([A-Za-z0-9_|*"$ -]+)\)(\s|$)', lines[k])
        if m:
            return [x.strip('" ') for x in m.group(1).split('|')]
    return []


def mutating_cmds(cgi):
    """Commands of a CGI that refuse without POST + token (mutation_guard) -> set, or 'all' (whole CGI)."""
    text = read(CGI / (cgi + '.cgi'))
    if cgi == 'upload_audio':
        return 'all'
    if cgi in ('update', 'flashinstall'):
        return set(re.findall(r'^POST:([a-z]+)', text, re.M))
    lines = text.split('\n')
    out = set()
    for i, ln in enumerate(lines):
        if 'mutation_guard' in ln and not ln.lstrip().startswith(('#', 'mutation_guard() {')):
            m = re.match(r'\s*([A-Za-z0-9_|]+)\)', ln)
            out |= set(m.group(1).split('|')) if m else set(label_before(lines, i))
    return out


def handler_text(cgi):
    t = read(CGI / (cgi + '.cgi'))
    if cgi == 'action':
        t += ''.join(read(p) for p in ACTION_D.glob('*.sh'))
    return t


def handles(text, cmd):
    if re.search(r'(^|[\s|(:"\'])' + re.escape(cmd) + r'(\|[^)\n]*)?\)', text, re.M):
        return True
    return bool(re.search(r'=\s*"?' + re.escape(cmd) + r'"?\s*\]|"' + re.escape(cmd) + r'"', text))


def calls():
    """Yield dicts for every reference to a CGI found in the sources."""
    for f in sources():
        s = read(f)
        for m in REF.finditer(s):
            q = m.group(2)
            cmd = None
            dyn = False
            cm = re.search(r'[?&]cmd=(.?)', q)
            if cm:
                lit = re.match(r'[?&]cmd=([A-Za-z0-9_-]+)', q[cm.start():])
                if lit and not (q[cm.start():].endswith(lit.group(1)) and s[m.end():m.end() + 1] in '$%'):
                    cmd = lit.group(1)
                else:
                    dyn = True
            elif q.endswith('cmd='):
                dyn = True
            elif q in ('', '?') and re.match(r"[\"'`]\s*\+", s[m.end():m.end() + 6]):
                dyn = True        # the query string is appended by the caller (post(q))
            yield dict(file=f, name=f.name, cgi=m.group(1), query=q, cmd=cmd, dyn=dyn, text=s,
                       start=m.start(), end=m.end())


def window(c, before=450, after=500):
    return c['text'][max(0, c['start'] - before):c['end'] + after]


class WiringE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = list(calls())
        cls.table, cls.action_text = action_table()
        cls.readonly = action_readonly(cls.action_text)

    def test_extraction_is_not_empty(self):
        self.assertGreater(len(self.calls), 150)
        self.assertGreater(len({c['cgi'] for c in self.calls}), 20)

    def test_cgi_exists(self):
        bad = sorted({(c['name'], c['cgi']) for c in self.calls if not (CGI / (c['cgi'] + '.cgi')).exists()})
        self.assertEqual(bad, [], 'pages reference a CGI that does not exist')

    def test_every_cgi_is_called_or_documented(self):
        # dead-code guard: a CGI no page / script / daemon calls must at least be a documented interface (docs/api.md,
        # docs/linux-port/*.md: curl-able debug endpoints)
        called = {c['cgi'] for c in self.calls if c['name'] != c['cgi'] + '.cgi'}
        docs = read(ROOT / 'docs/api.md') + ''.join(read(p) for p in (ROOT / 'docs/linux-port').glob('*.md'))
        other = ''
        for d in ('scripts', 'controlscripts', 'v3', 'src'):
            for p in (ROOT / d).rglob('*'):
                if p.is_file() and p.suffix in ('', '.sh', '.c', '.h', '.md') and p.stat().st_size < 3_000_000:
                    other += read(p)
        dead = [p.stem for p in CGI.glob('*.cgi')
                if p.stem not in called and p.name not in other and p.stem + '.cgi' not in docs
                and p.stem not in ('func', 'statelib')]       # sourced libraries
        self.assertEqual(dead, [], 'CGIs that nothing calls and no document describes')

    def test_data_target_pages_exist(self):
        bad = []
        for f in sources():
            for m in re.finditer(r'data-target=["\']([^"\'?]+\.html)', read(f)):
                if not (WWW / m.group(1)).exists():
                    bad.append((f.name, m.group(1)))
        self.assertEqual(bad, [])

    def test_dynamic_urls_are_allow_listed(self):
        bad = sorted({(c['name'], c['cgi'], c['query']) for c in self.calls
                      if c['dyn'] and (c['name'], c['cgi'], c['query']) not in DYNAMIC})
        self.assertEqual(bad, [], 'URL with a run-time cmd: resolve it or add it to DYNAMIC with the reason')
        used = {(c['name'], c['cgi'], c['query']) for c in self.calls if c['dyn']}
        self.assertEqual(sorted(set(DYNAMIC) - used), [], 'stale DYNAMIC entries')

    def _all_cmds(self):
        for c in self.calls:
            if c['cmd']:
                yield c, c['cmd']
            elif c['dyn']:
                for x in DYNAMIC.get((c['name'], c['cgi'], c['query']), ('', []))[1]:
                    yield c, x

    def test_cmd_has_a_branch(self):
        missing = set()
        for c, cmd in self._all_cmds():
            if c['cgi'] == 'action':
                g = self.table.get(cmd)
                if g is None:
                    # handled before the dispatch table (logout is browser side: HTTP Basic has no logout)
                    if cmd == 'logout' or handles(self.action_text.split('# Each command lives')[0], cmd):
                        continue
                    missing.add((c['name'], 'action', cmd, 'not in the dispatch table'))
                elif not handles(read(ACTION_D / (g + '.sh')), cmd):
                    missing.add((c['name'], 'action', cmd, 'no branch in action.d/%s.sh' % g))
            elif not handles(handler_text(c['cgi']), cmd):
                missing.add((c['name'], c['cgi'], cmd, 'no branch'))
        self.assertEqual(sorted(missing), [])

    def test_query_params_are_read(self):
        bad = set()
        for c in self.calls:
            for k in re.findall(r'[?&]([A-Za-z_]+)=', c['query']):
                if k in ('cmd', '_', 'format', 'uid'):
                    continue
                t = handler_text(c['cgi'])
                if not re.search(r'F_' + k + r'\b|\b' + k + r'=|[|(" ]' + k + r'[|)" ]|\b' + k + r'\)', t):
                    bad.add((c['name'], c['cgi'], k))
        self.assertEqual(sorted(bad), [], 'query parameters no handler reads')

    def test_csrf_and_method(self):
        readonly = self.readonly
        mut = {}
        bad = set()
        for c, cmd in self._all_cmds():
            cgi = c['cgi']
            if cgi in NO_TOKEN_OK or c['name'] == cgi + '.cgi':
                continue          # a CGI printing its own links to itself (shell loops), checked by its page tests
            if cgi == 'action':
                needs_token, needs_post = cmd not in readonly, False
            else:
                mut.setdefault(cgi, mutating_cmds(cgi))
                m = mut[cgi]
                needs_token = needs_post = (m == 'all') or (cmd in m)
            if not needs_token:
                continue
            pre = c['text'][max(0, c['start'] - 26):c['start']]
            if re.search(r'(data-target|action|dataset\.target)\s*=\s*["\'`]?$', pre):
                continue          # sent by a generic handler: see test_generic_handlers_send_the_token
            w = window(c)
            if re.search(r'post\(["\']$', c['text'][max(0, c['start'] - 8):c['start']]) and \
                    re.search(r'post\s*=\s*function[^\n]*csrfFetch', c['text']):
                w += ' csrfFetch'        # local post() helper of the page, defined with csrfFetch
            if not CSRF_AWARE.search(w):
                bad.add((c['name'], cgi, cmd, 'no CSRF token sent'))
            if needs_post and not re.search(r"POST|csrfFetch|\bcf\(", w):
                bad.add((c['name'], cgi, cmd, 'POST required'))
        self.assertEqual(sorted(bad), [])

    def test_export_string_types_are_exported_as_strings(self):
        # the export writes a value as JSON only when its type is numeric or in the string-type list of the awk
        # program: a string-valued type missing from the list is silently left out of every export
        ce = read(CGI / 'config_exchange.cgi')
        listed = set(re.search(r't ~ /\^\(topology\|([^)]*)\)\$/', ce).group(1).split('|')) | {'topology'}
        validator = read(ROOT / 'scripts/config-transaction.sh')
        rows = re.findall(r'row\("[^"]+";"[^"]+";"[^"]*";"[^"]+";"([^"]+)"', ce)
        bad = set()
        for t in set(rows):
            if t == 'bool' or t.startswith('u:') or t in listed or t.startswith('isp_'):  # isp_*: own branches in the awk
                continue
            m = re.search(r'^    ' + re.escape(t) + r'\)(.*?)(?=^    [A-Za-z_|:*]+\)|^\s*\*\) )', validator, re.M | re.S)
            if m and re.search(r'case [^\n]* in [^\n]*\b[a-z][a-z-]+\b[^\n]*\)', m.group(1)):
                bad.add(t)
        self.assertEqual(sorted(bad), [], 'string-valued row types missing from the export string-type list')

    def test_written_settings_are_exported_or_listed(self):
        ce = read(CGI / 'config_exchange.cgi')
        rows = {(os.path.basename(f), k) for f, k in re.findall(r'row\("([^"]+)";"[^"]+";"[^"]*";"([^"]+)"', ce)}
        files = {f for f, _ in rows}
        written = set()
        for p in list(ACTION_D.glob('*.sh')) + list(CGI.glob('*.cgi')):
            for m in re.finditer(r'rewrite_config\s+/mnt/config/([A-Za-z0-9_.]+)\s+([A-Za-z_][A-Za-z0-9_]*)', read(p)):
                written.add((m.group(1), m.group(2)))
        missing = sorted(k for k in written if k[0] in files | {'mqtt.conf'} and k not in rows and k not in NOT_EXPORTED)
        self.assertEqual(missing, [], 'written by the UI/API, neither exported nor listed in NOT_EXPORTED')
        stale = sorted(k for k in NOT_EXPORTED if k in rows)
        self.assertEqual(stale, [], 'NOT_EXPORTED entries that are exported now')

    def test_every_exported_key_is_read_somewhere(self):
        # a setting that is exported (so written by the UI or an import) must be read by something that runs
        ce = read(CGI / 'config_exchange.cgi')
        rows = re.findall(r'row\("([^"]+)";"[^"]+";"[^"]*";"([^"]+)"', ce)
        pool = {}
        for base in ('scripts', 'controlscripts', 'v3', 'src/tc100rtsp', 'src/tc100-mqttd', 'src/httpfront', 'src',
                     'www/cgi-bin'):
            d = ROOT / base
            if not d.exists():
                continue
            for p in d.rglob('*'):
                if p.is_file() and p.suffix in ('', '.sh', '.c', '.h', '.cgi', '.awk', '.py') and \
                        'config_exchange' not in p.name and p.stat().st_size < 3_000_000:
                    pool[p] = read(p)
        unread = []
        for f, k in rows:
            if k in ('value', 'password', 'ssid', 'psk') or f in ('wpa_supplicant.conf', 'user.pwd'):
                continue          # single-value files / secrets are read by their own files
            # conf_get / load_conf_file expose keys as C_KEY, BC_KEY ...: accept that prefix
            rx = re.compile(r'(?<![A-Za-z0-9])(?:[A-Z]{1,3}_)?' + re.escape(k) + r'(?![A-Za-z0-9_])')
            found = False
            for p, t in pool.items():
                for ln in t.split('\n'):
                    if rx.search(ln) and not re.search(r'rewrite_config|config-transaction|^\s*#', ln):
                        found = True
                        break
                if found:
                    break
            if not found:
                unread.append((f, k))
        self.assertEqual(unread, [], 'exported keys that nothing reads')

    def test_generic_handlers_send_the_token(self):
        # URLs held in data-target / data-checked / data-unchecked / form action= are sent by generic code
        need = [
            ('src/webui/index/90-startup.js', r'csrfFetch\(promptTarget\.dataset\.target'),
            ('src/webui/index/95-settings-page.js', r"csrfFetch\(action, \{ method: 'POST'"),
            ('www/scripts/scripts.bundle.min.js', r'EliteUI\.csrfFetch\(target, \{ method: .POST.'),
            ('www/scripts/scripts.bundle.min.js', r'EliteUI\.csrfFetch\(url, \{ method: .POST.'),
        ]
        bad = [f for f, rx in need if not re.search(rx, read(ROOT / f))]
        self.assertEqual(bad, [])

    def test_whole_cgi_mutations_send_the_token(self):
        # update.cgi / flashinstall.cgi / upload_audio.cgi: POST needs the token whatever cmd: calls without cmd too
        bad = set()
        for c in self.calls:
            if c['cgi'] in ('update', 'flashinstall', 'upload_audio') and c['name'] != c['cgi'] + '.cgi':
                if 'POST' in window(c, 200, 300) and not CSRF_AWARE.search(window(c, 450, 3500)):
                    bad.add((c['name'], c['cgi'], c['query']))
        self.assertEqual(sorted(bad), [])


if __name__ == '__main__':
    unittest.main()
