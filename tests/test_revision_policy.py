import json
from pathlib import Path
import unittest
from crossscale.policy import decision


class RevisedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads(Path('configs/default.json').read_text())
        self.c['admission_policy_revision'] = 'revision-20260912'
        self.r = dict(tenant='A', input_tokens=256, offered_s=0)

    def test_pending_capacity_is_not_dispatch_capacity(self):
        self.assertEqual(decision(self.c, 'B5', self.r, 0, 0, 4, {}, [.1]), 'reject')
        self.assertEqual(decision(self.c, 'B6', self.r, 0, 0, 4, {}, [.1]), 'delay')
        self.assertEqual(decision(self.c, 'B6', self.r, 0, 0, 4, {}, [60]), 'reject')

    def test_ready_admission_and_no_eta_decisions_match(self):
        for ready in (0, 1, 2, 4):
            for desired in (ready, 4):
                for active in ({}, {'A': 8}, {'B': 32}):
                    for now in (0, .2, 1):
                        args = (self.r, now, ready, desired, active, [])
                        self.assertEqual(decision(self.c, 'B5', *args), decision(self.c, 'B6', *args))

    def test_historical_behavior_remains_explicit(self):
        self.c.pop('admission_policy_revision')
        self.assertEqual(decision(self.c, 'B5', self.r, 0, 0, 4, {}, [.1]), 'admit')
        self.c['admission_policy_revision'] = 'unknown'
        with self.assertRaises(ValueError):
            decision(self.c, 'B5', self.r, 0, 0, 4, {}, [.1])
