import copy
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from crossscale.revision_recovery import build_plan, condition_containers, require_completed_mixed, execute


class RecoveryTests(unittest.TestCase):
    def test_active_suite_lock_blocks_execution_before_any_cluster_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (Path(tmp)/'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    execute(tmp, {})
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['suite.lock'])

    def test_plan_preserves_every_failed_prompt_id_and_fixes_conditions(self):
        base = json.loads(Path('configs/default.json').read_text())
        rows = [dict(id=23, tenant='B', offered_s=1, input_tokens=6309, output_tokens=256,
                     status='completed', dispatch_lag_s=.001, ttft_s=1.7),
                dict(id=24, tenant='A', offered_s=10, input_tokens=256, output_tokens=128,
                     status='completed', dispatch_lag_s=.001, ttft_s=.1)]
        with tempfile.TemporaryDirectory() as tmp:
            for n in (1, 2):
                folder = Path(tmp) / f'mixed-gpu-{n}-rps-0.01-seed-704/run'
                folder.mkdir(parents=True)
                (folder/'requests.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            plan = build_plan(base, tmp)
            self.assertEqual(plan['cases'][0]['request']['id'], 23)
            self.assertEqual(plan['cases'][0]['request']['input_tokens'], 6309)
            self.assertEqual(len(plan['cases']), 5)
            self.assertEqual(plan['repetitions'], 3)
            self.assertEqual([(c['batch_tokens'], c['eager']) for c in plan['conditions']],
                             [(4096, True), (8192, True), (4096, False), (8192, False)])
            self.assertEqual(plan['config']['tenants'], base['tenants'])
            rows[0]['ttft_s'] = 1.4
            (folder/'requests.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            with self.assertRaisesRegex(ValueError, 'failure sets'):
                build_plan(base, tmp)

    def test_variant_does_not_change_model_context_or_original(self):
        containers = [dict(image='pinned-image', args=['/models/llama', '--max-model-len', '32768',
                           '--max-num-batched-tokens', '1024', '--enforce-eager'])]
        before = copy.deepcopy(containers)
        compiled = condition_containers(containers, dict(batch_tokens=8192, eager=False))
        self.assertEqual(containers, before)
        self.assertEqual(compiled[0]['image'], 'pinned-image')
        self.assertNotIn('--enforce-eager', compiled[0]['args'])
        self.assertIn('32768', compiled[0]['args'])
        self.assertIn('8192', compiled[0]['args'])

    def test_active_incomplete_duplicate_and_failed_suites_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'revision-20260912/e1-mixed'
            folder.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                require_completed_mixed(tmp)
            runs = [dict(name=str(n)) for n in range(30)]
            (folder/'frozen-plan.json').write_text(json.dumps(dict(runs=runs)))
            (folder/'complete.json').write_text(json.dumps(dict(results=runs)))
            with self.assertRaises(RuntimeError):
                require_completed_mixed(tmp)
            (folder/'restored.json').write_text('{}')
            self.assertEqual(require_completed_mixed(tmp), folder)
            (folder/'complete.json').write_text(json.dumps(dict(results=runs[:-1]+[runs[0]])))
            with self.assertRaises(RuntimeError):
                require_completed_mixed(tmp)
            (folder/'complete.json').write_text(json.dumps(dict(results=runs)))
            (folder/'error.json').write_text('{}')
            with self.assertRaises(RuntimeError):
                require_completed_mixed(tmp)
