import unittest
import gzip
import json
import tempfile
from pathlib import Path
from crossscale.cluster import can_delete_empty_claim
from crossscale.kube import extract


class DeletionScope(unittest.TestCase):
    def setUp(self):
        self.claim = {'metadata': {'name': 'experiment-added', 'labels': {'karpenter.sh/nodepool': 'crossscale-gpu'}},
                      'status': {'nodeName': 'gpu-node'}}
        self.owned = {'experiment-added'}

    def test_only_empty_owned_claim_is_eligible(self):
        self.assertTrue(can_delete_empty_claim(self.claim, [], self.owned))
        self.assertFalse(can_delete_empty_claim(self.claim, [], set()))
        self.claim['metadata']['labels']['karpenter.sh/nodepool'] = 'unrelated'
        self.assertFalse(can_delete_empty_claim(self.claim, [], self.owned))

    def test_foreign_or_terminating_workload_blocks_deletion(self):
        pod = {'metadata': {'namespace': 'unrelated', 'name': 'work', 'deletionTimestamp': 'now'},
               'spec': {'nodeName': 'gpu-node'}, 'status': {'phase': 'Running'}}
        self.assertFalse(can_delete_empty_claim(self.claim, [pod], self.owned))

    def test_node_daemon_is_not_a_workload_blocker(self):
        pod = {'metadata': {'name': 'device-plugin', 'ownerReferences': [{'kind': 'DaemonSet'}]},
               'spec': {'nodeName': 'gpu-node'}, 'status': {'phase': 'Running'}}
        self.assertTrue(can_delete_empty_claim(self.claim, [pod], self.owned))

    def test_compressed_observations_preserve_scale_gap(self):
        def observation(ts, desired, count):
            pods = [{'metadata': {'name': str(i)}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for i in range(count)]
            return {'observed_unix_s': ts, 'deployment': {'spec': {'replicas': desired}}, 'pods': pods}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observations.jsonl.gz'
            with gzip.open(path, 'wt') as f:
                for row in [observation(1, 2, 2), observation(2, 4, 2), observation(7, 4, 4)]:
                    f.write(json.dumps(row) + '\n')
            result = extract(path)
            self.assertEqual(result['gap_statistics']['completed'], 1)
            self.assertEqual(result['episodes'][0]['gap_s'], 5)
