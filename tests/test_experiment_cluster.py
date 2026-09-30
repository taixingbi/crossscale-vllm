import unittest
import gzip
import json
import tempfile
from io import BytesIO
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from crossscale.cluster import Cluster, can_delete_empty_claim, retry_wait_s
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


def _http_error(code, body, retry_after=None):
    headers = EmailMessage()
    if retry_after is not None:
        headers['Retry-After'] = str(retry_after)
    return HTTPError('https://kubernetes.default.svc/x', code, 'error', headers, BytesIO(body.encode()))


class _JsonResponse:
    def __init__(self, payload):
        self._buf = BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self._buf

    def __exit__(self, *args):
        return False


class ApiRetry(unittest.TestCase):
    def test_retry_wait_uses_k8s_retry_after_seconds(self):
        body = json.dumps(dict(details=dict(retryAfterSeconds=1)))
        exc = _http_error(429, body)
        self.assertEqual(retry_wait_s(exc, body), 1)

    def test_get_retries_storage_reinitializing_then_succeeds(self):
        cluster = Cluster.__new__(Cluster)
        cluster.base = 'https://kubernetes.default.svc'
        cluster.identity = Path('/missing')
        cluster.tls = None
        payload = dict(kind='NodeClaimList', items=[])
        error = _http_error(429, json.dumps(dict(status='Failure', message='storage is (re)initializing',
                                                 reason='TooManyRequests', details=dict(retryAfterSeconds=1),
                                                 code=429)))
        with patch.object(Path, 'read_text', return_value='token'), \
             patch('crossscale.cluster.urlopen', side_effect=[error, _JsonResponse(payload)]), \
             patch('crossscale.cluster.time.sleep') as slept:
            self.assertEqual(cluster.get('nodeclaims', selector='karpenter.sh/nodepool=crossscale-gpu'), payload)
        slept.assert_called()

    def test_persistent_429_still_fails_after_budget(self):
        cluster = Cluster.__new__(Cluster)
        cluster.base = 'https://kubernetes.default.svc'
        cluster.identity = Path('/missing')
        cluster.tls = None
        def boom(*_a, **_k):
            raise _http_error(429, '{"status":"Failure"}')
        with patch.object(Path, 'read_text', return_value='token'), \
             patch('crossscale.cluster.urlopen', side_effect=boom), \
             patch('crossscale.cluster.time.monotonic', side_effect=[0, 0, 121]), \
             patch('crossscale.cluster.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 429'):
                cluster.get('nodeclaims')

    def test_missing_ok_404_is_not_retried(self):
        cluster = Cluster.__new__(Cluster)
        cluster.base = 'https://kubernetes.default.svc'
        cluster.identity = Path('/missing')
        cluster.tls = None
        error = _http_error(404, '{"kind":"Status"}')
        with patch.object(Path, 'read_text', return_value='token'), \
             patch('crossscale.cluster.urlopen', side_effect=error) as opener:
            self.assertIsNone(cluster.get('scaledobject', 'vllm', missing_ok=True))
        self.assertEqual(opener.call_count, 1)
