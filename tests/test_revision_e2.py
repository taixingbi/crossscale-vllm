import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from crossscale.revision_e2 import (
    batch_increase_cannot_meet_slo,
    diagnostic_b_tails,
    execute,
    prefill_slo_infeasibility,
    require_qualified_two_gpu_capacity,
)

LIVE = Path('results/full-experiments-20260908/run')


def _write_unqualified(root, rows=None, capacity=None):
    root = Path(root)
    ledger = root / 'revision-20260912/e1-mixed-terminal'
    ledger.mkdir(parents=True)
    (ledger / 'terminal-ledger.json').write_text(json.dumps(dict(
        completed=29, failed=1, unstarted=0,
        qualified_capacity={'1': None, '2': capacity},
        capacity_reason='Lowest tested rate .01 seed704 fails tenant B on both replica counts; higher rates cannot qualify under frozen consecutive-rate rule.',
    )))
    if rows is None:
        rows = [dict(input_tokens=5888, ttft_s=1.479), dict(input_tokens=10131, ttft_s=2.761)]
    dest = root / 'revision-20260912/e2-serving-recovery-20260927/batch8192-eager'
    dest.mkdir(parents=True)
    (dest / 'complete.json').write_text(json.dumps(dict(results=[
        dict(case=f'B-source-704-id-{i}', repetition=0, request=dict(id=i, **row))
        for i, row in enumerate(rows)
    ])))
    (root / 'suite.lock').write_text('')
    return root


class PrefillFloor(unittest.TestCase):
    def test_longest_prompt_exceeds_slo_token_budget(self):
        floor = prefill_slo_infeasibility([
            dict(input_tokens=5888, ttft_s=1.479),
            dict(input_tokens=10131, ttft_s=2.761),
        ])
        self.assertTrue(floor['infeasible'])
        self.assertGreater(floor['longest_prompt_tokens'], floor['tokens_coverable_in_slo'])
        self.assertGreater(floor['longest_prompt_required_tokens_s'], floor['slo_ttft_s'])

    def test_larger_batch_is_not_justified_when_prefill_work_exceeds_slo(self):
        analysis = batch_increase_cannot_meet_slo([
            dict(input_tokens=5888, ttft_s=1.52),
            dict(input_tokens=6836, ttft_s=1.75),
            dict(input_tokens=10131, ttft_s=2.76),
        ])
        self.assertFalse(analysis['justified'])
        self.assertEqual(analysis['misses_already_one_chunk'], 2)
        self.assertGreater(analysis['longest_prompt_prefill_s'], 1.5)


class E2Gate(unittest.TestCase):
    def test_unqualified_mixed_capacity_refuses_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unqualified(tmp)
            with self.assertRaisesRegex(RuntimeError, 'seed704 fails tenant B'):
                require_qualified_two_gpu_capacity(root)
            with self.assertRaisesRegex(RuntimeError, 'Do not substitute isolated rates'):
                execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / 'revision-20260912/e2-b2-b3').exists())

    def test_plan_mismatch_is_rejected_before_live_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unqualified(tmp, capacity=0.025)
            with self.assertRaisesRegex(RuntimeError, 'does not match qualified'):
                execute(root, dict(capacity_rps=0.01))
            self.assertFalse((root / 'revision-20260912/e2-b2-b3').exists())

    def test_held_lock_blocks_before_capacity_or_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_unqualified(tmp, capacity=0.025)
            with (root / 'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    execute(root, dict(capacity_rps=0.025))
            self.assertFalse((root / 'revision-20260912/e2-b2-b3').exists())


class E2Plan(unittest.TestCase):
    def test_paired_traces_and_nonempty_seed_scan(self):
        from crossscale.core import workload
        from crossscale.revision_e2 import plan, run_config
        base = json.loads(Path('configs/revision-20260930.json').read_text())
        frozen = plan(base, 0.025)
        self.assertEqual(frozen['training_seeds'], [802, 803])
        self.assertEqual(frozen['eval_seeds'], [811, 812, 813, 816, 818])
        self.assertEqual(frozen['capacity_rps'] * frozen['low_factor'], 0.01625)
        self.assertEqual(frozen['capacity_rps'] * frozen['high_factor'], 0.04125)
        self.assertEqual(len(frozen['eval_order']), 10)
        self.assertEqual({tuple(x) for x in frozen['eval_order']},
                         {(s, b) for s in frozen['eval_seeds'] for b in ('B2', 'B3')})
        left, _, _ = run_config(base, frozen['eval_seeds'][0], 0.025, 1)
        right, _, _ = run_config(base, frozen['eval_seeds'][0], 0.025, 0.8)
        self.assertEqual([{k: r[k] for k in ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')}
                          for r in workload(left)],
                         [{k: r[k] for k in ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')}
                          for r in workload(right)])
        with self.assertRaises(ValueError):
            plan(json.loads(Path('configs/default.json').read_text()), 0.025)


class LiveEvidence(unittest.TestCase):
    def test_8192_eager_b_tails_cannot_meet_b_slo(self):
        complete = LIVE / 'revision-20260912/e2-serving-recovery-20260927/batch8192-eager/complete.json'
        if not complete.exists():
            self.skipTest('live 8192-eager diagnostic is not present')
        analysis = batch_increase_cannot_meet_slo(diagnostic_b_tails(LIVE))
        self.assertTrue(analysis['infeasible'])
        self.assertFalse(analysis['justified'])
        self.assertGreaterEqual(analysis['ttft_misses'], 13)
        self.assertGreaterEqual(analysis['misses_already_one_chunk'], 12)
        self.assertGreater(analysis['longest_prompt_tokens'], 10000)

    def test_original_1s5_ledger_remains_unqualified(self):
        ledger = LIVE / 'revision-20260912/e1-mixed-terminal/terminal-ledger.json'
        if not ledger.exists():
            self.skipTest('terminal mixed ledger is not present')
        payload = json.loads(ledger.read_text())
        self.assertIsNone(payload['qualified_capacity']['2'])
        self.assertIsNone(payload['qualified_capacity']['1'])

    def test_amended_slo_unblocks_two_gpu_capacity_gate(self):
        amended = LIVE / 'revision-20260930/requalified-mixed-ledger.json'
        if not amended.exists():
            self.skipTest('amendment ledger is not present')
        self.assertEqual(require_qualified_two_gpu_capacity(LIVE), 0.025)
