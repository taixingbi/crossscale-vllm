import json
from pathlib import Path
import unittest

from crossscale.core import summarize
from crossscale.revision_e1 import plan, qualifies, capacity, RATES, SEEDS


class RevisionE1Tests(unittest.TestCase):
    def test_frozen_traces_have_samples_and_only_active_tenant(self):
        base = json.loads(Path('configs/default.json').read_text())
        frozen = plan(base)
        self.assertEqual(len(frozen['runs']), 90)
        for spec in frozen['runs']:
            self.assertGreaterEqual(spec['offered'], 60)
            rates = spec['config']['phases'][0]['rates']
            self.assertEqual([t for t in rates if rates[t] > 0], [spec['tenant']])
        self.assertEqual(base['initial_replicas'], 2)

    def test_inactive_tenants_do_not_disqualify_but_failures_do(self):
        c = json.loads(Path('configs/default.json').read_text())
        rows = [dict(tenant='B', status='completed', dispatch_lag_s=.001,
                     ttft_s=1, tpot_s=.01, output_tokens=10) for _ in range(60)]
        self.assertEqual(qualifies(summarize(rows, c), rows, 'B'), (True, True))
        for row in rows[:4]:
            row['status'] = 'timeout'
        self.assertEqual(qualifies(summarize(rows, c), rows, 'B'), (True, False))
        rows[0]['dispatch_lag_s'] = .051
        self.assertEqual(qualifies(summarize(rows, c), rows, 'B'), (False, False))

    def test_consecutive_rate_and_complete_seed_requirements(self):
        records = [dict(tenant='A', rps=r, seed=s, passed=True) for r in RATES['A'] for s in SEEDS]
        records[5]['passed'] = False
        self.assertEqual(capacity(records, 'A'), RATES['A'][0])
        self.assertIsNone(capacity(records[1:], 'A'))


if __name__ == '__main__':
    unittest.main()
