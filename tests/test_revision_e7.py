import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from crossscale.policy import decision
from crossscale.revision_e5 import run_config
from crossscale.revision_e7 import plan, execute, DEST, require_completed_e6

class E7(TestCase):
    def setUp(self):
        self.base = json.loads(Path('configs/revision-20260930.json').read_text())
        self.c = run_config(self.base, 871, .025, .8)[0]
        self.r = dict(tenant='A', input_tokens=256, offered_s=0)

    def test_actual_tenant_and_eta_policy_branches(self):
        # Four Ready slots: Gold's weighted budget is two versus uniform one.
        args = (self.r, 0, 4, 4, {'A': 1}, [])
        self.assertEqual(decision(self.c, 'B6', *args), 'admit')
        self.assertEqual(decision(self.c, 'no-tenant', *args), 'reject')
        # Near release, ETA permits waiting but never dispatch on unready GPUs.
        args = (self.r, 0, 0, 4, {}, [.01])
        for baseline in ('B6', 'no-tenant', 'oracle-eta'):
            self.assertEqual(decision(self.c, baseline, *args), 'delay')
        self.assertEqual(decision(self.c, 'B5', *args), 'reject')
        self.assertEqual(decision(self.c, 'B3', *args), 'admit')

    def test_frozen_paired_plan_and_explicit_scope(self):
        p = plan(self.base)
        self.assertEqual(p, json.loads(Path('configs/revision-20261003-e7-plan.json').read_text()))
        self.assertEqual(len(p['eval_order']), 25)
        self.assertEqual(len({tuple(x) for x in p['eval_order']}), 25)
        self.assertIn('natural slow-loop', p['scope'])
        self.assertIn('no HPA', p['supply'])

    def test_requires_all_unique_valid_e6_and_restore(self):
        from crossscale.revision_e6 import SEEDS, VARIANTS
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)/'revision-20260912/e6-eta-error'
            dest.mkdir(parents=True)
            rows = [dict(seed=s,variant=v[0],dispatch_valid=True) for s in SEEDS for v in VARIANTS]
            (dest/'complete.json').write_text(json.dumps(dict(results=rows)))
            with self.assertRaises(RuntimeError): require_completed_e6(tmp)
            (dest/'restored.json').write_text('{}')
            require_completed_e6(tmp)
            rows[-1] = rows[0]
            (dest/'complete.json').write_text(json.dumps(dict(results=rows)))
            with self.assertRaises(RuntimeError): require_completed_e6(tmp)

    def test_lock_prevents_any_destination_or_cluster_mutation(self):
        with TemporaryDirectory() as tmp:
            with (Path(tmp)/'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): execute(tmp, {})
            self.assertFalse((Path(tmp)/DEST).exists())
