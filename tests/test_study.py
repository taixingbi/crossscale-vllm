import unittest
from crossscale.study import continuation_gate, paired_bootstrap


class StudyGate(unittest.TestCase):
    def test_gate_requires_both_comparators_and_tenant_floor(self):
        comparisons = {b: {'pairs': 5, 'mean_wg_difference': .06, 'paired_bootstrap_95': [.01, .1]} for b in ('B3', 'ready-only')}
        runs = [{'tenants': {'C': {'goodput': .6, 'offered': 10, 'rejected': 4}}} for _ in range(5)]
        self.assertTrue(continuation_gate(comparisons, runs)['trigger_e3_to_e7'])
        comparisons['ready-only']['paired_bootstrap_95'][0] = -.01
        self.assertFalse(continuation_gate(comparisons, runs)['trigger_e3_to_e7'])
        comparisons['ready-only']['paired_bootstrap_95'][0] = .01
        runs[0]['tenants']['C']['goodput'] = .4
        self.assertFalse(continuation_gate(comparisons, runs)['trigger_e3_to_e7'])

    def test_bootstrap_does_not_treat_sparse_pairs_as_sufficient(self):
        self.assertIsNone(paired_bootstrap([.1]*4)['mean'])
        result = paired_bootstrap([.1]*5)
        self.assertAlmostEqual(result['mean'], .1)
        self.assertEqual(result['pairs'], 5)
