"""Offline observer tests; no cluster or inference requests."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from crossscale.episodes import Observer


class ScalerObserverTests(unittest.TestCase):
    def observe_once(self, capture, failure=False):
        with tempfile.TemporaryDirectory() as folder:
            cluster = Mock()
            observer = Observer(cluster, folder, capture_scaler=capture)
            def snapshot():
                observer.stop.set()
                return {'observed_unix_s': 100, 'pods': [],
                        'deployment': {'spec': {'replicas': 2}}}
            cluster.snapshot.side_effect = snapshot
            raw = {'scaledobject': None,
                   'hpa': {'items': [{'metadata': {'uid': 'hpa-uid',
                            'ownerReferences': [{'uid': 'scaledobject-uid'}]},
                            'status': {'desiredReplicas': 4}}]},
                   'events': {'items': [{'reason': 'SuccessfulRescale'}]}}
            def get(kind, *args, **kwargs):
                if failure:
                    raise RuntimeError('API unavailable')
                return raw[kind]
            cluster.get.side_effect = get
            observer.loop()
            with gzip.open(Path(folder) / 'observations.jsonl.gz', 'rt') as stream:
                rows = [json.loads(line) for line in stream]
            state_path = Path(folder) / 'state.json'
            state = json.loads(state_path.read_text()) if state_path.exists() else None
            return observer, cluster, rows, state, raw

    def test_opt_in_preserves_raw_scaler_evidence_and_read_window(self):
        observer, cluster, rows, state, raw = self.observe_once(True)
        self.assertIsNone(observer.error)
        self.assertEqual(len(rows), 1)
        evidence = rows[0]['scaler']
        for key, value in raw.items():
            self.assertEqual(evidence[key], value)
        self.assertLessEqual(evidence['read_started_unix_s'], evidence['read_finished_unix_s'])
        self.assertEqual(state['desired'], 2)
        cluster.get.assert_any_call('scaledobject', 'vllm', missing_ok=True)

    def test_default_does_not_query_scaler_or_change_snapshot_schema(self):
        observer, cluster, rows, state, _ = self.observe_once(False)
        cluster.get.assert_not_called()
        self.assertNotIn('scaler', rows[0])
        self.assertIsNone(observer.error)

    def test_api_failure_is_not_silently_recorded_as_no_scaler(self):
        observer, cluster, rows, state, _ = self.observe_once(True, failure=True)
        self.assertIn('API unavailable', observer.error)
        self.assertEqual(rows, [])
        self.assertIsNone(state)
        self.assertTrue(observer.started.is_set())
