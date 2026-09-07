import copy
from pathlib import Path
import runpy
import unittest

CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/check-cluster-plan.py'))['check']


def resource(kind, after, actions=None):
    return {'mode': 'managed', 'type': kind, 'change': {'actions': actions or ['create'], 'after': after}}


class ClusterPlan(unittest.TestCase):
    def setUp(self):
        self.plan = {'resource_changes': [
            resource('aws_eks_cluster', {'name': 'crossscale', 'version': '1.34', 'region': 'us-east-1'}),
            resource('aws_eks_node_group', {'instance_types': ['m5.large'], 'scaling_config': [
                {'desired_size': 2, 'min_size': 2, 'max_size': 2}]}),
        ]}

    def test_accepts_reviewed_cpu_cluster(self):
        CHECK(self.plan)

    def test_rejects_destructive_and_extra_resources(self):
        for extra in [resource('aws_instance', {}), resource('aws_vpc', {}, ['delete', 'create'])]:
            with self.subTest(extra=extra):
                plan = copy.deepcopy(self.plan)
                plan['resource_changes'].append(extra)
                with self.assertRaises(ValueError):
                    CHECK(plan)

    def test_rejects_gpu_nodes_or_changed_scale(self):
        for field, value in [('instance_types', ['g5.xlarge']), ('scaling_config', [{'desired_size': 4, 'min_size': 2, 'max_size': 4}])]:
            plan = copy.deepcopy(self.plan)
            plan['resource_changes'][1]['change']['after'][field] = value
            with self.assertRaises(ValueError):
                CHECK(plan)

    def test_rejects_other_region(self):
        self.plan['resource_changes'][0]['change']['after']['region'] = 'us-west-2'
        with self.assertRaises(ValueError):
            CHECK(self.plan)
