"""[up-fuzz] The libFuzzer setup of tests/fuzz is complete and the CI runs it (docs/linux-port/upgrade-3.2/fuzz.md).

The fuzzers themselves need clang and run in the CI job `fuzz` (sh tests/docker/local-ci.sh fuzz); this test only keeps the
parts around them from rotting: every target has a harness, seeds and a dictionary that exists, the seeds in git are what
tests/fuzz/gen_seeds.py writes (plus the regression inputs, named regress-*), the CI job and the local entry exist, and
the files keep LF endings."""
import importlib.util
import os
import re
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUZZ = os.path.join(ROOT, 'tests', 'fuzz')


def text(p):
    with open(os.path.join(ROOT, p), encoding='utf-8', newline='') as f:
        return f.read()


def rb(p):
    with open(p, 'rb') as f:
        return f.read()


def targets():
    """name -> (sources, flags, dictionary) from the TARGETS table of run.sh"""
    block = re.search(r'(?s)^TARGETS="(.*?)"$', text('tests/fuzz/run.sh'), re.M).group(1)
    out = {}
    for line in block.splitlines():
        name, src, flags, d = line.split('|')
        out[name] = (src.split(), flags, d)
    return out


class Targets(unittest.TestCase):
    def test_table(self):
        t = targets()
        self.assertGreaterEqual(len(t), 13)
        for want in ('rtsp_req', 'rtsp_auth', 'rtsp_talk', 'httpfront', 'onvif_soap', 'onvif_http', 'onvif_wsd', 'mqttd',
                     'whep_stun', 'whep_sdp', 'whep_hello', 'mdns'):
            self.assertIn(want, t)

    def test_each_target_has_a_harness_seeds_and_its_dictionary(self):
        for name, (src, flags, d) in targets().items():
            self.assertTrue(os.path.exists(os.path.join(ROOT, src[0])), name)
            h = text(src[0])
            self.assertIn('LLVMFuzzerTestOneInput', h, name)
            seeds = os.path.join(FUZZ, 'corpus', name)
            self.assertTrue(os.path.isdir(seeds) and os.listdir(seeds), '%s has no seeds' % name)
            if d:
                self.assertTrue(os.path.exists(os.path.join(FUZZ, d + '.dict')), d)

    def test_whep_harness_never_includes_the_tls_code(self):
        # the WebRTC gateway is ported to Mbed TLS 3.6 by another stream: the harness depends on whep_proto.h only
        h = text('tests/fuzz/fuzz_whep.c')
        self.assertNotIn('tc100_whep.c', re.sub(r'/\*.*?\*/', '', h, flags=re.S))
        self.assertNotIn('mbedtls', h.lower().replace('mbed tls', ''))

    def test_every_harness_that_includes_a_daemon_puts_its_main_aside(self):
        for f in ('fuzz_rtsp.c', 'fuzz_onvif.c', 'fuzz_mqttd.c'):
            self.assertRegex(text('tests/fuzz/' + f), r'#define main \w+\n#include "\.\./\.\./src/')


class Seeds(unittest.TestCase):
    def test_seeds_in_git_are_what_the_generator_writes(self):
        spec = importlib.util.spec_from_file_location('gen_seeds', os.path.join(FUZZ, 'gen_seeds.py'))
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        with tempfile.TemporaryDirectory() as d:
            gen.CORPUS = d
            for fn in (gen.rtsp_seeds, gen.http_seeds, gen.onvif_seeds, gen.mqtt_seeds, gen.mdns_seeds, gen.whep_seeds):
                fn()
            made = {}
            for dp, _, files in os.walk(d):
                for f in files:
                    made[os.path.relpath(os.path.join(dp, f), d).replace(os.sep, '/')] = rb(os.path.join(dp, f))
        have = {}
        corpus = os.path.join(FUZZ, 'corpus')
        for dp, _, files in os.walk(corpus):
            for f in files:
                rel = os.path.relpath(os.path.join(dp, f), corpus).replace(os.sep, '/')
                if f.startswith('regress-'):
                    continue		# an input a fuzzer found: kept by hand
                have[rel] = rb(os.path.join(dp, f))
        self.assertEqual(sorted(made), sorted(have))
        for k in made:
            self.assertEqual(made[k], have[k], k)

    def test_seed_files_are_not_converted_by_git(self):
        self.assertRegex(text('.gitattributes'), r'(?m)^tests/fuzz/corpus/\*\* binary$')


class Wiring(unittest.TestCase):
    def test_ci_job(self):
        ci = text('.github/workflows/ci.yml')
        self.assertRegex(ci, r'(?m)^  fuzz:$')
        job = ci[ci.index('\n  fuzz:'):]
        self.assertIn('sh tests/fuzz/run.sh -t 60', job)
        self.assertIn('actions/upload-artifact@', job)		# pinned by test_ci_pinning like every action
        self.assertIn('fuzz-out/*/crash-*', job)

    def test_local_entry(self):
        s = text('tests/docker/local-ci.sh')
        self.assertIn('fuzz) run_fuzz ;;', s)
        self.assertIn('tests/fuzz/run.sh', s)

    def test_lf_endings(self):
        for dp, _, files in os.walk(FUZZ):
            if 'corpus' in dp or os.sep + 'out' in dp:
                continue
            for f in files:
                if not f.endswith(('.c', '.h', '.sh', '.py', '.dict')):
                    continue		# a __pycache__ of the seed generator
                with open(os.path.join(dp, f), 'rb') as fh:
                    self.assertNotIn(b'\r', fh.read(), f)

    def test_httpfront_only_differs_under_the_fuzz_flag(self):
        # the one change to a daemon for the harness: sc() and _start() are left out when TC100_FUZZ_HOST is defined
        s = text('src/httpfront/httpfront.c')
        self.assertEqual(s.count('TC100_FUZZ_HOST'), 2)
        self.assertIn('#ifndef TC100_FUZZ_HOST\n/* entry point', s)


if __name__ == '__main__':
    unittest.main()
