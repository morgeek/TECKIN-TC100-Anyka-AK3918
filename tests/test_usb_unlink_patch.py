"""[usb0003] kernel patch 0024 (Anyka USB host): the unlink of the active URB does not wait for an interrupt, ep0 is
finished by its own function, endpoint_disable runs under the controller lock. The driver cannot run here: these
checks keep the patch file well formed and the three fixes (and their switch) in place."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / 'patches/kernel-6.6/series'
DRIVER = 'drivers/usb/host/anyka/usb-hc.c'


def patch():
    return next(SERIES.glob('0024-usb-host-anyka-*.patch')).read_bytes()


class UsbUnlinkPatch(unittest.TestCase):
    def setUp(self):
        self.raw = patch()
        self.p = self.raw.decode('utf-8')

    def test_file(self):
        self.assertNotIn(b'\r', self.raw)
        self.assertTrue(self.p.startswith('From '))          # git am, as CI applies the series
        self.assertIn('\nSubject: [PATCH] usb: host: anyka: ', self.p)
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
        self.assertGreaterEqual(len(hunks), 6)
        for old, new, got_old, got_new in hunks:
            self.assertEqual((old, new), (got_old, got_new))

    def test_switch(self):
        # 0644 and off by default: the new behaviour is the default, the old one is one echo away
        self.assertIn('+static bool unlink_wait_irq;\n+module_param(unlink_wait_irq, bool, 0644);', self.p)
        self.assertIn('+\tbool\t\t\twait_irq = READ_ONCE(unlink_wait_irq);', self.p)

    def test_dequeue_stops_the_active_transfer_at_once(self):
        self.assertIn('-\t\t\tif (time_before_eq(akotghc->jiffies_ep0, jiffies)) {', self.p)
        self.assertIn('+\t\t\tif (!wait_irq || time_before_eq(akotghc->jiffies_ep0, jiffies)) {', self.p)
        self.assertIn('+\t\t\t\t\tif (!wait_irq || time_before_eq(akotghc->jiffies_epx[i], jiffies)) {', self.p)

    def test_rx_abort_does_not_flush_an_empty_fifo(self):
        # the old single FLUSHFIFO write stays only under the switch; by default REQPKT is withdrawn by a plain
        # write that cannot acknowledge a packet (RXPKTRDY written as 1), then the checked flush helper
        self.assertIn('+\t\t\t\t\t\t} else if (wait_irq) {\n'
                      ' \t\t\t\t\t\t\thc_index_writeb(ep->epfifo, USB_RXCSR1_FLUSHFIFO, USB_REG_RXCSR1);\n'
                      '+\t\t\t\t\t\t} else {\n', self.p)
        new = self.p[self.p.index('+\t\t\t\t\t\t} else {\n'):]
        new = new[:new.index('akotghc->active_epx[i] = NULL;')]
        order = ['u8 csr = hc_index_readb(ep->epfifo, USB_REG_RXCSR1);', 'csr &= ~USB_RXCSR1_H_REQPKT;',
                 'csr |= USB_RXCSR1_RXPKTRDY;', 'hc_index_writeb(ep->epfifo, csr, USB_REG_RXCSR1);',
                 'flush_epx_rx_fifo(ep->epfifo);']
        pos = [new.index(x) for x in order]
        self.assertEqual(pos, sorted(pos))
        self.assertNotIn('FLUSHFIFO,', new)

    def test_endpoint_reset_clears_the_toggle_of_a_mapped_idle_endpoint(self):
        both = '\n'.join(l[1:] for l in self.p.split('\n') if l[:1] in ('+', ' ') and not l.startswith('+++'))
        # the two functions by their first changed lines (their names are only in the hunk headers)
        disable = both.index('akotghc_ep\t*ep;\n\tunsigned long\t\tflags;')
        fn = both[both.index('is_out = usb_endpoint_dir_out(&hep->desc);\n\tint\t\t\tepfifo = 0;\n\tunsigned long'):disable]
        cond = fn[fn.index('} else if (!READ_ONCE(unlink_wait_irq)'):]
        for x in ('epnum_to_epfifo(&akotg_epfifo_mapping, epnum, is_out, &epfifo)',
                  'epfifo != 0 && !akotghc->active_epx[epfifo - 1]',
                  'clear_epx_tx_data_toggle(epfifo);', 'clear_epx_rx_data_toggle(epfifo);'):
            self.assertIn(x, cond)
        self.assertLess(fn.index('spin_lock_irqsave(&akotghc->lock, flags);'), fn.index('clear_epx_tx_data_toggle'))
        # an unbind keeps the device toggles: endpoint_disable must not clear them
        self.assertNotIn('data_toggle', both[disable:])

    def test_ep0_is_not_finished_as_epx(self):
        self.assertIn('-\t\t\tif (akotghc->active_ep0 == ep)\n', self.p)
        self.assertIn('+\t\t\tif (ep->epnum == 0)\n', self.p)

    def test_endpoint_disable_under_the_lock(self):
        # the function as it is after the patch: added and context lines
        added = '\n'.join(l[1:] for l in self.p.split('\n') if l[:1] in ('+', ' ') and not l.startswith('+++'))
        fn = added[added.index('akotghc_ep\t*ep;\n\tunsigned long\t\tflags;'):]
        lock = fn.index('spin_lock_irqsave(&akotghc->lock, flags);')
        unlock = fn.rindex('spin_unlock_irqrestore(&akotghc->lock, flags);')
        # the sleep is before the lock, the pointer is read, cleared and the schedules purged inside, the free is after
        self.assertLess(fn.index('msleep(3);'), lock)
        for inside in ('ep = hep->hcpriv;', 'hep->hcpriv = NULL;', 'list_del_init(&ep->schedule);',
                       'akotghc->active_epx[i] = NULL;', 'akotghc->next_async_epx[i] = NULL;',
                       'akotghc->active_ep0 = NULL;', 'akotghc->next_async_ep0 = NULL;'):
            self.assertTrue(lock < fn.index(inside) < unlock, inside)
        self.assertGreater(fn.index('kfree(ep);'), unlock)
        # the old unlocked free is removed
        self.assertIn('-\tkfree(ep);\n \thep->hcpriv = NULL;', self.p)
        # the endpoint interrupt comes back after the flush, never for ep0
        self.assertIn('if (epfifo != 0 && !READ_ONCE(unlink_wait_irq)) {', fn)

    def test_queue_entry(self):
        q = (ROOT / 'docs/linux-port/test-queue.md').read_text(encoding='utf-8')
        self.assertIn('### AUDIT-1116-USB ', q)
        self.assertIn('/sys/module/otg_hs/parameters/unlink_wait_irq', q)


if __name__ == '__main__':
    unittest.main()
