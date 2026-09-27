"""Synthetic API evidence; these tests do not run KEDA or live experiments."""
from copy import deepcopy
import unittest

from crossscale.revision_scaler import audit_scaler_snapshot


def evidence():
    return {
        'observed_unix_s': 100,
        'deployment': {'metadata': {'uid': 'dep', 'namespace': 'crossscale', 'name': 'vllm'}},
        'scaler': {
            'read_started_unix_s': 101, 'read_finished_unix_s': 102,
            'scaledobject': {
                'metadata': {'uid': 'so', 'namespace': 'crossscale', 'name': 'vllm',
                             'labels': {'crossscale-experiment': 'full-20260908'}},
                'spec': {'scaleTargetRef': {'name': 'vllm'}}},
            'hpa': {'items': [{
                'metadata': {'uid': 'hpa', 'namespace': 'crossscale', 'name': 'keda-hpa-vllm',
                             'ownerReferences': [{'uid': 'so', 'name': 'vllm', 'controller': True,
                                                  'kind': 'ScaledObject', 'apiVersion': 'keda.sh/v1alpha1'}]},
                'spec': {'scaleTargetRef': {'name': 'vllm', 'kind': 'Deployment', 'apiVersion': 'apps/v1'}},
                'status': {'desiredReplicas': 4}}]},
            'events': {'items': [{
                'reason': 'SuccessfulRescale', 'lastTimestamp': '2026-09-27T00:00:00Z',
                'involvedObject': {'uid': 'hpa', 'name': 'keda-hpa-vllm',
                                   'namespace': 'crossscale', 'kind': 'HorizontalPodAutoscaler'}}]}}}


class ScalerAuditTests(unittest.TestCase):
    def audit(self, raw):
        return audit_scaler_snapshot(raw, deployment_uid='dep', scaledobject_uid='so')

    def test_linked_evidence_preserves_events_without_claiming_causality(self):
        raw = evidence()
        original = deepcopy(raw)
        result = self.audit(raw)
        self.assertEqual(result['status'], 'identity-linked')
        self.assertEqual(result['reported_desired_replicas'], 4)
        self.assertEqual(result['read_window'], [101, 102])
        self.assertEqual(result['rescale_events'], raw['scaler']['events']['items'])
        self.assertFalse(result['causal_attribution'])
        self.assertEqual(raw, original)

    def test_same_name_replacement_uids_are_rejected(self):
        for obj in ('deployment', 'scaledobject', 'owner'):
            raw = evidence()
            if obj == 'deployment':
                raw['deployment']['metadata']['uid'] = 'replacement'
            elif obj == 'scaledobject':
                raw['scaler']['scaledobject']['metadata']['uid'] = 'replacement'
            else:
                raw['scaler']['hpa']['items'][0]['metadata']['ownerReferences'][0]['uid'] = 'replacement'
            with self.subTest(obj=obj):
                self.assertEqual(self.audit(raw)['status'], 'unverified')

    def test_competing_target_hpa_is_rejected_even_when_deleting(self):
        raw = evidence()
        other = deepcopy(raw['scaler']['hpa']['items'][0])
        other['metadata'].update(uid='other', deletionTimestamp='2026-09-27T00:00:00Z')
        raw['scaler']['hpa']['items'].append(other)
        self.assertIn('missing-or-competing-target-hpas', self.audit(raw)['reasons'])
        other['spec']['scaleTargetRef']['name'] = 'unrelated'
        self.assertEqual(self.audit(raw)['status'], 'identity-linked')

    def test_foreign_labels_targets_or_noncontroller_owner_fail(self):
        for case in ('label', 'target', 'controller', 'hpa-target'):
            raw = evidence()
            scaler = raw['scaler']
            if case == 'label':
                scaler['scaledobject']['metadata']['labels'] = {}
            elif case == 'target':
                scaler['scaledobject']['spec']['scaleTargetRef']['kind'] = 'StatefulSet'
            elif case == 'hpa-target':
                scaler['hpa']['items'][0]['spec']['scaleTargetRef']['apiVersion'] = 'other/v1'
            else:
                scaler['hpa']['items'][0]['metadata']['ownerReferences'][0]['controller'] = False
            with self.subTest(case=case):
                self.assertEqual(self.audit(raw)['status'], 'unverified')

    def test_expired_or_unrelated_events_do_not_fabricate_rescale(self):
        raw = evidence()
        raw['scaler']['events']['items'][0]['involvedObject']['uid'] = 'old-hpa'
        result = self.audit(raw)
        self.assertEqual(result['status'], 'identity-linked')
        self.assertEqual(result['rescale_events'], [])
        raw['scaler']['events']['items'] = []
        self.assertEqual(self.audit(raw)['rescale_events'], [])

    def test_missing_evidence_and_invalid_read_windows_fail_closed(self):
        for case in ('capture', 'hpa', 'events', 'desired', 'nan', 'backwards'):
            raw = evidence()
            if case == 'capture':
                del raw['scaler']
            elif case in ('hpa', 'events'):
                raw['scaler'][case] = {}
            elif case == 'desired':
                raw['scaler']['hpa']['items'][0]['status'] = {}
            else:
                raw['scaler']['read_finished_unix_s'] = float('nan') if case == 'nan' else 99
            with self.subTest(case=case):
                self.assertEqual(self.audit(raw)['status'], 'unverified')
        with self.assertRaises(ValueError):
            audit_scaler_snapshot(evidence(), deployment_uid='', scaledobject_uid='so')
