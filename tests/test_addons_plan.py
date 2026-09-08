import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('addons_guard', Path(__file__).resolve().parents[1] / 'scripts/check-addons-plan.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class AddonsPlanTests(unittest.TestCase):
    def plan(self):
        resources = ['helm_release.' + name for name in ['karpenter', 'device_plugin', 'keda', 'prometheus', 'gpu_pool']]
        resources += ['aws_iam_role.model_reader', 'aws_iam_role_policy.model_reader', 'aws_eks_pod_identity_association.model_reader']
        plan = {'resource_changes': [{'mode': 'managed', 'address': a, 'change': {'actions': ['create'], 'after': {}}} for a in resources]}
        plan['resource_changes'][4]['change']['after']['values'] = [json.dumps({
            'clusterName': 'crossscale', 'nodeRole': 'crossscale-gpu', 'amiId': 'ami-0c126bbe79be20f0a', 'gpuLimit': 1})]
        plan['resource_changes'][-1]['change']['after'] = {'cluster_name': 'crossscale', 'namespace': 'crossscale', 'service_account': 'vllm-model-reader'}
        return plan

    def test_allows_smoke(self):
        guard.check(self.plan())

    def test_rejects_delete(self):
        plan = self.plan()
        plan['resource_changes'][0]['change']['actions'] = ['delete', 'create']
        with self.assertRaises(ValueError):
            guard.check(plan)

    def test_rejects_larger_gpu_pool(self):
        plan = self.plan()
        entry = plan['resource_changes'][4]['change']['after']
        values = json.loads(entry['values'][0]); values['gpuLimit'] = 4
        entry['values'] = [json.dumps(values)]
        with self.assertRaises(ValueError):
            guard.check(plan)
