"""Live noisy-neighbor comparison; fixed A/B rates and a fourfold C burst."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from . import revision_e3 as comparison
from .core import workload
from .revision_e2 import offered_rates
from .revision_e3_extension import DEST as EXTENSION_DEST

DEST = 'revision-20260912/e4-noisy-neighbor'
SEEDS = (841, 842, 843, 844, 845)
BASELINES = ('B3', 'B5', 'B6')
BURST = (600, 1200)


def run_config(base, seed, capacity, threshold):
    config, _, _ = comparison.e3_config(base, seed, capacity, threshold)
    rates = offered_rates(capacity, 0.65)
    noisy = dict(rates, C=4 * rates['C'])
    config.update(duration_s=1800, drain_s=180, phases=[
        dict(start_s=0, rates=rates),
        dict(start_s=BURST[0], rates=noisy),
        dict(start_s=BURST[1], rates=dict(rates)),
    ])
    rows = workload(config)
    counts = {t: sum(r['tenant'] == t for r in rows) for t in config['tenants']}
    return config, rows, counts


def plan(base, capacity):
    if capacity != 0.025 or base['tenants']['B']['ttft_s'] != 3.0:
        raise ValueError('E4 requires the documented 3s amendment and 0.025 mixed capacity')
    order = [[s, b] for s in SEEDS for b in BASELINES]
    random.Random(20261002).shuffle(order)
    traces = []
    for seed in SEEDS:
        _, rows, counts = run_config(base, seed, capacity, 0.8)
        if not all(counts.values()) or any(r['input_tokens'] + r['output_tokens'] > 32768 for r in rows):
            raise ValueError('Frozen E4 trace has missing tenants or exceeds context')
        traces.append(dict(seed=seed, offered_by_tenant=counts,
                           sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()))
    return dict(
        phase='e4-noisy-neighbor', revision='revision-20260930',
        slo_revision='revision-20260930-b-ttft-3s',
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        capacity_rps=capacity, duration_s=1800, drain_s=180, burst_s=list(BURST),
        eval_seeds=list(SEEDS), baselines=list(BASELINES), eval_order=order,
        order_seed=20261002, traces=traces, base_load_factor=0.65, c_burst_factor=4,
        slo_threshold='E2 frozen threshold; no new tuning',
        analysis=dict(primary='A SLO goodput over all offered A requests',
                      secondary=['C goodput', 'C rejection and defer fractions', 'P99 TTFT',
                                 'weighted SLO goodput', 'GPU utilization', 'tokens/s'],
                      cohorts=['whole run', '600 <= offered_s < 1200'],
                      contrasts=['B6-B5', 'B5-B3', 'B6-B3'],
                      bootstrap_replicates=10000, bootstrap_seed=20261002,
                      practical_effect=0.05, unit='paired seed; equal weight per run'),
        limitation='Five fixed seeds, no outcome selection. Low request counts limit precision; '
                   'a C arrival-rate increase is not a guarantee of queueing or scale-out. '
                   'Within-trace before/burst comparison is descriptive, not a randomized causal control.',
        matched_scale='Natural KEDA/HPA decisions only; no forced provisioning gap',
    )


def require_completed_e3(root):
    for relative, baselines in ((comparison.DEST, comparison.BASELINES),
                                (EXTENSION_DEST, ('B2', 'B4'))):
        source = Path(root) / relative
        if (source / 'error.json').exists() or not (source / 'restored.json').exists():
            raise RuntimeError('All E3 comparisons must complete and restore before E4')
        records = json.loads((source / 'complete.json').read_text())['results']
        expected = {(s, b) for s in (821, 822, 824, 826, 828) for b in baselines}
        if (len(records) != len(expected) or
                {(r['seed'], r['baseline']) for r in records} != expected or
                not all(r['dispatch_valid'] for r in records)):
            raise RuntimeError('E3 records are incomplete or dispatch-invalid')


def execute(root, frozen):
    import fcntl
    from .episodes import save
    root = Path(root)
    with (root / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_completed_e3(root)
        base = json.loads((root / 'configs/revision-20260930.json').read_text())
        capacity = comparison.require_qualified_two_gpu_capacity(root)
        if frozen != plan(base, capacity):
            raise ValueError('E4 frozen plan mismatch')
        threshold = comparison.require_completed_e2(root)
        comparison.require_admission_calibration(root)
        dest = root / DEST
        dest.mkdir(exist_ok=False)
        save(dest / 'frozen-plan.json', frozen)
        comparison._run_suite(root, dest, frozen, threshold, config_factory=run_config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    execute(args.root, json.loads(args.plan.read_text()))


if __name__ == '__main__':
    main()
