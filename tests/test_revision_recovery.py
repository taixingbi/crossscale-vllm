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

class TerminalRecoveryTests(unittest.TestCase):
    def test_preserved_failure_requires_complete_unchanged_archived_evidence(self):
        import hashlib
        plan = json.loads(Path('configs/revision-20260912/e1-mixed-plan.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mixed = root/'revision-20260912/e1-mixed'
            cont = mixed.parent/'e1-mixed-continuation-20260930'
            checkpoint = mixed.parent/'e1-mixed-terminal'
            def save(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            for folder in (mixed, cont):
                save(folder/'frozen-plan.json', plan)
                save(folder/'restored.json', dict(unix_s=2))
            save(mixed/'error.json', dict(error='observer failure'))
            entries, continued = [], []
            for i, spec in enumerate(plan['runs']):
                folder = (mixed if i < 28 else cont)/spec['name']
                outcome = 'failed_observer' if i == 27 else 'completed'
                entries.append(dict(name=spec['name'], outcome=outcome,
                                    path=str(folder.relative_to(root))))
                if i == 27:
                    save(folder/'observer-error.json', dict(error='nodeclaims HTTP 429 storage is (re)initializing'))
                    save(folder/'run/requests.jsonl', dict(status='completed'))
                else:
                    record = {k: spec[k] for k in ('name', 'replicas', 'rps', 'seed', 'offered_by_tenant')}
                    save(folder/'complete.json', record)
                    if i >= 28:
                        continued.append(record)
            save(cont/'complete.json', dict(results=continued, continuation_only=True,
                                           capacities=None, completed_unix_s=1))
            save(checkpoint/'terminal-ledger.json', dict(completed=29, failed=1, unstarted=0, runs=entries))
            files = []
            for folder in (mixed, cont):
                for p in folder.rglob('*'):
                    if p.is_file():
                        rel = str(p.relative_to(root))
                        files.append(dict(path=rel, bytes=p.stat().st_size,
                                          sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                                          s3_uri='s3://crossscale-experiment-results-646821141010-us-east-1/full-20260908/'+rel))
            save(checkpoint/'archive-manifest.json', dict(files=files))
            self.assertEqual(require_completed_mixed(root), mixed)
            last = cont/plan['runs'][-1]['name']/'complete.json'
            original = last.read_text()
            last.unlink()
            with self.assertRaises(RuntimeError):
                require_completed_mixed(root)
            last.write_text(original+' ')
            with self.assertRaises(RuntimeError):
                require_completed_mixed(root)
            last.write_text(original)
            save(mixed/plan['runs'][27]['name']/'complete.json', {})
            with self.assertRaises(RuntimeError):
                require_completed_mixed(root)

class RemainingConditionTests(unittest.TestCase):
    def test_only_untouched_fourth_condition_is_selected(self):
        from crossscale.revision_recovery import remaining_recovery_condition, RECOVERY
        plan = dict(conditions=[dict(name=n) for n in ('a', 'b', 'c', 'd')],
                    cases=[dict(name='case')], repetitions=1)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'revision-20260912'/RECOVERY
            source.mkdir(parents=True)
            def save(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            save(source/'frozen-plan.json', plan)
            save(source/'error.json', dict(error="TimeoutError('Diagnostic rollout did not become Ready within 2400 seconds')", unix_s=1))
            save(source/'restored.json', dict(unix_s=2))
            for name in ('a', 'b'):
                save(source/name/'complete.json', dict(results=[dict(case='case', repetition=0,
                      request=dict(status='completed'), dispatch_valid=True)]))
            (source/'c').mkdir()
            self.assertEqual(remaining_recovery_condition(tmp, plan), [dict(name='d')])
            (source/'d').mkdir()
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                remaining_recovery_condition(tmp, plan)
            (source/'d').rmdir()
            (source/'restored.json').unlink()
            with self.assertRaises(FileNotFoundError):
                remaining_recovery_condition(tmp, plan)
