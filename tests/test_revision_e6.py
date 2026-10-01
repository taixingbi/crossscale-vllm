import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crossscale.revision_e5 import capacity_state
from crossscale.revision_e6 import (
    DEST,
    E5_DEST,
    LAG_S,
    apply_eta_variant,
    execute,
    plan,
    require_completed_e5,
    wait_then_execute,
)


def _snap(now, nready=2):
    return dict(observed_unix_s=now, deployment=dict(spec=dict(replicas=4)),
                pods=[dict(metadata=dict(uid=str(i)), status=dict(conditions=[
                    dict(type='Ready', status='True' if i < nready else 'False')]))
                      for i in range(4)])


class EtaVariant(TestCase):
    def test_errors_change_only_perceived_eta(self):
        raw = capacity_state(_snap(91), ['0', '1'], ['2', '3'], 0, LAG_S)
        self.assertEqual(raw['ready'], 2)
        self.assertEqual(raw['desired'], 4)
        self.assertEqual(raw['pending_eta_unix_s'], [120, 120])
        none = apply_eta_variant(raw, 0, LAG_S, None)
        self.assertEqual(none['pending_eta_unix_s'], [])
        self.assertEqual(none['ready'], 2)
        zero = apply_eta_variant(raw, 0, LAG_S, 0.0)
        oracle = apply_eta_variant(raw, 0, LAG_S, 'oracle')
        self.assertEqual(zero['pending_eta_unix_s'], oracle['pending_eta_unix_s'])
        self.assertEqual(zero['pending_eta_unix_s'], [120, 120])
        early = apply_eta_variant(raw, 0, LAG_S, -0.5)
        late = apply_eta_variant(raw, 0, LAG_S, 0.5)
        self.assertEqual(early['pending_eta_unix_s'], [90, 90])
        self.assertEqual(late['pending_eta_unix_s'], [150, 150])
        self.assertEqual(early['ready'], raw['ready'])
        self.assertEqual(late['desired'], raw['desired'])


class E6Plan(TestCase):
    def test_pairs_seven_variants_on_e5_traces(self):
        base = json.loads(Path('configs/revision-20260930.json').read_text())
        e5 = json.loads(Path('configs/revision-20261001-e5-plan.json').read_text())
        frozen = plan(base, e5)
        self.assertEqual(frozen['eval_seeds'], [871, 872, 873, 874, 875])
        self.assertEqual(frozen['lag_s'], 60)
        self.assertEqual(frozen['practical_effect'] if False else frozen['analysis']['practical_effect'], 0.05)
        self.assertEqual(len(frozen['eval_order']), 35)
        self.assertEqual({tuple(x) for x in frozen['eval_order']},
                         {(s, v) for s in frozen['eval_seeds'] for v in frozen['variants']})
        self.assertEqual(frozen['traces'], e5['traces'])
        self.assertIn('no-eta', frozen['variants'])
        self.assertIn('oracle', frozen['variants'])
        self.assertEqual(frozen['eta_errors'], [-0.5, -0.25, 0.0, 0.25, 0.5])


class E6Gate(TestCase):
    def _e5(self, root, *, complete=True, restored=True, failed=False, n=90):
        dest = Path(root) / E5_DEST
        dest.mkdir(parents=True)
        (dest / 'frozen-plan.json').write_text('{}')
        if failed:
            (dest / 'error.json').write_text(json.dumps({'error': 'late release'}))
        if complete:
            (dest / 'complete.json').write_text(json.dumps({
                'results': [dict(dispatch_valid=True, seed=i) for i in range(n)],
            }))
        if restored:
            (dest / 'restored.json').write_text(json.dumps({'ok': True}))
        (Path(root) / 'suite.lock').write_text('')
        return dest

    def test_failed_e5_refuses_execute(self):
        with TemporaryDirectory() as tmp:
            self._e5(tmp, complete=False, restored=False, failed=True)
            with self.assertRaisesRegex(RuntimeError, 'E5 failed; E6 not started'):
                require_completed_e5(tmp)
            with self.assertRaisesRegex(RuntimeError, 'E5 failed; E6 not started'):
                wait_then_execute(tmp, {}, poll_s=0)
            self.assertTrue((Path(tmp) / 'revision-20260912/e6-waiter-error.json').exists())
            self.assertFalse((Path(tmp) / DEST).exists())

    def test_incomplete_e5_refuses(self):
        with TemporaryDirectory() as tmp:
            self._e5(tmp, complete=False, restored=False)
            with self.assertRaisesRegex(RuntimeError, 'E5 must complete'):
                require_completed_e5(tmp)

    def test_held_lock_blocks_before_destination(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._e5(root)
            (root / 'configs/revision-20260930.json').parent.mkdir(parents=True)
            (root / 'configs/revision-20260930.json').write_text(
                Path('configs/revision-20260930.json').read_text())
            with (root / 'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    execute(root, dict(phase='mismatch'))
            self.assertFalse((root / DEST).exists())
