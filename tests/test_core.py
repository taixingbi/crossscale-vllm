import hashlib
import copy
import json
from pathlib import Path
import tempfile
import unittest

from crossscale.core import config, workload, summarize, write_run, quantile
from crossscale.policy import decision
from crossscale.sim import run
from crossscale.kube import extract


class Experiments(unittest.TestCase):
    def setUp(self):
        self.c = config('configs/default.json')

    def test_open_loop_reproducible(self):
        self.assertEqual(workload(self.c), workload(self.c))
        self.assertTrue(all(r['offered_s'] < 300 for r in workload(self.c)))

    def test_rejection_cannot_inflate_goodput(self):
        rows = []
        for t in self.c['tenants']:
            rows.extend([dict(tenant=t, status='completed', ttft_s=.1, tpot_s=.01, output_tokens=5), dict(tenant=t, status='rejected', output_tokens=5)])
        self.assertEqual(summarize(rows, self.c)['weighted_slo_goodput'], .5)

    def test_missing_tenant_is_not_reweighted(self):
        self.assertIsNone(summarize([], self.c)['weighted_slo_goodput'])

    def test_eta_never_dispatches_unready_capacity(self):
        c = self.c
        c['eta_margin_s'] = 0
        r = dict(tenant='A', input_tokens=2, offered_s=0)
        self.assertEqual(decision(c, 'B6', r, 0, 0, 4, {}, [.1]), 'delay')
        self.assertEqual(decision(c, 'ready-only', r, 0, 0, 4, {}, [.1]), 'reject')
        self.assertEqual(decision(c, 'B5', r, 0, 0, 4, {}, [.1]), 'admit')
        self.assertEqual(decision(c, 'B6', r, 0, 0, 4, {}, [60]), 'reject')

    def test_deadline_includes_gateway_wait(self):
        r = dict(tenant='A', input_tokens=256, offered_s=0)
        self.assertEqual(decision(self.c, 'B6', r, 1, 0, 4, {}, [1.1]), 'reject')

    def test_simulation_accounts_for_every_arrival(self):
        c = copy.deepcopy(self.c)
        c.update(duration_s=4, drain_s=1)
        c['phases'] = [c['phases'][0]]
        with tempfile.TemporaryDirectory() as d:
            run(c, 'B6', Path(d)/'run')
            rows = [json.loads(x) for x in (Path(d)/'run/requests.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), len(workload(c)))
            self.assertTrue(all(r['status'] in ('completed', 'timeout', 'rejected') for r in rows))
            with self.assertRaises(FileExistsError):
                run(c, 'B6', Path(d)/'run')

    def test_quantile_interpolation_and_summary_tails(self):
        self.assertIsNone(quantile([], .95))
        self.assertEqual(quantile([7], .99), 7)
        self.assertAlmostEqual(quantile([10, 0, 5], .95), 9.5)
        rows = [dict(tenant='A', status='completed', ttft_s=x, tpot_s=.01,
                     output_tokens=5) for x in [10, 0, 5]]
        result = summarize(rows, self.c)['tenants']['A']
        self.assertAlmostEqual(result['p95_ttft_s'], 9.5)
        self.assertAlmostEqual(result['p99_ttft_s'], 9.9)

    def test_streamed_artifacts_preserve_trace_hash(self):
        for count in (0, 1, 3):
            rows = [dict(id=i, tenant='A', offered_s=i*.1, input_tokens=10,
                         output_tokens=4, status='rejected') for i in range(count)]
            trace = [{k: r[k] for k in ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')} for r in rows]
            expected = hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest()
            with tempfile.TemporaryDirectory() as d:
                out = Path(d)/'run'
                write_run(out, self.c, rows, [], 'simulation', 'B6')
                self.assertEqual(json.loads((out/'manifest.json').read_text())['trace_sha256'], expected)
                self.assertEqual([json.loads(line) for line in (out/'requests.jsonl').read_text().splitlines()], rows)

    def test_e0_streaming_preserves_completed_episode_and_stages(self):
        pod = dict(metadata=dict(name='vllm-1', uid='pod-1', creationTimestamp='2026-01-01T00:00:00Z'),
                   spec=dict(nodeName='gpu-1'), status=dict(conditions=[
                       dict(type='Ready', status='True', lastTransitionTime='2026-01-01T00:00:05Z')]))
        observations = [dict(observed_unix_s=t, deployment={'spec': {'replicas': n}}, pods=pods)
                        for t, n, pods in [(0, 0, []), (1, 1, []), (5, 1, [pod]), (6, 1, [pod])]]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'obs'
            p.write_text('\n'.join(json.dumps(x) for x in observations))
            result = extract(p)
        self.assertEqual(result['episodes'][0]['gap_s'], 4)
        self.assertEqual(result['gap_statistics']['completed'], 1)
        self.assertEqual(len(result['pod_stages']), 1)
        self.assertEqual(result['pod_stages'][0]['vllm_ready_unix_s'], 1767225605)

    def test_e0_censors_incomplete_scale(self):
        observations = [dict(observed_unix_s=i, deployment={'spec': {'replicas': n}}, pods=[]) for i,n in [(0,2),(1,4),(2,4)]]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'obs'
            p.write_text('\n'.join(json.dumps(x) for x in observations))
            episode = extract(p)['episodes'][0]
            self.assertIsNone(episode['gap_s'])
            self.assertEqual(episode['censor_reason'], 'observation_ended')


if __name__ == '__main__':
    unittest.main()
