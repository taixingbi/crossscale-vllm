import json
from pathlib import Path
from unittest import TestCase
from crossscale.policy_audit import audit_decisions
from crossscale.revision_e5 import run_config

class PolicyAudit(TestCase):
    def setUp(self):
        self.c=run_config(json.loads(Path('configs/revision-20260930.json').read_text()),871,.025,.8)[0]
    def row(self,action,ready=0,active=None,eta=None):
        return dict(baseline='B6', request=dict(tenant='A',input_tokens=256,offered_s=0),
            now_monotonic_s=0,ready=ready,desired=4,active=active or {},
            pending_etas_monotonic_s=eta or [],action=action,request_id='1')
    def test_delay_is_distinct_from_overhead_and_deduplicated(self):
        r=self.row('delay',eta=[.01])
        a=audit_decisions(self.c,[r,r,self.row('admit',ready=2)])
        self.assertTrue(a['replay_valid'])
        self.assertEqual(a['requests_with_actual_delay'],1)
        self.assertEqual(a['action_counts']['delay'],2)
        self.assertEqual(a['eta_branch_differences'],2)
    def test_tenant_branch_under_contention_and_replay_mismatch(self):
        r=self.row('admit',ready=4,active={'A':1})
        self.assertEqual(audit_decisions(self.c,[r])['tenant_branch_differences'],1)
        r['action']='reject'
        self.assertFalse(audit_decisions(self.c,[r])['replay_valid'])
