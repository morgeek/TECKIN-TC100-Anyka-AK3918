"""[wifiq] scripts/wifi-quality.sh with far fewer forks (audit 2026-11-24 section 7): the same files, byte for byte, as
the script of bb778fd (kept in tests/fixtures/wifi-quality-before-wifiq.sh), over simulated minutes of fake /proc, iw
and ping data, and a fork count (pid counter of busybox ash in the container) that went down.

Not identical, on purpose: after a clock that goes BACK by more than an hour the old awk scan of the whole log counted
the lines of the "future" again; the new window file already dropped them.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BB = shutil.which("busybox")
OLD = ROOT / "tests/fixtures/wifi-quality-before-wifiq.sh"
NEW = ROOT / "scripts/wifi-quality.sh"
HDR = ("Inter-| sta-|   Quality        |   Discarded packets\n face | tus | link level noise |  nwid  crypt\n")
PINGS = ["3 packets transmitted, 3 packets received, 0% packet loss\n",
         "3 packets transmitted, 2 packets received, 33% packet loss\n",
         "3 packets transmitted, 0 packets received, 100% packet loss\n",
         "",
         "3 packets transmitted, 3 packets received, 07% packet loss\n",
         "3 packets transmitted, 1 packets received, 66% packet loss\n",
         "ping: sendto: Network unreachable\n"]


def lcg(seed):
    while True:
        seed = (seed * 1103515245 + 12345) & 0x7fffffff
        yield seed >> 8


class Rig:
    """one directory with a copy of the script under test, the fake inputs and the output files"""

    def __init__(self, root, name, script):
        self.d = Path(root) / name
        self.d.mkdir()
        shutil.copy(script, self.d / "wifi-quality.sh")
        shutil.copy(ROOT / "scripts/wifi-signal.sh", self.d / "wifi-signal.sh")
        self.env = {k: str(self.d / v) for k, v in dict(
            WQ_LOG="log", WQ_SUM="sum", WQ_STATE="prev", WQ_WIRELESS="wireless", WQ_STATION="st", WQ_PING="ping",
            WQ_UPTIME="up", WIFI_AVG_FILE="avg").items()}
        self.env["PATH"] = os.environ["PATH"]

    def feed(self, st, wireless, ping, up):
        (self.d / "st").write_text(st)
        (self.d / "wireless").write_text(wireless)
        (self.d / "ping").write_text(ping)
        (self.d / "up").write_text(up)

    def run(self, now, cmd="sample"):
        env = dict(self.env, WQ_NOW=str(now))
        r = subprocess.run([BB, "ash", str(self.d / "wifi-quality.sh"), cmd], env=env, capture_output=True, text=True,
                           timeout=30)
        assert r.returncode == 0, r.stderr
        return r

    def outputs(self):
        return {n: (self.d / n).read_bytes() if (self.d / n).exists() else None
                for n in ("log", "sum", "avg", "prev")}


def step_inputs(i, gen, rt, fl):
    """the fake iw / proc / ping data of simulated minute i; rt, fl are the running counters"""
    r = next(gen)
    rt += r % 40
    fl += (r >> 5) % 3
    if i == 40:                       # a counter that went backwards (driver reload)
        rt, fl = 3, 0
    beacon = ""
    if i % 7 != 3:
        beacon = "\tbeacon signal avg:\t%d dBm\n" % ([-9, -50, -100, -110, -63, -77, -51][i % 7] - (i % 5 if i % 7 in (1, 4, 5) else 0))
    st = ("Station aa:bb:cc:dd:ee:ff (on wlan0)\n\tsignal avg:\t-13 dBm\n" + beacon +
          "\ttx retries:\t%d\n\ttx failed:\t%d\nStation 11:22 (on wlan0)\n\ttx retries:\t%d\n" % (rt, fl, 5))
    lvl = -256 if i % 11 == 5 else -40 - i % 30
    wireless = HDR + " wlan0: 0000   %d.  %d.  -256        0      0\n" % (0 if lvl == -256 else 60, lvl)
    return st, wireless, PINGS[r % len(PINGS)], "%d.%02d 1\n" % (500 + 60 * i, i % 100), rt, fl


@unittest.skipUnless(BB and os.path.isdir("/proc/self"), "needs busybox on Linux")
class Identity(unittest.TestCase):
    def pair(self, t):
        return Rig(t, "old", OLD), Rig(t, "new", NEW)

    def same(self, old, new, label):
        a, b = old.outputs(), new.outputs()
        for k in a:
            self.assertEqual(a[k], b[k], "%s: %s differs\nold=%r\nnew=%r" % (label, k, a[k], b[k]))

    def test_132_simulated_minutes_give_the_same_files(self):
        gen = lcg(7)
        rt = fl = 100
        with tempfile.TemporaryDirectory() as t:
            old, new = self.pair(t)
            now = 1000000
            for i in range(132):          # more than the 60 minutes of the window
                st, wl, ping, up, rt, fl = step_inputs(i, gen, rt, fl)
                now += 60 if i != 100 else 7200            # a forward jump (clock set)
                for rig in (old, new):
                    rig.feed(st, wl, ping, up)
                    if i == 50:                            # the previous-state file lost: both recount the log
                        (rig.d / "prev").unlink()
                    if i == 60 and rig is new:             # the window lost (an upgrade): rebuilt from the log
                        (rig.d / "prev.win").unlink()
                    rig.run(now)
                self.same(old, new, "minute %d" % i)
            self.assertGreater(len((new.d / "log").read_text().split("\n")), 100)
            self.assertIn(b"samples_1h=", new.outputs()["sum"])

    def test_upgrade_from_a_full_day_log_and_trim(self):
        """a 1440-line log and a state file of the old script, no window file: 80 samples, the trim at 1500 lines"""
        with tempfile.TemporaryDirectory() as t:
            old, new = self.pair(t)
            base = 2000000
            lines = "".join("%d %d %d %d %s\n" % (base + 60 * j, -40 - j % 37, j % 9, j % 3, "null" if j % 17 == 0 else j % 50)
                            for j in range(1440))
            for rig in (old, new):
                (rig.d / "log").write_text(lines)
                (rig.d / "prev").write_text("1000 10 1440\n")
            gen = lcg(3)
            rt, fl = 1010, 11
            now = base + 60 * 1440
            for i in range(80):
                st, wl, ping, up, rt, fl = step_inputs(i + 1, gen, rt, fl)
                for rig in (old, new):
                    rig.feed(st, wl, ping, up)
                    rig.run(now)
                self.same(old, new, "minute %d" % i)
                now += 60
            self.assertEqual(len((new.d / "log").read_text().splitlines()), 1440 + 19)    # trimmed to 1440 at the 61st

    def test_summary_command_reads_the_whole_log_like_before(self):
        with tempfile.TemporaryDirectory() as t:
            old, new = self.pair(t)
            lines = "".join("%d %s %d %d %s\n" % (5000 + 60 * j, "null" if j % 9 == 0 else -50 - j % 41, j % 7, j % 2,
                                                   "null" if j % 13 == 0 else "0%d" % (j % 10)) for j in range(200))
            for rig in (old, new):
                (rig.d / "log").write_text(lines)
                rig.run(5000 + 60 * 199, "summary")
            self.same(old, new, "summary")
            self.assertIn(b"samples_1h=", new.outputs()["sum"])


@unittest.skipUnless(BB and os.path.isdir("/proc/self"), "needs busybox on Linux")
class Forks(unittest.TestCase):
    """real iw / ping / timeout / mv through PATH (stubs for iw and ping), forks counted with the pid counter"""

    PROBE = ("probe() { sh -c 'echo $$'; }\n"
             "a=$(probe); b=$(probe); c=$((b - a))\n")      # c = pids used by one probe

    def count(self, script, runs=6):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            bindir = t / "bin"
            bindir.mkdir()
            subprocess.run([BB, "--install", "-s", str(bindir)], check=True)
            (t / "iw.out").write_text("Station aa:bb (on wlan0)\n\tbeacon signal avg:\t-55 dBm\n\ttx retries:\t10\n\ttx failed:\t1\n")
            (t / "ping.out").write_text("3 packets transmitted, 3 packets received, 0% packet loss\n")
            for n in ("iw", "ping"):
                if (bindir / n).is_symlink():           # never write through the link into the real busybox
                    (bindir / n).unlink()
            (bindir / "iw").write_text("#!/bin/sh\nexec cat '%s'\n" % (t / "iw.out"))
            (bindir / "ping").write_text("#!/bin/sh\nexec cat '%s'\n" % (t / "ping.out"))
            for n in ("iw", "ping"):
                (bindir / n).chmod(0o755)
            for n in ("old", "new"):
                (t / n).mkdir()
            # the old script reads the real /proc/net/route: point it at the fake one (the new one has WQ_ROUTE)
            (t / "wq.sh").write_text(Path(script).read_text().replace("/proc/net/route", str(t / "route")))
            shutil.copy(ROOT / "scripts/wifi-signal.sh", t / "wifi-signal.sh")
            (t / "route").write_text("Iface\tDestination\tGateway\tFlags\nwlan0\t00000000\t0101A8C0\t0003\n")
            (t / "up").write_text("1000.00 1\n")
            env = {"PATH": str(bindir), "WQ_LOG": str(t / "log"), "WQ_SUM": str(t / "sum"), "WQ_STATE": str(t / "prev"),
                   "WQ_ROUTE": str(t / "route"), "WQ_UPTIME": str(t / "up"), "WIFI_AVG_FILE": str(t / "avg"),
                   "WQ_WIRELESS": str(t / "none")}
            code = (self.PROBE + "sh %s sample\n" % (t / "wq.sh") +       # a first run: files and caches exist
                    "p0=$(probe)\n"
                    "i=0; while [ $i -lt %d ]; do WQ_NOW=$((5000 + i * 60)) sh %s sample; i=$((i + 1)); done\n"
                    "p1=$(probe)\n"
                    "echo $(( (p1 - p0 - c) / %d ))\n" % (runs, t / "wq.sh", runs))
            r = subprocess.run([BB, "ash", "-c", code], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((t / "sum").exists())
            self.assertIn("-55", (t / "avg").read_text())
            return int(r.stdout.split()[-1])

    def test_fork_count_went_down(self):
        old = self.count(OLD)
        new = self.count(NEW)
        print("\nwifi-quality.sh forks per run (the sh that starts it included): old %d, new %d" % (old, new))
        self.assertGreaterEqual(old, 12)
        # busybox timeout costs 3 pids (itself, its timer, the command): 2 x 3 for iw and ping, 2 mv, the launch
        self.assertLessEqual(new, 9)
        self.assertLessEqual(new, old - 4)


if __name__ == "__main__":
    unittest.main()
