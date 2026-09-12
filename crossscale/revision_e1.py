"""September 12 isolated-tenant E1; preparation is entirely offline by default."""
import argparse
import asyncio
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import time
from urllib.request import urlopen

from .core import workload

RATES = {'A': [.05, .1, .2, .4, .8, 1.6],
         'B': [.01, .025, .05, .1, .2, .4],
         'C': [.005, .01, .025, .05, .1, .2]}
SEEDS = [601, 602, 603, 604, 605]
MIN_SAMPLES = 60


def plan(base):
    """Fixed five repetitions everywhere, including every possible boundary."""
    runs = []
    for tenant, rates in RATES.items():
        for rate in rates:
            for seed in SEEDS:
                c = copy.deepcopy(base)
                c.update(seed=seed, duration_s=max(600, math.ceil(100/rate)),
                         initial_replicas=1, max_replicas=1, client_force_close=True,
                         upstream_force_close=True,
                         serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off')
                c['phases'] = [{'start_s': 0, 'rates': {t: rate if t == tenant else 0 for t in c['tenants']}}]
                rows = workload(c)
                if len(rows) < MIN_SAMPLES or any(r['input_tokens']+r['output_tokens'] > 32768 for r in rows):
                    raise ValueError('Frozen trace has insufficient samples or exceeds context')
                runs.append(dict(name=f'{tenant}-rps-{rate}-seed-{seed}', tenant=tenant,
                                 rps=rate, seed=seed, offered=len(rows), config=c))
    return dict(revision='revision-20260912', phase='e1-isolated',
                batch_tokens=4096, min_samples=MIN_SAMPLES, seeds=SEEDS,
                qualification='Every fixed repetition and every lower tested rate passes; no replacements',
                runs=runs)


def qualifies(summary, rows, tenant):
    metric = summary['tenants'][tenant]
    valid = bool(rows) and all(r.get('dispatch_lag_s', float('inf')) <= .05 for r in rows)
    return valid, (valid and metric['offered'] >= MIN_SAMPLES and
                   metric['goodput'] is not None and metric['goodput'] >= .95)


def capacity(records, tenant):
    result = None
    for rate in RATES[tenant]:
        rs = [r for r in records if r['tenant'] == tenant and r['rps'] == rate]
        if len(rs) != len(SEEDS) or {r['seed'] for r in rs} != set(SEEDS) or not all(r['passed'] for r in rs):
            break
        result = rate
    return result


def execute(root, frozen):
    # Imports needing cluster/runtime dependencies occur only for explicit execution.
    from .study import Study, SERVICE, MODEL, PROMETHEUS
    from .episodes import Observer, ready, save
    from .live import run
    from .telemetry import collect, QUERIES
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        e0 = root/'e0-prefill4096'
        if not all((e0/name).exists() for name in ('complete.json', 'restored.json')) or (e0/'error.json').exists():
            raise RuntimeError('E0 completion/restoration required before E1')
        for condition in ('cached-on-existing-node', 'cold-new-node', 'prebaked-image-new-node'):
            summaries = list((e0/condition).glob('episode-*/summary.json'))
            if len(summaries) != 30 or any(json.loads(p.read_text()).get('error') for p in summaries):
                raise RuntimeError('E0 episodes incomplete or require diagnosis')
        dest = root/'revision-20260912'/'e1-isolated'
        dest.mkdir(parents=True, exist_ok=False)
        save(dest/'frozen-plan.json', frozen)
        (root/'study.pid').write_text(str(os.getpid()))
        study = Study(root)
        study.idle()
        study.fixed(1)
        study.control.cleanup_empty()
        before = study.k.get('deployment', 'vllm')
        original = before['spec']['template']['spec']['containers']
        trial = copy.deepcopy(original)
        args = trial[0]['args']
        if args[args.index('--max-num-batched-tokens')+1] != '1024':
            raise RuntimeError('Expected E0-restored 1024 condition')
        args[args.index('--max-num-batched-tokens')+1] = '4096'
        save(dest/'deployment-before.json', before)

        def rollout(containers):
            study.k.patch('deployment', 'vllm', {'spec': {'template': {'spec': {'containers': containers}}}})
            deadline = time.monotonic()+1200
            while time.monotonic() < deadline:
                pods = study.k.get('pods', selector='app=vllm')['items']
                if len(pods) == 1 and ready(pods[0]) and not pods[0]['metadata'].get('deletionTimestamp') and pods[0]['spec']['containers'][0]['args'] == containers[0]['args']:
                    return pods[0]
                time.sleep(3)
            raise TimeoutError('Serving rollout deadline')

        try:
            pod = rollout(trial)
            study.warmup()
            save(dest/'deployment-trial.json', study.k.get('deployment', 'vllm'))
            with urlopen('http://'+pod['status']['podIP']+':8000/metrics', timeout=20) as response:
                metrics = response.read().decode()
            (dest/'installed-metrics.txt').write_text(metrics)
            names = {line.split('{')[0].split(' ')[0] for line in metrics.splitlines() if line and not line.startswith('#')}
            required = ['vllm:num_requests_waiting', 'vllm:num_requests_running', 'vllm:kv_cache_usage_perc', 'vllm:prompt_tokens_total', 'vllm:generation_tokens_total']
            save(dest/'metric-availability.json', {n: n in names for n in required})
            queries = {k: v for k, v in QUERIES.items() if k != 'slo_saturation'}
            queries.update(prompt_tokens_s='sum(rate(vllm:prompt_tokens_total{namespace="crossscale"}[1m]))',
                           generation_tokens_s='sum(rate(vllm:generation_tokens_total{namespace="crossscale"}[1m]))')
            if not all(n in names for n in required):
                raise RuntimeError('Required vLLM telemetry missing; inspect availability before measurement')
            preflight = collect(PROMETHEUS, time.time()-120, time.time(), 5, dest/'telemetry-preflight', queries)
            if set(preflight['missing_series']) & {'waiting', 'running', 'kv_cache', 'prompt_tokens_s', 'generation_tokens_s'}:
                raise RuntimeError('Required Prometheus series unavailable before measurement')
            records = []
            for spec in frozen['runs']:
                folder = dest/spec['name']
                study.event('revision-e1-run-start', name=spec['name'])
                study.warmup()
                with Observer(study.k, folder):
                    save(folder/'cluster-before.json', study.k.snapshot())
                    summary = asyncio.run(run(spec['config'], 'B0', folder/'run', SERVICE, MODEL, root/'tokens.json'))
                    # Keep observation through the entire predeclared arrival/drain horizon.
                    remaining = summary['start_unix_s']+spec['config']['duration_s']+spec['config']['drain_s']-time.time()
                    if remaining > 0:
                        time.sleep(remaining)
                    study.idle()
                    save(folder/'cluster-after.json', study.k.snapshot())
                    collect(PROMETHEUS, summary['start_unix_s'], time.time(), 5, folder/'telemetry', queries)
                rows = [json.loads(line) for line in (folder/'run'/'requests.jsonl').read_text().splitlines()]
                valid, passed = qualifies(summary, rows, spec['tenant'])
                record = {k: spec[k] for k in ('name', 'tenant', 'rps', 'seed', 'offered')}
                record.update(dispatch_valid=valid, passed=passed, summary=summary)
                records.append(record)
                save(folder/'complete.json', record)
                save(dest/'progress.json', records)
                study.event('revision-e1-run-complete', name=spec['name'], passed=passed)
            save(dest/'complete.json', dict(results=records, capacities={t: capacity(records, t) for t in RATES}, completed_unix_s=time.time()))
        except BaseException as exc:
            save(dest/'error.json', dict(error=repr(exc), unix_s=time.time()))
            raise
        finally:
            current = study.k.get('deployment', 'vllm')['spec']['template']['spec']['containers']
            if current[0]['args'] != trial[0]['args']:
                raise RuntimeError('Unexpected serving change; refusing blind restoration')
            rollout(original)
            study.warmup()
            save(dest/'restored.json', dict(unix_s=time.time(), deployment=study.k.get('deployment', 'vllm')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    args = parser.parse_args()
    if args.execute:
        frozen = json.loads(args.plan.read_text())
        if frozen != plan(json.loads(args.config.read_text())):
            raise ValueError('Frozen plan differs from current code/config')
        execute(args.root, frozen)
    else:
        frozen = plan(json.loads(args.config.read_text()))
        with args.plan.open('x') as stream:
            json.dump(frozen, stream, indent=2)
        print(json.dumps(dict(runs=len(frozen['runs']), arrival_hours=sum(r['config']['duration_s'] for r in frozen['runs'])/3600)))


if __name__ == '__main__':
    main()
