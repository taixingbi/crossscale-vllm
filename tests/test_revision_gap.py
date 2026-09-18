import unittest
from crossscale.revision_gap import observed_gap, gap_cohort


def sample(t, desired, ready):
    return dict(observed_unix_s=t, desired=desired, ready=ready)


class GapTests(unittest.TestCase):
    def test_stepwise_scale_uses_actual_first_decision_and_final_readiness(self):
        gap = observed_gap([sample(100,2,2),sample(110,3,2),sample(120,4,3),sample(150,4,4)])
        self.assertEqual(gap['gap_s'],40)
        self.assertEqual(gap['target_requested_unix_s'],120)
        rows = [dict(offered_s=s,status='rejected') for s in (9,10,49,50)]
        self.assertEqual(gap_cohort(rows,100,gap),rows[1:3])
        self.assertFalse(gap['censored'])

    def test_missing_readiness_is_censored_not_zero(self):
        gap = observed_gap([sample(100,2,2),sample(110,4,2),sample(140,4,3)])
        self.assertTrue(gap['censored'])
        self.assertIsNone(gap['gap_s'])
        self.assertEqual(len(gap_cohort([dict(offered_s=20,status='timeout')],100,gap)),1)

    def test_no_scale_is_not_a_zero_duration_gap(self):
        gap = observed_gap([sample(100,2,2),sample(200,2,2)])
        self.assertEqual(gap['status'],'no-scale-observed')
        self.assertIsNone(gap['gap_s'])
        self.assertEqual(gap_cohort([dict(offered_s=20)],100,gap),[])

    def test_bad_initial_state_or_time_is_rejected(self):
        for samples in ([],[sample(1,4,4)],[sample(1,2,2),sample(1,4,2)]):
            with self.assertRaises(ValueError): observed_gap(samples)
