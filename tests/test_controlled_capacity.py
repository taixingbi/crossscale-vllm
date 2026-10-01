from unittest import TestCase, mock
from crossscale.controlled_capacity import GateDriver

class DriverTests(TestCase):
    def snapshot(self, now, ready_count):
        return dict(observed_unix_s=now,deployment=dict(spec=dict(replicas=4)),
                    pods=[dict(metadata=dict(uid=str(i)),status=dict(conditions=[dict(type='Ready',status='True' if i<ready_count else 'False')])) for i in range(4)])
    def driver(self, routed):
        k=mock.Mock();k.get.return_value={'items':[{'endpoints':[{'targetRef':{'uid':str(i)},'conditions':{'ready':True}} for i in range(routed)]}]}
        d=GateDriver(k,'owner',['0','1'],['2','3'],30);d.on_start(0);return d
    @mock.patch('crossscale.controlled_capacity.patch_gate')
    @mock.patch('crossscale.controlled_capacity.time.time',return_value=91)
    def test_ready_and_routes_both_required(self, clock, patch):
        d=self.driver(2)
        state=d(self.snapshot(91,4))
        self.assertIsNone(d.observed_release)
        self.assertEqual(state['ready'],4)
        d=self.driver(4);d(self.snapshot(91,4));self.assertEqual(d.observed_release,91)
    @mock.patch('crossscale.controlled_capacity.patch_gate')
    @mock.patch('crossscale.controlled_capacity.time.time',return_value=96)
    def test_late_observed_release_rejected_even_if_now_ready(self, clock, patch):
        with self.assertRaisesRegex(RuntimeError,'tolerance'):
            self.driver(4)(self.snapshot(96,4))
    @mock.patch('crossscale.controlled_capacity.time.time',return_value=89)
    def test_endpoint_leak_detected(self, clock):
        with self.assertRaisesRegex(RuntimeError,'routed before release'):
            self.driver(3)(self.snapshot(89,2))
