import json
import hashlib
import tempfile
from pathlib import Path
import unittest

from crossscale.core import workload
from crossscale.revision_mixed import plan, qualifies, capacity, freeze


class MixedPlanTests(unittest.TestCase):
    def test_freeze_records_runtime_and_refuses_overwrite(self):
        base = json.loads(Path('configs/default.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.json'
            report = freeze(base, [.01], path)
            original = path.read_bytes()
            self.assertEqual(report['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(report['runs'], 10)
            self.assertAlmostEqual(report['arrival_hours'], 700000/3600)
            self.assertAlmostEqual(report['minimum_runtime_hours'],
                                   (700000+10*base['drain_s'])/3600)
            self.assertFalse(report['execution_started'])
            with self.assertRaises(FileExistsError):
                freeze(base, [.02], path)
            self.assertEqual(path.read_bytes(), original)

    def test_paired_traces_and_sample_sufficiency(self):
        base = json.loads(Path('configs/default.json').read_text())
        frozen = plan(base, [.01, .02])
        self.assertEqual(len(frozen['runs']), 20)
        for one, two in zip(frozen['runs'][:10], frozen['runs'][10:]):
            self.assertEqual(workload(one['config']), workload(two['config']))
            self.assertGreaterEqual(min(one['offered_by_tenant'].values()), 60)
            self.assertEqual(two['config']['max_replicas'], 2)

    def test_missing_tenant_and_dispatch_lag_cannot_pass(self):
        summary = {'tenants': {t: {'offered': 60, 'goodput': 1} for t in 'ABC'}}
        rows = [{'dispatch_lag_s': .001}]
        self.assertEqual(qualifies(summary, rows), (True, True))
        summary['tenants']['C']['offered'] = 0
        self.assertEqual(qualifies(summary, rows), (True, False))
        self.assertEqual(qualifies(summary, [{}]), (False, False))

    def test_capacity_requires_every_seed_and_lower_rate(self):
        frozen = {'rates': [.01, .02], 'seeds': [701, 702, 703, 704, 705]}
        records = [dict(replicas=2, rps=r, seed=s, passed=True, dispatch_valid=True)
                   for r in frozen['rates'] for s in frozen['seeds']]
        self.assertEqual(capacity(records, frozen, 2), .02)
        self.assertIsNone(capacity(records, frozen, 1))
        records[5]['passed'] = False
        self.assertEqual(capacity(records, frozen, 2), .01)
        self.assertIsNone(capacity(records[1:], frozen, 2))


if __name__ == '__main__':
    unittest.main()
