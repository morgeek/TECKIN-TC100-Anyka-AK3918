#!/usr/bin/env python3
# End-to-end validation of state.cgi?cmd=frigateyaml: sets up a minimal /mnt
# tree, runs state.cgi under bash (func.cgi needs ${var//} which dash lacks),
# and asserts the emitted YAML parses and has the correct Frigate structure.
#
# Best-effort: SKIPS cleanly (exit 0) if /mnt isn't writable, or bash / PyYAML
# are missing — so it never breaks CI. The CI-safe structural checks live in
# tools/test-wave3-fixes.sh. Run: python3 tools/test-frigateyaml.py
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def skip(msg):
    print(f"SKIP: {msg}")
    sys.exit(0)

if not shutil.which("bash"):
    skip("bash not available")
try:
    import yaml
except ImportError:
    skip("PyYAML not installed (pip install pyyaml)")

# Try to build a minimal /mnt sandbox.
try:
    for d in ("/mnt/www/cgi-bin", "/mnt/scripts", "/mnt/config", "/mnt/bin"):
        os.makedirs(d, exist_ok=True)
    shutil.copy(f"{ROOT}/www/cgi-bin/func.cgi", "/mnt/www/cgi-bin/func.cgi")
    shutil.copy(f"{ROOT}/www/cgi-bin/state.cgi", "/mnt/www/cgi-bin/state.cgi")
    shutil.copy(f"{ROOT}/scripts/common_functions.sh", "/mnt/scripts/common_functions.sh")
    open("/mnt/config/rtspserver.conf", "w").write(
        "USERNAME=root\nUSERPASSWORD=secret\nPORT=554\n"
        "0_width=1280\n0_height=720\n0_fps=16\n0_codec=2\n"
        "1_width=640\n1_height=360\n1_fps=8\n1_codec=0\n")
    open("/mnt/config/boot.conf", "w").write("WEB_MODE=full\nRTSP_SUBSTREAM=1\nRTSP_AUDIO=1\n")
    open("/mnt/config/mqtt.conf", "w").write("MQTT_ENABLE=1\nMQTT_HOST=192.168.1.10\nMQTT_PORT=1883\nMQTT_USER=frigate\n")
    open("/mnt/VERSION", "w").write("v1.3.0\n")
except (PermissionError, OSError) as e:
    skip(f"cannot set up /mnt sandbox ({e})")

def render(qs):
    r = subprocess.run(["bash", "/mnt/www/cgi-bin/state.cgi"],
                       env=dict(os.environ, REQUEST_METHOD="GET", QUERY_STRING=qs),
                       capture_output=True, text=True, cwd="/mnt/www/cgi-bin")
    body = r.stdout.split("\n\n", 1)[-1]  # strip CGI headers
    return body

pass_n = fail_n = 0
def chk(c, m):
    global pass_n, fail_n
    print(("PASS" if c else "FAIL") + ": " + m)
    if c: pass_n += 1
    else: fail_n += 1

# substream enabled
doc = yaml.safe_load(render("cmd=frigateyaml"))
chk(isinstance(doc, dict), "renders a YAML mapping")
cam = doc["cameras"][list(doc["cameras"])[0]]
inputs = cam["ffmpeg"]["inputs"]
roles = [r for i in inputs for r in i["roles"]]
chk("record" in roles and "detect" in roles, "record + detect roles present")
chk(all(i["path"].startswith("rtsp://127.0.0.1:8554/") for i in inputs), "inputs use go2rtc restream")
chk(cam["detect"]["enabled"] is True, "detect.enabled true")
chk(cam["detect"]["width"] == 640 and cam["detect"]["fps"] == 8, "detect uses sub-stream dims")
chk("retain" not in cam["record"], "no deprecated record.retain")
chk(cam["record"]["alerts"]["retain"]["days"] == 14, "current alerts retention schema")
chk(doc["mqtt"]["enabled"] is True and doc["mqtt"]["host"] == "192.168.1.10", "mqtt section")
gs = doc["go2rtc"]["streams"]
chk(any("/video0_unicast" in v[0] for v in gs.values()), "go2rtc maps to real camera rtsp")

# no substream -> single input carries both roles, detect uses main dims
open("/mnt/config/boot.conf", "w").write("WEB_MODE=full\nRTSP_SUBSTREAM=0\n")
doc2 = yaml.safe_load(render("cmd=frigateyaml"))
cam2 = doc2["cameras"][list(doc2["cameras"])[0]]
in2 = cam2["ffmpeg"]["inputs"]
chk(len(in2) == 1 and set(in2[0]["roles"]) == {"record", "detect"}, "no-sub: one input, both roles")
chk(cam2["detect"]["width"] == 1280, "no-sub: detect falls back to main dims")

# redact
body = render("cmd=frigateyaml&redact=1")
chk("USERNAME:PASSWORD@" in body and "root:secret" not in body, "redact blanks credentials")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
