"""Forks removed from the once-a-minute Wi-Fi jobs (review of the background brief, docs/linux-port/frontier/
background-2026-11-11.md): the new lines must give exactly what the old ones gave, in busybox ash.

wifi-quality.sh: the gateway address without two $(echo | cut), the packet loss without printf | sed | head;
wifi-roam.sh: the uptime without $(cut), no mkdir / rm when there is nothing to do.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASH = shutil.which("busybox")

OLD_GATEWAY = r'''old_gw() { _gw=$1; printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$(echo "$_gw" | cut -c5-6)" "0x$(echo "$_gw" | cut -c3-4)" "0x${_gw%??????}"; }'''
OLD_LOSS = r'''old_loss() { _out=$1; _p=$(printf '%s\n' "$_out" | sed -n 's/.* \([0-9][0-9]*\)% packet loss.*/\1/p' | head -n 1)
  case "$_p" in ''|*[!0-9]*) echo null ;; *) echo "$_p" ;; esac; }'''

PINGS = [
    "PING 192.168.1.1 (192.168.1.1): 56 data bytes\n\n--- 192.168.1.1 ping statistics ---\n"
    "3 packets transmitted, 3 packets received, 0% packet loss\nround-trip min/avg/max = 1.9/3.1/4.8 ms",
    "--- 192.168.1.1 ping statistics ---\n3 packets transmitted, 2 packets received, 33% packet loss",
    "--- 192.168.1.1 ping statistics ---\n3 packets transmitted, 0 packets received, 100% packet loss",
    "3 packets transmitted, 3 received, 0% packet loss, time 2003ms",      # iputils
    "",
    "ping: sendto: Network unreachable",
    "1 2 3 packets transmitted, 7% packet loss\nother line 9% packet loss",  # two matches: the first line wins
]


def ash(code, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([ASH, "ash", "-c", code], capture_output=True, text=True, env=e, timeout=20)


def code_only(f):
    return "\n".join(l for l in f.split("\n") if not l.lstrip().startswith("#"))


def shfunc(path, name):
    s = (ROOT / path).read_text(encoding="utf-8")
    return re.search(r"^" + re.escape(name) + r"\(\)\s*\{.*?^}", s, re.M | re.S).group(0)


@unittest.skipUnless(ASH, "needs busybox")
class ForkCuts(unittest.TestCase):
    def test_gateway_is_unchanged(self):
        gw = shfunc("scripts/wifi-quality.sh", "wq_gateway")
        self.assertNotIn("| cut", code_only(gw))
        with tempfile.TemporaryDirectory() as t:
            for hexgw in ("0101A8C0", "FE01A8C0", "0100000A", "FFFFFFFF", "00000000", "0A0B0C0D"):
                route = Path(t, "route")
                route.write_text("Iface\tDestination\tGateway \tFlags\n"
                                 f"wlan0\t0001A8C0\t00000000\t0001\nwlan0\t00000000\t{hexgw}\t0003\n")
                code = (OLD_GATEWAY + "\n" + gw.replace("/proc/net/route", str(route))
                        + f'\nold_gw {hexgw}; wq_gateway')
                a, b = ash(code).stdout.split("\n")[:2]
                self.assertEqual(a, b, hexgw)

    def test_loss_is_unchanged(self):
        loss = shfunc("scripts/wifi-quality.sh", "wq_loss")
        self.assertNotIn("| sed", code_only(loss))
        with tempfile.TemporaryDirectory() as t:
            for out in PINGS:
                f = Path(t, "ping")
                f.write_text(out)
                code = OLD_LOSS + "\n" + loss + '\nold_loss "$(cat "$WQ_PING")"; wq_loss'
                a, b = ash(code, {"WQ_PING": str(f)}).stdout.split("\n")[:2]
                self.assertEqual(a, b, repr(out))

    def test_roam_uptime_and_idle_path(self):
        s = (ROOT / "scripts/wifi-roam.sh").read_text(encoding="utf-8")
        self.assertNotIn("cut -d. -f1 /proc/uptime", s)
        self.assertNotIn("$(now)", s)
        # good signal, nothing to do: the state directory exists, no weak file -> the run forks nothing
        with tempfile.TemporaryDirectory() as t:
            env = {"WRO_STATE": t, "WRO_DBM": "-50", "WRO_NOW": "1000", "WRO_WPA_CLI": "false"}
            r = subprocess.run([ASH, "ash", str(ROOT / "scripts/wifi-roam.sh"), "once"], env={**os.environ, **env},
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0)
            Path(t, "weak").write_text("1\n")
            r = subprocess.run([ASH, "ash", str(ROOT / "scripts/wifi-roam.sh"), "once"], env={**os.environ, **env},
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0)
            self.assertFalse(Path(t, "weak").exists())     # a good signal still clears the weak count
        # the uptime read gives what cut gave
        code = 'read -r t _ < /proc/uptime; t=${t%%.*}; c=$(cut -d. -f1 /proc/uptime); [ "$t" -le "$c" ] && [ $((c - t)) -le 1 ] && echo same'
        self.assertEqual(ash(code).stdout.strip(), "same")


if __name__ == "__main__":
    unittest.main()
