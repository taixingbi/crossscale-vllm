"""Explicit live execution of the separately frozen revised mixed calibration."""
import argparse
import asyncio
import copy
import fcntl
import json
import os
from pathlib import Path
import time
from urllib.request import urlopen

from .revision_mixed import plan, qualifies, capacity

def execute(root, frozen):
    # Imports needing cluster/runtime dependencies occur only for explicit execution.
    from .study import Study, SERVICE, MODEL, PROMETHEUS
    from .episodes import Observer, ready, save
    from .live import run
    from .telemetry import collect, QUERIES
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        isolated = root/'revision-20260912'/'e1-isolated'
        if not all((isolated/name).exists() for name in ('complete.json', 'restored.json')) or (isolated/'error.json').exists():
            raise RuntimeError('Isolated E1 completion/restoration required')
        prior = json.loads((isolated/'complete.json').read_text())
        if len(prior['results']) != 90:
            raise RuntimeError('Isolated E1 incomplete')
        dest = root/'revision-20260912'/'e1-mixed'
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
            raise RuntimeError('Expected isolated-E1-restored 1024 condition')
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
            replicas = 1
            for spec in frozen['runs']:
                if spec['replicas'] != replicas:
                    study.fixed(spec['replicas'])
                    replicas = spec['replicas']
                    study.control.cleanup_empty()
                folder = dest/spec['name']
                study.event('revision-mixed-run-start', name=spec['name'])
                study.warmup()
                with Observer(study.k, folder, interval_s=5):
                    save(folder/'cluster-before.json', study.k.snapshot())
                    summary = asyncio.run(run(spec['config'], 'B0', folder/'run', SERVICE, MODEL, root/'tokens.json'))
                    # Keep observation through the entire predeclared arrival/drain horizon.
                    remaining = summary['start_unix_s']+spec['config']['duration_s']+spec['config']['drain_s']-time.time()
                    if remaining > 0:
                        time.sleep(remaining)
                    study.idle()
                    save(folder/'cluster-after.json', study.k.snapshot())
                    collect(PROMETHEUS, summary['start_unix_s'], time.time(), 10, folder/'telemetry', queries)
                rows = [json.loads(line) for line in (folder/'run'/'requests.jsonl').read_text().splitlines()]
                valid, passed = qualifies(summary, rows)
                record = {k: spec[k] for k in ('name', 'replicas', 'rps', 'seed', 'offered_by_tenant')}
                record.update(dispatch_valid=valid, passed=passed, summary=summary)
                records.append(record)
                save(folder/'complete.json', record)
                save(dest/'progress.json', records)
                study.event('revision-mixed-run-complete', name=spec['name'], passed=passed)
            save(dest/'complete.json', dict(results=records, capacities={str(n): capacity(records, frozen, n) for n in (1, 2)}, completed_unix_s=time.time()))
        except BaseException as exc:
            save(dest/'error.json', dict(error=repr(exc), unix_s=time.time()))
            raise
        finally:
            current = study.k.get('deployment', 'vllm')['spec']['template']['spec']['containers']
            if current[0]['args'] != trial[0]['args']:
                raise RuntimeError('Unexpected serving change; refusing blind restoration')
            study.fixed(1)
            study.control.cleanup_empty()
            rollout(original)
            study.warmup()
            save(dest/'restored.json', dict(unix_s=time.time(), deployment=study.k.get('deployment', 'vllm')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    args = parser.parse_args()
    frozen = json.loads(args.plan.read_text())
    if frozen != plan(json.loads(args.config.read_text()), frozen['rates']):
        raise ValueError('Frozen plan differs from current code/config')
    execute(args.root, frozen)


if __name__ == '__main__':
    main()
