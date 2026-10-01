import json
from pathlib import Path
from unittest import TestCase
from crossscale.revision_e5 import capacity_state, plan, run_config


class ControlledCapacity(TestCase):
    def snapshot(self, now, nready=2):
        return dict(observed_unix_s=now, deployment=dict(spec=dict(replicas=4)),
                    pods=[dict(metadata=dict(uid=str(i)), status=dict(conditions=[
                        dict(type='Ready', status='True' if i < nready else 'False')]))
                          for i in range(4)])

    def test_elapsed_eta_does_not_create_capacity(self):
        before=capacity_state(self.snapshot(59), ['0','1'], ['2','3'], 0, 30)
        self.assertEqual((before['ready'],before['desired'],before['pending_eta_unix_s']), (2,2,[]))
        pending=capacity_state(self.snapshot(91), ['0','1'], ['2','3'], 0, 30)
        self.assertEqual(pending['ready'], 2)
        self.assertEqual(pending['pending_eta_unix_s'], [90,90])
        released=capacity_state(self.snapshot(92,4), ['0','1'], ['2','3'], 0, 30)
        self.assertEqual((released['ready'],released['pending_eta_unix_s']), (4,[]))

    def test_early_release_or_capacity_loss_rejected(self):
        for snap in (self.snapshot(80,4), self.snapshot(80,1)):
            with self.assertRaises(RuntimeError):
                capacity_state(snap, ['0','1'], ['2','3'], 0, 30)
        snap=self.snapshot(91);snap['pods'][3]['metadata']['uid']='replacement'
        with self.assertRaises(RuntimeError):
            capacity_state(snap, ['0','1'], ['2','3'], 0, 30)

    def test_plan_pairs_all_conditions_without_changing_trace(self):
        base=json.loads(Path('configs/revision-20260930.json').read_text())
        frozen=plan(base)
        self.assertEqual(len({tuple(x) for x in frozen['eval_order']}),90)
        for seed in frozen['eval_seeds']:
            left=run_config(base,seed,.025,.8)
            self.assertTrue(all(left[2].values()))
            self.assertEqual(left[1],run_config(base,seed,.025,1.2)[1])
