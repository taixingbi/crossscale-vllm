"""Frozen controlled-capacity design; live executor is deliberately separate."""
import hashlib
import json
import random

from .core import workload
from .kube import ready
from .revision_e3 import e3_config
from .revision_e2 import offered_rates

LAGS = (0, 15, 30, 60, 90, 120)
BASELINES = ('B3', 'B5', 'B6')


def run_config(base, seed, capacity, threshold):
    config, _, _ = e3_config(base, seed, capacity, threshold)
    config.update(duration_s=600, drain_s=180, phases=[
        dict(start_s=0, rates=offered_rates(capacity, .65)),
        dict(start_s=60, rates=offered_rates(capacity, 1.65)),
        dict(start_s=360, rates=offered_rates(capacity, .65)),
    ])
    rows = workload(config)
    return config, rows, {t: sum(r['tenant'] == t for r in rows) for t in config['tenants']}


def plan(base, capacity=.025):
    if capacity != .025 or base['tenants']['B']['ttft_s'] != 3:
        raise ValueError('Requires amended measured capacity and B SLO')
    examined, seeds, traces = [], [], []
    for seed in range(871, 10871):
        _, rows, counts = run_config(base, seed, capacity, .8)
        selected = all(counts.values())
        examined.append(dict(seed=seed, counts=counts, selected=selected))
        if selected:
            seeds.append(seed)
            traces.append(dict(seed=seed, sha256=hashlib.sha256(
                json.dumps(rows, sort_keys=True).encode()).hexdigest(), counts=counts))
        if len(seeds) == 5:
            break
    if len(seeds) != 5:
        raise ValueError('Insufficient nonempty-tenant seeds')
    order = [[s, lag, b] for s in seeds for lag in LAGS for b in BASELINES]
    random.Random(20261003).shuffle(order)
    return dict(phase='e5-controlled-prewarmed-capacity', capacity_rps=capacity,
                slo_revision='revision-20260930-b-ttft-3s',
                serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
                eval_seeds=seeds, examined=examined, traces=traces, eval_order=order,
                order_seed=20261003, lags_s=list(LAGS), baselines=list(BASELINES),
                duration_s=600, drain_s=180, burst_s=[60, 360],
                initial_usable=2, prewarmed_replicas=4, release_trigger_s=60,
                release_tolerance_s=5, observer_interval_s=.5,
                supply='Fixed matched two-to-four usable-capacity schedule; no HPA during measurement',
                eta='B6 knows nominal scheduled release; observed EndpointSlice/Ready lag is retained',
                baseline_scope='B3 admission bypass, B5 Ready-only, B6 scheduled-ETA admission; '
                               'these controlled variants do not compare slow scaling decisions',
                analysis=dict(primary='weighted SLO goodput over all offered requests',
                              secondary=['A goodput', 'P99 TTFT', 'reject/defer fractions',
                                         'GPU utilization', 'tokens/s'],
                              cohorts=['whole run', 'burst', 'observed controlled-capacity gap'],
                              contrasts=['B6-B5', 'B5-B3', 'B6-B3'],
                              bootstrap_samples=10000, bootstrap_seed=20261003,
                              practical_effect=.05, resampling_unit='paired seed within each lag'),
                limitations=['Prewarmed controlled capacity is not natural EC2 provisioning.',
                             'All four GPUs consume resources while two are withheld.',
                             'Nonempty-tenant seed selection and sparse counts limit inference.',
                             'Nominal scheduled ETA is not an oracle for actual readiness.',
                             'Zero nominal lag retains measured Kubernetes propagation latency.'])


def capacity_state(snapshot, baseline_uids, withheld_uids, start_unix_s, lag_s):
    """Read actual readiness; planned release never creates dispatch slots."""
    expected = set(baseline_uids) | set(withheld_uids)
    if (len(set(baseline_uids)) != 2 or len(set(withheld_uids)) != 2 or
            len(expected) != 4 or lag_s not in LAGS):
        raise ValueError('Expected two baseline and two withheld identities and a frozen lag')
    pods = [p for p in snapshot['pods'] if not p['metadata'].get('deletionTimestamp')]
    if {p['metadata']['uid'] for p in pods} != expected:
        raise RuntimeError('Controlled-capacity pod identities changed')
    actual_ready = {p['metadata']['uid'] for p in pods if ready(p)}
    if not set(baseline_uids) <= actual_ready:
        raise RuntimeError('Baseline usable capacity was lost')
    now = snapshot['observed_unix_s']
    trigger = None if start_unix_s is None else start_unix_s + 60
    target = None if trigger is None else trigger + lag_s
    if (target is None or now < target) and actual_ready & set(withheld_uids):
        raise RuntimeError('Withheld capacity became Ready before scheduled release')
    desired = 4 if trigger is not None and now >= trigger else 2
    pending = ([target for uid in withheld_uids if uid not in actual_ready]
               if desired == 4 else [])
    return dict(observed_unix_s=now, ready=len(actual_ready), desired=desired,
                pending_eta_unix_s=pending,
                capacity_source='actual Kubernetes Ready; controlled prewarmed release',
                actual_deployment_desired=snapshot['deployment']['spec']['replicas'],
                release_target_unix_s=target)
