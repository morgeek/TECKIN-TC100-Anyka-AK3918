"""[venc-irq] kernel patch 0025 (ak39_venc): the encoder interrupt is masked at the controller when it is disarmed
(IRQ_DISABLE_UNLAZY), so a late interrupt is not noted as pending and replayed at the next AKUIO_WAIT_IRQ. The driver
cannot run here: these checks keep the patch file well formed, the fix and its switch in place, and the assumptions
it rests on (level flow handler, controller without acknowledge, status cleared by user space) true in the tree."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / 'patches/kernel-6.6/series'
DRIVER = 'drivers/misc/ak39_venc.c'


def one(pattern):
    found = sorted(SERIES.glob(pattern))
    if len(found) != 1:
        raise AssertionError((pattern, found))
    return found[0]


class VencIrqPatch(unittest.TestCase):
    def setUp(self):
        self.raw = one('0025-misc-ak39_venc-*.patch').read_bytes()
        self.p = self.raw.decode('utf-8')

    def test_file(self):
        self.assertNotIn(b'\r', self.raw)
        self.assertTrue(self.p.startswith('From '))          # git am, as CI applies the series
        self.assertIn('\nSubject: [PATCH] misc: ak39_venc: ', self.p)
        self.assertEqual(re.findall(r'^diff --git a/(\S+) ', self.p, re.M), [DRIVER])

    def test_hunk_counts(self):
        # every hunk header matches its body (a hand-edited patch with a wrong count does not apply)
        body = self.p.split('\ndiff --git ', 1)[1].split('\n-- \n')[0].split('\n')
        hunks, cur = [], None
        for line in body:
            m = re.match(r'@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@', line)
            if m:
                cur = [int(m.group(1) or 1), int(m.group(2) or 1), 0, 0]
                hunks.append(cur)
            elif cur is not None:
                if line.startswith('-') or line.startswith(' ') or line == '':
                    cur[2] += 1
                if line.startswith('+') or line.startswith(' ') or line == '':
                    cur[3] += 1
        self.assertEqual(len(hunks), 5)
        for old, new, got_old, got_new in hunks:
            self.assertEqual((old, new), (got_old, got_new))

    def test_only_additions(self):
        # the arm/mask accounting of the driver (irq_armed under v->lock) is not rewritten
        removed = [l for l in self.p.split('\ndiff --git ', 1)[1].split('\n')
                   if l.startswith('-') and not l.startswith('---') and l != '-- ']
        self.assertEqual(removed, [])

    def test_switch(self):
        # 0644 and on by default: the fix is the default, the lazy disable is one echo away
        self.assertIn('+static bool irq_unlazy = true;\n+module_param(irq_unlazy, bool, 0644);', self.p)
        self.assertIn('+\tbool want = READ_ONCE(irq_unlazy);', self.p)

    def test_fix(self):
        self.assertIn('+\t\tirq_set_status_flags(v->irq, IRQ_DISABLE_UNLAZY);', self.p)
        self.assertIn('+\t\tirq_clear_status_flags(v->irq, IRQ_DISABLE_UNLAZY);', self.p)
        # applied at probe, and again before every arm (the line is disabled there: the flag is read by the
        # next disable)
        self.assertIn(' \tirq_set_status_flags(v->irq, IRQ_NOAUTOEN);\n+\tak39_venc_irq_mode(v);', self.p)
        self.assertIn(' \t\treinit_completion(&v->irq_done);\n+\t\tak39_venc_irq_mode(v);\n'
                      ' \t\tenable_irq(v->irq);', self.p)

    def test_series_order(self):
        # 0025 is written on top of the three patches that touch the driver
        touching = [f.name[:4] for f in sorted(SERIES.glob('0*.patch'))
                    if ('diff --git a/%s ' % DRIVER) in f.read_text(encoding='utf-8')]
        self.assertEqual(touching, ['0008', '0015', '0017', '0025'])


class Assumptions(unittest.TestCase):
    """what makes masking safe: nothing but a level can reach the handler, and the level stays until user space
    clears it"""

    def test_controller_is_level_without_acknowledge(self):
        p = one('0001-*.patch').read_text(encoding='utf-8')
        chip = re.search(r'\+static struct irq_chip ak39_chip = \{.*?\n\+\};', p, re.S).group(0)
        self.assertIn('.irq_mask', chip)
        self.assertIn('.irq_unmask', chip)
        self.assertNotIn('irq_ack', chip)
        self.assertNotIn('irq_disable', chip)                # a chip callback would bypass the lazy/unlazy choice
        self.assertIn('handle_level_irq);', p)
        self.assertNotIn('IRQ_LEVEL', p)                     # why the IRQ core replayed a pending note
        # the pending set is the live status under the mask: no latch to lose an interrupt in
        self.assertIn('readl_relaxed(ak39_base + AK39_INT_STATUS) &\n+\t\t\t  readl_relaxed(ak39_base + AK39_IRQ_MASK);', p)

    def test_driver_disarms_with_disable_irq_nosync(self):
        p = one('0008-*.patch').read_text(encoding='utf-8')
        self.assertEqual(p.count('\tdisable_irq_nosync('), 3)      # handler, last close, timeout / signal
        self.assertEqual(p.count('+\t\tenable_irq(v->irq);'), 1)
        self.assertIn('+\tirq_set_status_flags(v->irq, IRQ_NOAUTOEN);', p)

    def test_user_space_clears_the_end_status(self):
        lib = (ROOT / 'src/libakuio/libakuio.c').read_text(encoding='utf-8')
        self.assertIn('*res = st ? __builtin_ctz(st) : 0;', lib)   # a replayed wait reads 0: looks like a success
        self.assertIn('volatile uint32_t *s18 = (volatile uint32_t *)(regs + 0x8018);', lib)
        fe = (ROOT / 'src/h265enc/freeenc.h').read_text(encoding='utf-8')
        self.assertIn('FE_WR(e, 0x8018, e->dbg[3]);', fe)

    def test_queue_entry(self):
        q = (ROOT / 'docs/linux-port/test-queue.md').read_text(encoding='utf-8')
        self.assertIn('### AUDIT-1116-VENCIRQ ', q)
        self.assertIn('/sys/module/ak39_venc/parameters/irq_unlazy', q)


if __name__ == '__main__':
    unittest.main()
