"""speaker-play.sh: a stop signal ends the player; it never plays without the lock (review 2026-11-11, C5).

The trap used to run on INT and TERM too, remove the lock and let the script go on: a SIGTERM during amixer started
aplay without the lock, so a second player could start next to it.
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
LOCK = "/tmp/speaker-play.lock"


@unittest.skipUnless(shutil.which("busybox"), "needs busybox")
class SpeakerLock(unittest.TestCase):
    def setUp(self):
        for _ in range(100):
            if not os.path.isdir(LOCK):
                break
            time.sleep(0.1)
        else:
            self.skipTest("the speaker lock is held by something else")

    def test_term_during_setup_stops_without_playing(self):
        with tempfile.TemporaryDirectory() as t:
            b = Path(t, "bin")
            b.mkdir()
            Path(b, "amixer").write_text("#!/bin/sh\nsleep 2\n")
            Path(b, "aplay").write_text("#!/bin/sh\necho played > %s/played\n" % t)
            for f in b.iterdir():
                f.chmod(0o755)
            env = dict(os.environ, PATH=str(b) + os.pathsep + os.environ["PATH"])
            p = subprocess.Popen(["busybox", "ash", str(ROOT / "scripts/speaker-play.sh"), "/dev/null", "50"],
                                 env=env, start_new_session=True, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(50):          # the lock is taken, the script is in amixer
                if os.path.isdir(LOCK):
                    break
                time.sleep(0.02)
            time.sleep(0.3)
            os.killpg(p.pid, signal.SIGTERM)
            rc = p.wait(10)
            time.sleep(0.3)
            self.assertFalse(Path(t, "played").exists(), "aplay started after the stop signal")
            self.assertFalse(os.path.isdir(LOCK), "the lock is left behind")
            self.assertEqual(rc, 143)


if __name__ == "__main__":
    unittest.main()
