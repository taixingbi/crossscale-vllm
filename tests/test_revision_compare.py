import unittest

from crossscale.revision_compare import paired_comparison


def records():
    return [dict(seed=s, baseline=b, value=v, dispatch_valid=True, censored=False,
                 condition_sha256='condition', trace_sha256=f'trace-{s}', mode='live')
            for s in range(5) for b, v in [('B6', .8), ('B5', .7)]]


class ComparisonTests(unittest.TestCase):
    def compare(self, rows):
        return paired_comparison(rows, 'B6', 'B5', range(5), .05, resamples=100)

    def test_paired_direction_and_practical_effect(self):
        result = self.compare(records())
        self.assertAlmostEqual(result['mean_difference'], .1)
        self.assertTrue(result['practical_benefit_supported'])
        reverse = paired_comparison(records(), 'B5', 'B6', range(5), .05, resamples=100)
        self.assertFalse(reverse['practical_benefit_supported'])

    def test_invalid_missing_censored_remain_accounted_for(self):
        rows = records()[1:]
        rows[1]['dispatch_valid'] = False
        rows[3]['censored'] = True
        rows[5]['value'] = None
        result = self.compare(rows)
        self.assertEqual([e['reason'] for e in result['excluded']],
                         ['missing-run', 'invalid-dispatch', 'censored-or-unknown',
                          'missing-or-nonfinite-metric'])
        self.assertEqual(len(result['pairs']), 1)
        self.assertIsNone(result['practical_benefit_supported'])
        self.assertIsNone(result['paired_bootstrap_95'])

    def test_mismatches_and_duplicates_are_errors(self):
        for field, value in [('mode', 'simulation'), ('condition_sha256', 'other'),
                             ('trace_sha256', 'other'), ('seed', 99)]:
            rows = records()
            rows[0][field] = value
            with self.assertRaises(ValueError):
                self.compare(rows)
        with self.assertRaises(ValueError):
            self.compare(records()+records()[:1])

    def test_zero_is_valid_and_bootstrap_is_deterministic(self):
        rows = records()
        for row in rows:
            row['value'] = 0
        self.assertEqual(self.compare(rows), self.compare(rows))
        self.assertEqual(self.compare(rows)['paired_bootstrap_95'], [0, 0])
        self.assertFalse(self.compare(rows)['practical_benefit_supported'])
