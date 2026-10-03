"""E7 controlled admission/tenant ablation; natural slow scaling remains separate."""
import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from .controlled_capacity import GateDriver
from .revision_e5 import run_config, verify_frozen_trace

E5_DEST = 'revision-20260912/e5-controlled-prewarmed-capacity'
E5_PLAN = Path('configs/revision-20261001-e5-plan.json')
DEST = 'revision-20260912/e7-controlled-ablations'
OWNER = 'e7-20261003'
LAG_S = 60
ORDER_SEED = 20261005
SEEDS = (871, 872, 873, 874, 875)
# no-ETA is B5. Oracle uses the known controlled release instant, labeled as
# scheduled-release knowledge, not a predictor of natural EC2 readiness.
VARIANTS = (
    ('B3', 'B3', None),
    ('B5', 'B5', None),
    ('no-tenant', 'no-tenant', 0.0),
    ('CrossScale', 'B6', 0.0),
    ('Oracle', 'oracle-eta', 'oracle'),
)


def variant_map():
    return {name: (baseline, error) for name, baseline, error in VARIANTS}


def apply_eta_variant(state, start_unix_s, lag_s, variant):
    """Rewrite perceived ETA only. Actual Ready/desired/release stay observed."""
    if lag_s != LAG_S:
        raise ValueError('E7 holds the controlled lag at 60s')
    out = dict(state)
    trigger = None if start_unix_s is None else start_unix_s + 60
    target = None if trigger is None else trigger + lag_s
    pending_n = max(0, 4 - int(state.get('ready', 0)))
    if variant is None or state.get('desired') != 4 or not pending_n or trigger is None:
        out.update(pending_eta_unix_s=[], perceived_eta_unix_s=None,
                   eta_source='none' if variant is None else state.get('eta_source', 'scheduled-release'))
        if variant is None:
            out['eta_source'] = 'none'
        return out
    if variant == 'oracle':
        perceived, source = target, 'scheduled-release-oracle'
    else:
        perceived, source = trigger + lag_s * (1 + float(variant)), f'scheduled-release-error-{variant}'
    out.update(pending_eta_unix_s=[perceived] * pending_n, perceived_eta_unix_s=perceived,
               eta_source=source, scheduled_release_unix_s=target)
    return out


class EtaVariantDriver(GateDriver):
    def __init__(self, cluster, owner, baseline_uids, withheld_uids, lag_s, variant, tolerance_s=5):
        super().__init__(cluster, owner, baseline_uids, withheld_uids, lag_s, tolerance_s)
        self.variant = variant

    def __call__(self, snapshot):
        return apply_eta_variant(super().__call__(snapshot), self.start, self.lag, self.variant)


def plan(base, e5_plan=None):
    if base['tenants']['B']['ttft_s'] != 3.0:
        raise ValueError('E7 requires the 3.0s B TTFT amendment')
    source = e5_plan or json.loads(E5_PLAN.read_text())
    if source.get('eval_seeds') != list(SEEDS) or source.get('capacity_rps') != 0.025:
        raise ValueError('E7 reuses the frozen E5 traces and amended 0.025 capacity')
    order = [[seed, name] for seed in SEEDS for name, _, _ in VARIANTS]
    random.Random(ORDER_SEED).shuffle(order)
    return dict(
        phase='e7-controlled-ablations', revision='revision-20260930',
        slo_revision='revision-20260930-b-ttft-3s',
        admission_policy_revision='revision-20260912',
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        capacity_rps=0.025, duration_s=600, drain_s=180, burst_s=[60, 360],
        eval_seeds=list(SEEDS), traces=source['traces'], eval_order=order,
        order_seed=ORDER_SEED, variants=[name for name, _, _ in VARIANTS],
        baselines=[v[1] for v in VARIANTS], lag_s=LAG_S, eta_errors=[0.0],
        scope='E7 controlled fast-policy ablation only; natural slow-loop audit remains separate',
        initial_usable=2, prewarmed_replicas=4, release_trigger_s=60,
        release_tolerance_s=5, observer_interval_s=.5,
        slo_threshold='E2 frozen threshold; no new tuning',
        supply='Same E5 prewarmed two-to-four usable-capacity schedule; no HPA',
        eta='B6 sees scheduled release times (1+error). Oracle uses the known '
            'controlled release instant. no-eta is B5 Ready-only. Not natural EC2 ETA.',
        analysis=dict(primary='weighted SLO goodput over all offered requests',
                      secondary=['A goodput', 'P99 TTFT', 'reject/defer fractions',
                                 'GPU utilization', 'tokens/s'],
                      cohorts=['whole run', 'burst', 'observed controlled-capacity gap'],
                      contrasts=['CrossScale-B5', 'CrossScale-no-tenant', 'B5-B3', 'Oracle-CrossScale'],
                      bootstrap_samples=10000, bootstrap_seed=ORDER_SEED,
                      practical_effect=0.05, resampling_unit='paired seed'),
        limitations=['Controlled prewarmed capacity is not natural EC2 provisioning.',
                     'Oracle is scheduled-release knowledge, not a natural-readiness predictor.',
                     'CrossScale and Oracle share the same scheduled instant; any gap is only '
                     'label/implementation, not a different physical ETA.',
                     'One lag (60s) isolates ETA error; E5 already crosses lags.',
                     'Four GPUs stay allocated while two are withheld.',
                     'Slow scaling is disabled and audited absent; this does not complete the natural-scaling E7 subphase.',
                     'E5 traces are reused prospectively, not independent of E5/E6.',
                     'Sparse counts and little contention may leave tenant budgets unexercised.'],
    )


def freeze(base, destination, e5_plan=None):
    frozen = plan(base, e5_plan)
    payload = (json.dumps(frozen, indent=2, allow_nan=False) + '\n').encode()
    with Path(destination).open('xb') as stream:
        stream.write(payload)
    return dict(plan=str(destination), sha256=hashlib.sha256(payload).hexdigest(),
                eval_seeds=frozen['eval_seeds'], variants=frozen['variants'])


def require_completed_e5(root):
    e5 = Path(root) / E5_DEST
    if (e5 / 'error.json').exists() and not (e5 / 'complete.json').exists():
        raise RuntimeError('E5 failed; E7 not started')
    if not all((e5 / name).exists() for name in ('complete.json', 'restored.json', 'frozen-plan.json')):
        raise RuntimeError('E5 must complete and restore before E7')
    records = json.loads((e5 / 'complete.json').read_text())['results']
    if len(records) != 90 or not all(r.get('dispatch_valid') for r in records):
        raise RuntimeError('E5 records are incomplete or dispatch-invalid')
    return records


def require_completed_e6(root):
    dest = Path(root) / 'revision-20260912/e6-eta-error'
    if not all((dest / n).exists() for n in ('complete.json', 'restored.json')):
        raise RuntimeError('E6 must complete and restore before E7')
    records = json.loads((dest / 'complete.json').read_text())['results']
    from .revision_e6 import SEEDS as seeds, VARIANTS as variants
    expected = {(s, v[0]) for s in seeds for v in variants}
    actual = {(r['seed'], r['variant']) for r in records}
    if len(records) != len(expected) or actual != expected or not all(r['dispatch_valid'] for r in records):
        raise RuntimeError('E6 incomplete, duplicate, or invalid cells')


def execute(root, frozen, *, continuation=None):
    import asyncio
    import fcntl
    import os
    import subprocess
    import sys
    import time
    from urllib.request import urlopen

    from .episodes import Observer, save
    from .kube import ready
    from .live import run
    from .readiness_gate import CONDITION, OWNER_LABEL, patch_gate
    from .revision_e3 import require_admission_calibration, require_completed_e2
    from .study import MODEL, PROMETHEUS, SERVICE, Study, probe
    from .telemetry import collect

    root = Path(root)
    plan_builder = plan if continuation is None else continuation.plan
    destination = DEST if continuation is None else continuation.DEST
    owner = OWNER if continuation is None else continuation.OWNER
    names = variant_map() if continuation is None else continuation.variant_map()
    with (root / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base = json.loads((root / 'configs/revision-20260930.json').read_text())
        e5_plan = json.loads((root / E5_PLAN).read_text()) if (root / E5_PLAN).exists() else json.loads(E5_PLAN.read_text())
        if frozen != plan_builder(base, e5_plan):
            raise ValueError('Frozen E7 plan mismatch')
        require_completed_e5(root)
        require_completed_e6(root)
        if continuation is not None:
            continuation.require_predecessor(root)
        traces = {}
        for entry in frozen['traces']:
            seed = entry['seed']
            rows = json.loads((root / f'configs/revision-20261001-e5-traces/seed-{seed}.json').read_text())
            traces[seed] = verify_frozen_trace(rows, run_config(base, seed, 0.025, 0.8)[1], entry['sha256'])
        threshold = require_completed_e2(root)
        require_admission_calibration(root)
        dest = root / destination
        dest.mkdir(exist_ok=False)
        save(dest / 'frozen-plan.json', frozen)
        (root / 'study.pid').write_text(str(os.getpid()))
        study = Study(root)
        k = study.k
        study.remove_scaler()
        study.idle()
        study.fixed(1)
        study.control.cleanup_empty()
        before = k.get('deployment', 'vllm')
        save(dest / 'deployment-before.json', before)
        original = copy.deepcopy(before['spec']['template'])
        trial = copy.deepcopy(original)
        args = trial['spec']['containers'][0]['args']
        if args[args.index('--max-num-batched-tokens') + 1] != '1024':
            raise RuntimeError('Expected restored serving condition')
        args[args.index('--max-num-batched-tokens') + 1] = '4096'
        trial['metadata']['labels'][OWNER_LABEL] = owner
        trial['spec']['readinessGates'] = [dict(conditionType=CONDITION)]
        changed = False

        def live_pods():
            return [p for p in k.get('pods', selector='app=vllm')['items']
                    if not p['metadata'].get('deletionTimestamp')]

        def set_gates(withheld):
            for p in live_pods():
                patch_gate(k, p, owner, p['metadata']['uid'] not in withheld, time.time())

        def wait_routes(uids, timeout=30):
            until = time.monotonic() + timeout
            while time.monotonic() < until:
                pods = live_pods()
                slices = k.get('endpointslices', selector='kubernetes.io/service-name=vllm')
                ids = {e.get('targetRef', {}).get('uid') for v in slices['items'] for e in v.get('endpoints', [])
                       if e.get('conditions', {}).get('ready')}
                if ids == set(uids) and {p['metadata']['uid'] for p in pods if ready(p)} == set(uids):
                    return
                time.sleep(.5)
            raise TimeoutError('Service routes do not match actual usable capacity')

        try:
            changed = True
            k.patch('deployment', 'vllm', {'spec': {'replicas': 4, 'strategy': {'type': 'Recreate', 'rollingUpdate': None},
                                                   'template': trial}})
            until = time.monotonic() + 2400
            while time.monotonic() < until:
                pods = live_pods()
                study.control.remember_claims()
                candidates = [p for p in pods if p['metadata'].get('labels', {}).get(OWNER_LABEL) == owner]
                for p in candidates:
                    patch_gate(k, p, owner, True, time.time())
                if len(pods) == 4 and len(candidates) == 4 and all(ready(p) for p in candidates):
                    break
                time.sleep(3)
            else:
                raise TimeoutError('Four-model prewarm startup deadline')
            nodes = {c['status'].get('nodeName') for c in study.control.claims()
                     if c['metadata']['name'] in study.control.ownership['initial_claims']}
            pods.sort(key=lambda p: (p['spec']['nodeName'] not in nodes, p['metadata']['name']))
            baseline = [p['metadata']['uid'] for p in pods[:2]]
            withheld = [p['metadata']['uid'] for p in pods[2:]]
            identities = baseline + withheld
            wait_routes(identities)
            study.warmup()
            proofs = {p['metadata']['uid']: asyncio.run(probe(
                [dict(input_tokens=16384, output_tokens=2)], study.tokens,
                'http://' + p['status']['podIP'] + ':8000')) for p in pods}
            save(dest / 'prewarm-proof.json', dict(pods=pods, inference=proofs, baseline=baseline, withheld=withheld))
            results = []
            for seed, variant in frozen['eval_order']:
                baseline_name, error = names[variant]
                study.idle()
                set_gates([])
                wait_routes(identities)
                study.warmup()
                set_gates(withheld)
                wait_routes(baseline)
                config, _, _ = run_config(base, seed, 0.025, threshold)
                config.update(eta_error=0 if error in (None, 'oracle') else error,
                              e7_variant=variant)
                folder = dest / 'eval' / f'seed-{seed}' / variant
                config['policy_audit_path'] = str(folder / 'policy-decisions.jsonl')
                driver = EtaVariantDriver(k, owner, baseline, withheld, LAG_S, error)
                gateway = None
                with Observer(k, folder, interval_s=.5, capture_scaler=True, state_builder=driver) as observer:
                    save(folder / 'config.json', config)
                    log = (folder / 'gateway.log').open('w')
                    try:
                        gateway = subprocess.Popen(
                            [sys.executable, '-m', 'crossscale.cli', 'gateway',
                             '--config', str(folder / 'config.json'), '--baseline', baseline_name,
                             '--state', str(folder / 'state.json'), '--url', SERVICE, '--host', '0.0.0.0'],
                            cwd=str(root), stdout=log, stderr=log)
                        until = time.monotonic() + 60
                        while True:
                            if gateway.poll() is not None:
                                raise RuntimeError('Gateway startup failed')
                            try:
                                with urlopen('http://127.0.0.1:8080/metrics', timeout=2):
                                    break
                            except OSError:
                                if time.monotonic() > until:
                                    raise TimeoutError('Gateway startup')
                                time.sleep(.5)
                        if k.get('hpa')['items'] or k.get('scaledobject', 'vllm', missing_ok=True):
                            raise RuntimeError('Controlled schedule requires no autoscaler')
                        study.event('e7-measure-start', seed=seed, variant=variant, lag=LAG_S, baseline=baseline_name)
                        summary = asyncio.run(run(config, baseline_name, folder / 'run', 'http://127.0.0.1:8080',
                                                  MODEL, root / 'tokens.json', trace=traces[seed],
                                                  on_start=driver.on_start))
                        until = summary['start_unix_s'] + config['duration_s'] + config['drain_s']
                        while time.time() < until:
                            if observer.error:
                                raise RuntimeError(observer.error)
                            time.sleep(min(2, until - time.time()))
                        if k.get('hpa')['items'] or k.get('scaledobject', 'vllm', missing_ok=True):
                            raise RuntimeError('Unexpected slow scaler during controlled E7')
                        study.idle()
                        collect(PROMETHEUS, summary['start_unix_s'], time.time(), 5, folder / 'telemetry')
                    finally:
                        if gateway is not None:
                            gateway.terminate()
                            try:
                                gateway.wait(timeout=15)
                            except subprocess.TimeoutExpired:
                                gateway.kill()
                                gateway.wait()
                        log.close()
                if driver.observed_release is None:
                    raise RuntimeError('No observed controlled release')
                rows = [json.loads(x) for x in (folder / 'run/requests.jsonl').read_text().splitlines()]
                valid = max((r.get('dispatch_lag_s', 0) for r in rows), default=0) <= .05
                record = dict(seed=seed, variant=variant, baseline=baseline_name, eta_error=error,
                              lag_s=LAG_S, dispatch_valid=valid, summary=summary,
                              nominal_release_unix_s=driver.start + 60 + LAG_S,
                              observed_release_unix_s=driver.observed_release)
                save(folder / 'complete.json', record)
                results.append(record)
                save(dest / 'progress.json', results)
                if not valid:
                    raise RuntimeError('Dispatch validity exceeded')
            save(dest / 'complete.json', dict(results=results, completed_unix_s=time.time()))
        except BaseException as exc:
            save(dest / 'error.json', dict(error=repr(exc), unix_s=time.time()))
            raise
        finally:
            if changed:
                for p in live_pods():
                    if p['metadata'].get('labels', {}).get(OWNER_LABEL) == owner:
                        patch_gate(k, p, owner, True, time.time())
                study.fixed(1)
                study.control.cleanup_empty()
                restore = copy.deepcopy(original)
                restore['metadata']['labels'][OWNER_LABEL] = None
                restore['spec']['readinessGates'] = original['spec'].get('readinessGates')
                k.patch('deployment', 'vllm', {'spec': {'replicas': 1, 'template': restore,
                                                        'strategy': before['spec']['strategy']}})
                study.control.wait_ready(1)
                study.warmup()
                save(dest / 'restored.json', dict(unix_s=time.time(), deployment=k.get('deployment', 'vllm')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--config', type=Path, default=Path('configs/revision-20260930.json'))
    parser.add_argument('--plan', type=Path, default=Path('configs/revision-20261003-e7-plan.json'))
    parser.add_argument('--e5-plan', type=Path, default=E5_PLAN)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    base = json.loads(args.config.read_text())
    e5_plan = json.loads(args.e5_plan.read_text())
    if args.freeze:
        print(json.dumps(freeze(base, args.plan, e5_plan), indent=2))
        return
    frozen = json.loads(args.plan.read_text())
    if frozen != plan(base, e5_plan):
        raise ValueError('Frozen E7 plan differs from current code/config')
    if args.execute:
        execute(args.root, frozen)
        return
    print(json.dumps(plan(base, e5_plan), indent=2))


if __name__ == '__main__':
    main()
