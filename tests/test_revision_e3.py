import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from crossscale.revision_e3 import (
    DEST,
    E2_DEST,
    b5_b6_differ_only_by_eta,
    e3_config,
    execute,
    plan,
    require_admission_calibration,
    require_completed_e2,
    wait_then_execute,
)


def _amended(root):
    root = Path(root)
    (root / 'revision-20260930').mkdir(parents=True)
    (root / 'revision-20260930' / 'requalified-mixed-ledger.json').write_text(json.dumps({
        'slo_revision': 'revision-20260930-b-ttft-3s',
        'qualified_capacity': {'1': 0.025, '2': 0.025},
    }))
    (root / 'admission-prefill4096').mkdir()
    (root / 'admission-prefill4096' / 'admission-calibration.json').write_text(json.dumps({
        'prefill_tokens_s': 3305.8201319531686,
        'slots_per_replica': 1,
    }))
    (root / 'suite.lock').write_text('')
    return root


def _e2(root, *, complete=True, restored=True, failed=False, threshold=1.0):
    dest = Path(root) / E2_DEST
    dest.mkdir(parents=True)
    (dest / 'frozen-plan.json').write_text(json.dumps({'capacity_rps': 0.025}))
    if failed:
        (dest / 'error.json').write_text(json.dumps({'error': 'training failed'}))
    if complete:
        (dest / 'complete.json').write_text(json.dumps({'ok': True}))
        (dest / 'slo-tuning.json').write_text(json.dumps({
            'selected_threshold': threshold, 'candidates': [{'threshold': threshold, 'mean_wg': 0.5}],
        }))
    if restored:
        (dest / 'restored.json').write_text(json.dumps({'ok': True}))
    return dest


class E3Plan(TestCase):
    def test_priority_trio_and_admission_calibration(self):
        from crossscale.core import workload
        base = json.loads(Path('configs/revision-20260930.json').read_text())
        frozen = plan(base, 0.025)
        self.assertEqual(frozen['baselines'], ['B3', 'B5', 'B6'])
        self.assertEqual(frozen['eval_seeds'], [821, 822, 824, 826, 828])
        self.assertEqual(frozen['capacity_rps'] * frozen['low_factor'], 0.01625)
        self.assertEqual(frozen['capacity_rps'] * frozen['high_factor'], 0.04125)
        self.assertEqual(frozen['practical_effect'], 0.05)
        self.assertEqual(frozen['slots_per_replica'], 1)
        self.assertEqual(frozen['admission_policy_revision'], 'revision-20260912')
        self.assertNotIn('B2', {b for _, b in frozen['eval_order']})
        self.assertNotIn('B4', {b for _, b in frozen['eval_order']})
        self.assertEqual(len(frozen['eval_order']), 15)
        self.assertEqual({tuple(x) for x in frozen['eval_order']},
                         {(s, b) for s in frozen['eval_seeds'] for b in ('B3', 'B5', 'B6')})
        left, _, _ = e3_config(base, frozen['eval_seeds'][0], 0.025, 1)
        right, _, _ = e3_config(base, frozen['eval_seeds'][0], 0.025, 0.8)
        self.assertEqual(left['admission_policy_revision'], 'revision-20260912')
        self.assertEqual(left['slots_per_replica'], 1)
        self.assertEqual([{k: r[k] for k in ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')}
                          for r in workload(left)],
                         [{k: r[k] for k in ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')}
                          for r in workload(right)])
        b5_b6_differ_only_by_eta(left)
        with self.assertRaises(ValueError):
            plan(json.loads(Path('configs/default.json').read_text()), 0.025)


class E3Gate(TestCase):
    def test_failed_e2_without_complete_refuses_execute(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root, complete=False, restored=False, failed=True)
            with self.assertRaisesRegex(RuntimeError, 'E2 failed; E3 not started'):
                execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / DEST).exists())

    def test_incomplete_e2_refuses_execute(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root, complete=False, restored=False)
            with self.assertRaisesRegex(RuntimeError, 'E2 must complete'):
                execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / DEST).exists())

    def test_held_lock_blocks_before_destination(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root)
            with (root / 'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / DEST).exists())

    def test_waiter_aborts_on_failed_e2(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root, complete=False, restored=False, failed=True)
            with self.assertRaisesRegex(RuntimeError, 'E2 failed; E3 not started'):
                wait_then_execute(root, dict(capacity_rps=0.025), poll_s=0)
            self.assertTrue((root / 'revision-20260912/e3-waiter-error.json').exists())
            self.assertFalse((root / DEST).exists())
            self.assertTrue((root / 'e3-waiter.pid').exists())

    @mock.patch('crossscale.revision_e3._run_suite')
    def test_execute_uses_e2_threshold_after_restore(self, run):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root, threshold=1.2)
            execute(root, dict(capacity_rps=0.025))
            self.assertEqual(run.call_args.args[3], 1.2)
            self.assertTrue((root / DEST / 'frozen-plan.json').exists())

    def test_calibration_mismatch_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            (root / 'admission-prefill4096' / 'admission-calibration.json').write_text(json.dumps({
                'prefill_tokens_s': 6000, 'slots_per_replica': 8,
            }))
            with self.assertRaisesRegex(RuntimeError, 'slots_per_replica'):
                require_admission_calibration(root)
            _e2(root)
            with self.assertRaisesRegex(RuntimeError, 'does not match admission'):
                execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / DEST).exists())

    def test_require_completed_e2_reads_threshold(self):
        with TemporaryDirectory() as tmp:
            root = _amended(tmp)
            _e2(root, threshold=0.8)
            self.assertEqual(require_completed_e2(root), 0.8)
