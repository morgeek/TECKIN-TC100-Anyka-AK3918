#!/usr/bin/env python3
"""Build a bounded, self-contained brief for a frontier model (Fable or similar), one subject at a time.

The model gets only what this script puts in the brief: no repository, no tools, no camera. That is what keeps the
cost bounded and the answer focused. Each brief has the shared guardrails, the question, the expected answer format
and code excerpts cut by function name (or line range), and the script refuses to write a brief over MAX_CHARS.

    python3 docs/linux-port/frontier/brief.py --list
    python3 docs/linux-port/frontier/brief.py daynight --data /path/to/night-summary.md -o /tmp/brief-daynight.md
    python3 docs/linux-port/frontier/brief.py talk -o brief-talk.md

The subjects, rules and the way an answer comes back are in docs/linux-port/a-faire-implementeur.md,
section "Dossiers pour un modèle frontier".
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
MAX_CHARS = 60000          # about 15 k tokens of input: the whole brief, guardrails included
MAX_DATA_CHARS = 8000      # a --data file (measurement summary), never raw logs
KERNEL = "patches/kernel-6.6/series/0006-media-anyka-isp-add-ISP-video-input-and-sensor-drive.patch"

GUARDRAILS = """## Rules for this task (read first)

- You only have this document. Do not ask for the repository, more files or tool access, and do not assume code that
  is not shown: when something you need is missing, say exactly what (file, function) and continue with what you have.
- Analysis in writing only. No full rewrite of a file. A change you propose is a minimal unified diff on the excerpts
  shown, at most about 60 lines in all, or a short pseudo-code when the design is the point.
- Hardware facts: the camera is an Anyka AK3918 (ARM926EJ-S, ARMv5, 64 MB RAM, about 20 MB free), Linux 6.6, musl,
  busybox ash, no compiler on the camera. Every change must stay small in RAM and CPU.
- Never propose: touching U-Boot or the boot environment, flashing, changing a default value that reaches an installed
  camera without a one-time migration, removing a test, or disabling a security check.
- Separate what the excerpts prove from what you suppose. Number your hypotheses and give each one a concrete check
  (a log line to read, a value to measure, a test to write) that confirms or rules it out.
- Keep the whole answer under about 1500 words. Stop when the question is answered; do not add a general review of
  other topics.

## Expected answer

1. Short answer (5 lines at most).
2. Findings, most important first, each with: the excerpt and line it rests on, proved or supposed, consequence.
3. Proposal (diff or pseudo-code), only for the findings that need one.
4. Checks to run, in order, each with what result confirms or rules out what.
5. What was missing from this document, if anything.
"""

SUBJECTS = {
    "daynight": {
        "title": "Day / night switching that cannot oscillate (item 21)",
        "question": """The camera switches between day (IR-cut filter in, colour) and night (filter out, infrared LEDs on,
greyscale) from one of four light measurements (DAYNIGHT_SOURCE = luma, ae, isp or vendor). The decision runs in the C
supervisor, every 5 s (functions below). With the default `luma` source, the night of 2026-11-10 oscillated: 44
switches, one every 3 min (MIN_SWITCH) from 01:38 to 03:31 in a dark room. Cause found in the capture: the picture
luminance is regulated by the auto-exposure towards its target, so it settles at 100-102 with the IR LEDs on (just above
LUMA_DAY = 100: back to day) and at 37-38 in day mode in the dark (just under LUMA_NIGHT = 40: back to night). The
`vendor` source (stock firmware method: exposure x gain / AE luminance, plus white-balance counts) was replayed on the
same capture without a false switch; the data summary at the end has the measured values, and the result of a real
night with `vendor` when available.

Questions:
1. Is the `vendor` decision as written free of oscillation for these values? Under which light conditions can it
   still oscillate (dawn, dusk, a lamp switched on or off, IR LEDs cut by the protection `dn_ir_guard`)?
2. Propose the decision rule that should be the default: inputs, thresholds or how to derive them, hysteresis, hold
   times, and the argument (or proof) that it cannot oscillate with an IR light that raises the measured light by itself.
3. What should the `luma` source become (kept as is, fixed, or only a fallback), given that installed cameras use it?
4. Which log fields are missing to check this in one more night?""",
        "parts": [
            ("lines", "src/supervisord/supervisord.c", 205, 236),
            ("cfunc", "src/supervisord/supervisord.c", "dn_index"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_vendor_lum"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_switch"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_hold"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_step_ae"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_awb"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_step_vendor"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_ir_guard"),
            ("cfunc", "src/supervisord/supervisord.c", "dn_step_luma"),
        ],
        "needs_data": True,
    },
    "talk": {
        "title": "Audio backchannel: one talker at a time, the speaker lock (talk.c)",
        "question": """RTSP clients can send audio to the camera speaker (ONVIF backchannel). talk.c gives the speaker to
one client at a time, spawns the player (speaker-play.sh) and shares the speaker with other users (browser push-to-talk,
sound tests) through the directory lock /tmp/speaker-play.lock. The host test suite was flaky on these tests (a talker
was sometimes refused); it was mitigated in the tests by waiting for the lock to disappear between tests
(wait_speaker_free), not explained.

Questions:
1. Find the races and the states where the speaker can stay taken, be given to two talkers, or be refused while free:
   between talk_rtp, talk_tick, talk_release, the player's exit, the lock directory and its owner reset.
2. Which one explains a refused talker right after a previous test ended? Is the test workaround hiding a real bug
   that a user could hit (client disconnects while the player starts, two clients within 2 s, a browser
   push-to-talk at the same time)?
3. Minimal fix, and the test that would have caught it.""",
        "parts": [
            ("file", "src/tc100rtsp/talk.c"),
            ("file", "scripts/speaker-play.sh"),
            ("lines", "tests/test_tc100rtsp.py", 612, 700),
            ("lines", "tests/test_tc100rtsp.py", 883, 1000),
        ],
        "needs_data": False,
    },
    "nr": {
        "title": "Noise reduction strength (DENOISE): ISP structures and driver use",
        "question": """tc100_rtsp reads the ISP noise-reduction blocks (NR1 raw domain, NR2 luma: a mode, a manual set and
9 sets chosen by the driver from the total gain), stretches the 17-point weight curves along the pixel difference by a
user factor (DENOISE -50..50, 2 % per step) and writes them back with the SET ioctls. The kernel driver excerpts show the
structures, what SET does, and how the driver picks and applies a set. Not yet tested on a camera.

Questions:
1. Is the structure layout right (ARM EABI, unsigned short fields, sizes 1782 / 482 checked) and is the GET / SET use
   safe (sizes, what the driver copies, what happens while the driver applies a set from the stats work)?
2. Is stretching the weight curves the right lever for "more / less smoothing" given how the driver and the hardware
   use them (weights, nr1_k, the lc_lut tables, calc_*_k which the driver does not write)? Would scaling another field
   be more faithful? What visible artefacts can +50 or -50 produce?
3. Can the base copy (read once per video start) go stale: night tuning style switch, an ISP reset, the driver changing
   the sets by itself, tc100_rtsp restart while DENOISE != 0?
4. Bugs in nr_stretch / nr_apply (rounding, monotonicity, index 16, f = 0).""",
        "parts": [
            ("grep", "src/tc100rtsp/tc100_rtsp.c", r"struct isp_nr|ISP_GET_NR|ISP_SET_NR|nr_base = -1|p_dnr != nr_asked|nr_log\(fd\)|p_dnr = p_dnr|\"DENOISE\""),
            ("cfunc", "src/tc100rtsp/tc100_rtsp.c", "nr_stretch"),
            ("cfunc", "src/tc100rtsp/tc100_rtsp.c", "nr_apply"),
            ("cfunc", "src/tc100rtsp/tc100_rtsp.c", "nr_log"),
            ("lines", KERNEL, 16658, 16710),
            ("lines", KERNEL, 2249, 2266),
            ("lines", KERNEL, 7488, 7560),
            ("lines", KERNEL, 8160, 8215),
        ],
        "needs_data": False,
    },
    "cgi": {
        "title": "Web form input handling: parsing, CSRF, rate limit, config import",
        "question": """The web interface runs busybox ash CGI scripts as root on the camera. func.cgi parses the query and
POST body into shell variables F_<name>, and provides the CSRF, mutation and rate-limit guards; action.cgi applies
settings; config_exchange.cgi imports a configuration bundle (JSON) into the config files. This is a defensive review
of our own code, to fix it.

Questions:
1. Can a request inject shell code or change a variable other than F_<name> (names, values, encoding, length,
   duplicate keys, newlines, NUL)? Can the import write a file or key outside the allowed table?
2. Can the CSRF / mutation guard be bypassed (method, content type, missing or empty token, a GET that mutates)?
3. Denial of service by one request (size, slow body, rate limit state in /tmp).
4. For each finding: the request that shows it (as a curl command line against the camera's own web server) and the
   minimal fix.""",
        "parts": [
            ("lines", "www/cgi-bin/func.cgi", 1, 195),
            ("shfunc", "www/cgi-bin/func.cgi", "rate_limit_check"),
            ("shfunc", "www/cgi-bin/func.cgi", "csrf_guard"),
            ("shfunc", "www/cgi-bin/func.cgi", "mutation_guard"),
            ("lines", "www/cgi-bin/action.cgi", 1, 47),
            ("shfunc", "www/cgi-bin/action.cgi", "sanitize_int_range"),
            ("shfunc", "www/cgi-bin/config_exchange.cgi", "_ce_form_get"),
            ("shfunc", "www/cgi-bin/config_exchange.cgi", "_ce_prepare_file"),
            ("shfunc", "www/cgi-bin/config_exchange.cgi", "_ce_import"),
        ],
        "needs_data": False,
    },
}


def lines_of(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace").split("\n")


def cut(rel, a, b):
    ls = lines_of(rel)
    return a, "\n".join(ls[a - 1:b])


def cfunc(rel, name):
    ls = lines_of(rel)
    for i, l in enumerate(ls):
        if re.match(rf"^(static\s+)?[\w\s\*]*\b{name}\s*\(", l) and not l.rstrip().endswith(";"):
            depth, seen = 0, False
            for j in range(i, len(ls)):
                depth += ls[j].count("{") - ls[j].count("}")
                seen = seen or "{" in ls[j]
                if seen and depth == 0:
                    return i + 1, "\n".join(ls[i:j + 1])
    raise SystemExit(f"{rel}: C function {name} not found")


def shfunc(rel, name):
    ls = lines_of(rel)
    for i, l in enumerate(ls):
        if re.match(rf"^{re.escape(name)}\(\)\s*\{{?\s*$", l):
            for j in range(i + 1, len(ls)):
                if ls[j] == "}":
                    return i + 1, "\n".join(ls[i:j + 1])
    raise SystemExit(f"{rel}: shell function {name} not found")


def grep(rel, pat):
    ls = lines_of(rel)
    out = [f"{i + 1}: {l}" for i, l in enumerate(ls) if re.search(pat, l)]
    return None, "\n".join(out)


def build(key, data=None):
    s = SUBJECTS[key]
    out = [f"# {s['title']}\n", "Project: free firmware for the TECKIN TC100 camera (Anyka AK3918).\n", GUARDRAILS,
           "## Question\n", s["question"], "\n## Excerpts\n"]
    for part in s["parts"]:
        kind, rel = part[0], part[1]
        if kind == "lines":
            start, text = cut(rel, part[2], part[3])
            where = f"{rel}:{part[2]}-{part[3]}"
        elif kind == "file":
            start, text = 1, (ROOT / rel).read_text(encoding="utf-8")
            where = rel
        elif kind == "cfunc":
            start, text = cfunc(rel, part[2])
            where = f"{rel}:{start} ({part[2]})"
        elif kind == "shfunc":
            start, text = shfunc(rel, part[2])
            where = f"{rel}:{start} ({part[2]})"
        else:
            start, text = grep(rel, part[2])
            where = f"{rel} (matching lines, with their numbers)"
        lang = "c" if rel.endswith((".c", ".h", ".patch")) else "python" if rel.endswith(".py") else "sh"
        out.append(f"### {where}\n\n```{lang}\n{text}\n```\n")
    if s["needs_data"]:
        if not data:
            raise SystemExit(f"{key}: needs --data (a measurement summary written for this brief, not raw logs)")
        d = Path(data).read_text(encoding="utf-8")
        if len(d) > MAX_DATA_CHARS:
            raise SystemExit(f"--data is {len(d)} chars, over {MAX_DATA_CHARS}: summarise it (tables, not raw logs)")
        out.append("## Data summary\n\n" + d + "\n")
    brief = "\n".join(out)
    if len(brief) > MAX_CHARS:
        raise SystemExit(f"{key}: brief is {len(brief)} chars, over {MAX_CHARS}: cut excerpts before sending it")
    return brief


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject", nargs="?", choices=sorted(SUBJECTS))
    ap.add_argument("--data", help="measurement summary (Markdown, at most %d chars)" % MAX_DATA_CHARS)
    ap.add_argument("-o", "--output", help="write the brief here (default: stdout)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.subject:
        for k, s in SUBJECTS.items():
            print(f"{k:9} {s['title']}{'  (needs --data)' if s['needs_data'] else ''}")
        return
    brief = build(a.subject, a.data)
    if a.output:
        Path(a.output).write_text(brief, encoding="utf-8")
    else:
        sys.stdout.write(brief)
    print(f"{a.subject}: {len(brief)} chars, about {len(brief) // 4} tokens", file=sys.stderr)


if __name__ == "__main__":
    main()
