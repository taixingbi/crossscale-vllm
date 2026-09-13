"""Offline mixed-load plan builder; this module never contacts the cluster."""
import copy
import argparse
import hashlib
import json
import math
from pathlib import Path

from .core import workload

SEEDS = (701, 702, 703, 704, 705)
MIN_SAMPLES = 60


def plan(base, rates):
    """Pair identical 4:2:1 traces across one and two fixed replicas.

    Rates must be chosen and persisted before execution. Horizons target 100
    requests for the least frequent tenant; no seed is searched or replaced.
    """
    rates = list(rates)
    if not rates or any(not math.isfinite(r) or r <= 0 for r in rates):
        raise ValueError('Rates must be finite and positive')
    if rates != sorted(set(rates)):
        raise ValueError('Rates must be unique and increasing')
    if set(base['tenants']) != {'A', 'B', 'C'}:
        raise ValueError('Expected the full A/B/C workload')
    runs = []
    for replicas in (1, 2):
        for rate in rates:
            for seed in SEEDS:
                c = copy.deepcopy(base)
                c.update(seed=seed, duration_s=max(600, math.ceil(700/rate)),
                         initial_replicas=replicas, max_replicas=replicas,
                         client_force_close=True, upstream_force_close=True,
                         serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off')
                c['phases'] = [{'start_s': 0, 'rates':
                                {'A': rate*4/7, 'B': rate*2/7, 'C': rate/7}}]
                trace = workload(c)
                counts = {t: sum(r['tenant'] == t for r in trace) for t in c['tenants']}
                if min(counts.values()) < MIN_SAMPLES:
                    raise ValueError('Insufficient samples; predeclare a longer horizon, never replace seeds')
                if any(r['input_tokens']+r['output_tokens'] > 32768 for r in trace):
                    raise ValueError('Trace exceeds context')
                runs.append(dict(name=f'mixed-gpu-{replicas}-rps-{rate}-seed-{seed}',
                                 replicas=replicas, rps=rate, seed=seed,
                                 offered_by_tenant=counts, config=c))
    return dict(revision='revision-20260912', phase='e1-mixed', batch_tokens=4096,
                rates=rates, seeds=list(SEEDS), min_samples=MIN_SAMPLES, runs=runs)


def qualifies(summary, rows):
    valid = bool(rows) and all(r.get('dispatch_lag_s', float('inf')) <= .05 for r in rows)
    passing = valid and all(
        summary['tenants'].get(t, {}).get('offered', 0) >= MIN_SAMPLES
        and summary['tenants'][t].get('goodput') is not None
        and summary['tenants'][t]['goodput'] >= .95 for t in ('A', 'B', 'C'))
    return valid, passing


def capacity(records, frozen, replicas):
    result = None
    for rate in frozen['rates']:
        runs = [r for r in records if r['replicas'] == replicas and r['rps'] == rate]
        if (len(runs) != len(frozen['seeds'])
                or {r['seed'] for r in runs} != set(frozen['seeds'])
                or not all(r['dispatch_valid'] and r['passed'] for r in runs)):
            break
        result = rate
    return result


def freeze(base, rates, destination):
    """Write a new plan exclusively; never overwrite a prior declaration."""
    frozen = plan(base, rates)
    payload = (json.dumps(frozen, indent=2, allow_nan=False)+'\n').encode()
    arrival = sum(r['config']['duration_s'] for r in frozen['runs'])
    drain = sum(r['config']['drain_s'] for r in frozen['runs'])
    with Path(destination).open('xb') as stream:
        stream.write(payload)
    return dict(plan=str(destination), sha256=hashlib.sha256(payload).hexdigest(),
                runs=len(frozen['runs']), arrival_hours=arrival/3600,
                drain_hours=drain/3600,
                minimum_runtime_hours=(arrival+drain)/3600,
                excludes='Provisioning, rollouts, warmups, export and restoration',
                execution_started=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--rates', type=float, nargs='+', required=True)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(json.loads(args.config.read_text()), args.rates, args.plan)))


if __name__ == '__main__':
    main()
