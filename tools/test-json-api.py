#!/usr/bin/env python3
# Validates the C1 fix: action.cgi's JSON responses are now well-formed.
# Sources func.cgi and calls the body-only helpers (json_body_ok / json_body_err)
# across tricky messages, asserting with a real JSON parser that every response
# is valid JSON with the right fields and NO leaked HTTP header block.
#
# func.cgi's query parser uses ${var//} (a bash/busybox-ash feature dash lacks),
# but the helpers themselves don't — we source with an empty QUERY_STRING so the
# parser loop is a no-op, then call the helpers. Run: python3 tools/test-json-api.py
import subprocess, json, os, sys, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNC = os.path.join(ROOT, "www", "cgi-bin", "func.cgi")
SH = "dash" if shutil.which("dash") else "sh"
PRELUDE = f'QUERY_STRING=""; REQUEST_METHOD=""; . {FUNC}; '
ENV = dict(os.environ, LC_ALL="C.UTF-8", LANG="C.UTF-8")

def run(snippet, **msgvars):
    # Pass test messages via the environment (not interpolated into the shell
    # command) so quotes / backslashes / $ / unicode reach the helper verbatim.
    env = dict(ENV, **msgvars)
    r = subprocess.run([SH, "-c", PRELUDE + snippet], capture_output=True, text=True, env=env)
    return r.stdout, r.stderr, r.returncode

pass_n = fail_n = 0
def check(desc, cond):
    global pass_n, fail_n
    if cond: pass_n += 1
    else:
        fail_n += 1
        print(f"FAIL: {desc}")

OK_MSGS = [
    "Video settings for stream 0 updated.",
    'Preset "living room" created',
    "path C:\\temp\\x",
    "weird & < > | ; ( ) chars",
    "unicode: café €",
    "",
    "DNS updated. Primary: 1.1.1.1 Secondary: none. Reboot to make permanent.",
]
for m in OK_MSGS:
    out, err, rc = run('json_body_ok "$MSG"', MSG=m)
    check(f"ok stderr empty {m!r}", err.strip() == "")
    check(f"ok no header leak {m!r}", "Status:" not in out and "Content-type" not in out)
    try:
        o = json.loads(out)
        check(f"ok valid JSON {m!r}", True)
        check(f"ok=true {m!r}", o.get("ok") is True)
        check(f"message roundtrip {m!r}", o.get("message") == m)
        check(f"code=ok {m!r}", o.get("code") == "ok")
        check(f"timestamp int {m!r}", isinstance(o.get("timestamp"), int))
    except Exception as e:
        check(f"ok valid JSON {m!r} ({e}) [{out!r}]", False)

ERR_CASES = [
    ("INVALID_PORT", "Invalid telnet port. Allowed range is 1-65535."),
    ("AUDIO_TEST_FAILED", 'unsupported source format: "wav"'),
    ("UNSUPPORTED_COMMAND", "Unsupported command 'foo'"),
    ("PRESET_NOT_FOUND", "Preset 'x' not found"),
]
for code, msg in ERR_CASES:
    out, err, rc = run('json_body_err "$C" "$M"', C=code, M=msg)
    check(f"err stderr empty {code}", err.strip() == "")
    check(f"err no header leak {code}", "Status:" not in out and "Content-type" not in out)
    try:
        o = json.loads(out)
        check(f"err valid JSON {code}", True)
        check(f"ok=false {code}", o.get("ok") is False)
        check(f"error=message {code}", o.get("error") == msg)
        check(f"code=code {code}", o.get("code") == code)
    except Exception as e:
        check(f"err valid JSON {code} ({e}) [{out!r}]", False)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
