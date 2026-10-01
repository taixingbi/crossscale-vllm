"""E3 B3/B5/B6 live comparison. Starts only after E2 completes and restores."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from .policy import decision
from .revision_e2 import (
    DEST as E2_DEST,
    LOW_FACTOR,
    HIGH_FACTOR,
    DURATION_S,
    DRAIN_S,
    BURST,
    require_qualified_two_gpu_capacity,
    run_config,
    select_seeds,
)

EVAL_START = 821
ORDER_SEED = 20260930
DEST = 'revision-20260912/e3-b3-b5-b6'
BASELINES = ('B3', 'B5', 'B6')
ADMISSION_REVISION = 'revision-20260912'
PREFILL_TOKENS_S = 3305.8201319531686
SLOTS_PER_REPLICA = 1
PRACTICAL_EFFECT = 0.05


def e3_config(base, seed, capacity_rps, slo_threshold):
    config, rows, counts = run_config(base, seed, capacity_rps, slo_threshold)
    config.update(admission_policy_revision=ADMISSION_REVISION,
                  prefill_tokens_s=PREFILL_TOKENS_S, slots_per_replica=SLOTS_PER_REPLICA)
    return config, rows, counts


def plan(base, capacity_rps):
    if capacity_rps != 0.025:
        raise ValueError('E3 plan requires amended two-GPU mixed capacity 0.025')
    if base['tenants']['B']['ttft_s'] != 3.0:
        raise ValueError('E3 plan requires the 3.0s B TTFT amendment')
    import random
    evaluation, examined = select_seeds(base, capacity_rps, EVAL_START, 5)
    order = [[seed, baseline] for seed in evaluation for baseline in BASELINES]
    random.Random(ORDER_SEED).shuffle(order)
    return dict(
        revision='revision-20260930', phase='e3-b3-b5-b6',
        slo_revision='revision-20260930-b-ttft-3s',
        admission_policy_revision=ADMISSION_REVISION,
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        capacity_rps=capacity_rps, low_factor=LOW_FACTOR, high_factor=HIGH_FACTOR,
        duration_s=DURATION_S, drain_s=DRAIN_S, burst_s=list(BURST),
        eval_seeds=evaluation, eval_examined=examined, eval_order=order,
        order_seed=ORDER_SEED, baselines=list(BASELINES),
        slots_per_replica=SLOTS_PER_REPLICA, prefill_tokens_s=PREFILL_TOKENS_S,
        practical_effect=PRACTICAL_EFFECT,
        slo_threshold='e2-slo-tuning.json',
        limitation='Priority trio only; B2/B4 wait for this checkpoint. Uses E2 frozen SLO threshold.',
        matched_scale='forbidden; KEDA/HPA must request 2-to-4',
    )


def freeze(base, capacity_rps, destination):
    frozen = plan(base, capacity_rps)
    payload = (json.dumps(frozen, indent=2, allow_nan=False) + '\n').encode()
    with Path(destination).open('xb') as stream:
        stream.write(payload)
    return dict(plan=str(destination), sha256=hashlib.sha256(payload).hexdigest(),
                eval_seeds=frozen['eval_seeds'])


def require_admission_calibration(root):
    path = Path(root) / 'admission-prefill4096/admission-calibration.json'
    payload = json.loads(path.read_text())
    if payload['slots_per_replica'] != SLOTS_PER_REPLICA:
        raise RuntimeError('E3 slots_per_replica does not match admission calibration')
    if abs(payload['prefill_tokens_s'] - PREFILL_TOKENS_S) > 1e-6:
        raise RuntimeError('E3 prefill_tokens_s does not match admission calibration')
    return payload


def require_completed_e2(root):
    e2 = Path(root) / E2_DEST
    if (e2 / 'error.json').exists() and not (e2 / 'complete.json').exists():
        raise RuntimeError('E2 failed; E3 not started')
    if not all((e2 / name).exists() for name in ('complete.json', 'restored.json', 'slo-tuning.json', 'frozen-plan.json')):
        raise RuntimeError('E2 must complete, restore, and freeze its SLO threshold before E3')
    threshold = json.loads((e2 / 'slo-tuning.json').read_text())['selected_threshold']
    if threshold not in (0.8, 1.0, 1.2):
        raise RuntimeError('Unexpected E2 SLO threshold')
    return threshold


def b5_b6_differ_only_by_eta(config):
    request = dict(tenant='A', input_tokens=256, offered_s=0)
    if decision(config, 'B5', request, 0, 0, 4, {}, [0.1]) != 'reject':
        raise ValueError('B5 must not use pending ETA as a dispatch slot')
    if decision(config, 'B6', request, 0, 0, 4, {}, [0.1]) != 'delay':
        raise ValueError('B6 must defer on a feasible pending ETA')
    if decision(config, 'B5', request, 0, 1, 4, {}, []) != decision(config, 'B6', request, 0, 1, 4, {}, []):
        raise ValueError('B5 and B6 must match when no ETA is pending')


def _run_suite(root, dest, frozen, slo_threshold):
    import asyncio
    import os
    import subprocess
    import sys
    import time
    from urllib.request import urlopen

    from .core import summarize
    from .episodes import Observer, ready, save
    from .kube import extract
    from .live import run
    from .study import MODEL, PROMETHEUS, SERVICE, Study, prometheus
    from .telemetry import collect

    root, dest = Path(root), Path(dest)
    (root / 'study.pid').write_text(str(os.getpid()))
    study = Study(root)
    cfg = root / 'configs/revision-20260930.json'
    base = json.loads((cfg if cfg.exists() else Path('configs/revision-20260930.json')).read_text())
    eta_path = root / 'e0-prefill4096/cold-new-node/summary.json'
    eta = json.loads(eta_path.read_text())['training_p90_s'] if eta_path.exists() else 60
    sample, _, _ = e3_config(base, frozen['eval_seeds'][0], frozen['capacity_rps'], slo_threshold)
    b5_b6_differ_only_by_eta(sample)
    study.remove_scaler()
    study.idle()
    study.fixed(1)
    study.control.cleanup_empty()
    before = study.k.get('deployment', 'vllm')
    original = before['spec']['template']['spec']['containers']
    trial = copy.deepcopy(original)
    args = trial[0]['args']
    if args[args.index('--max-num-batched-tokens') + 1] != '1024':
        raise RuntimeError('Expected restored 1024 serving before E3')
    args[args.index('--max-num-batched-tokens') + 1] = '4096'
    save(dest / 'deployment-before.json', before)

    def rollout(containers):
        study.k.patch('deployment', 'vllm', {'spec': {'template': {'spec': {'containers': containers}}}})
        deadline = time.monotonic() + 2400
        while time.monotonic() < deadline:
            pods = study.k.get('pods', selector='app=vllm')['items']
            live = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
            if (len(live) == 1 and ready(live[0])
                    and live[0]['spec']['containers'][0]['args'] == containers[0]['args']):
                return live[0]
            time.sleep(3)
        raise TimeoutError('E3 serving rollout deadline')

    def measure(folder, baseline, config):
        folder = Path(folder)
        study.remove_scaler()
        study.control.baseline()
        study.control.cleanup_empty()
        study.warmup()
        gateway = None
        with Observer(study.k, folder, eta=eta, interval_s=1, capture_scaler=True) as observer:
            save(folder / 'config.json', config)
            save(folder / 'before.json', study.k.snapshot())
            log = (folder / 'gateway.log').open('w')
            try:
                gateway = subprocess.Popen(
                    [sys.executable, '-m', 'crossscale.cli', 'gateway', '--config', str(folder / 'config.json'),
                     '--baseline', baseline, '--state', str(folder / 'state.json'),
                     '--url', SERVICE, '--host', '0.0.0.0'],
                    cwd=str(root), stdout=log, stderr=log)
                deadline = time.monotonic() + 60
                while True:
                    if gateway.poll() is not None:
                        raise RuntimeError('gateway exited during startup')
                    try:
                        with urlopen('http://127.0.0.1:8080/metrics', timeout=2):
                            pass
                        up = prometheus('up{job="crossscale-gateway"}')
                        if up and all(float(x['value'][1]) == 1 for x in up) and not prometheus(
                                'crossscale_slo_saturation{job="crossscale-gateway"}'):
                            break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError('gateway not freshly scraped by Prometheus')
                    time.sleep(2)
                if baseline == 'B4':
                    if study.k.get('hpa')['items'] or study.k.get('scaledobject', 'vllm', missing_ok=True):
                        raise RuntimeError('Admission-only must have no autoscaler')
                else:
                    study.install_scaler(baseline, config.get('slo_threshold', 1))
                    until = time.monotonic() + 60
                    while time.monotonic() < until and not study.k.get('hpa')['items']:
                        time.sleep(1)
                    if not study.k.get('hpa')['items']:
                        raise RuntimeError('KEDA did not create an HPA')
                save(folder / 'scaler-before.json', {
                    'scaledobject': study.k.get('scaledobject', 'vllm', missing_ok=True),
                    'hpa': study.k.get('hpa'),
                    'deployment_uid': study.k.get('deployment', 'vllm')['metadata']['uid']})
                summary = asyncio.run(run(config, baseline, folder / 'run', 'http://127.0.0.1:8080',
                                          MODEL, root / 'tokens.json'))
                until = summary['start_unix_s'] + config['duration_s'] + config['drain_s']
                while time.time() < until:
                    time.sleep(min(5, until - time.time()))
                study.idle()
                save(folder / 'after.json', study.k.snapshot())
                save(folder / 'scaler-after.json', {
                    'scaledobject': study.k.get('scaledobject', 'vllm', missing_ok=True),
                    'hpa': study.k.get('hpa')})
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
                study.remove_scaler()
            if observer.error:
                raise RuntimeError(observer.error)
        rows = [json.loads(line) for line in (folder / 'run' / 'requests.jsonl').read_text().splitlines()]
        burst = summarize([r for r in rows if BURST[0] <= r['offered_s'] < BURST[1]],
                          dict(config, duration_s=BURST[1] - BURST[0]))
        save(folder / 'burst-summary.json', burst)
        save(folder / 'scale-summary.json', extract(folder / 'observations.jsonl.gz'))
        valid = max((r.get('dispatch_lag_s', 0) for r in rows), default=0) <= .05
        record = dict(baseline=baseline, seed=config['seed'], slo_threshold=config.get('slo_threshold'),
                      dispatch_valid=valid, summary=summary, offered_by_tenant={
                          t: sum(r['tenant'] == t for r in rows) for t in config['tenants']})
        save(folder / 'complete.json', dict(record, completed_unix_s=time.time()))
        if not valid:
            raise RuntimeError('client dispatch lag exceeded predeclared limit')
        return record

    try:
        rollout(trial)
        study.fixed(2)
        study.warmup()
        save(dest / 'deployment-trial.json', study.k.get('deployment', 'vllm'))
        save(dest / 'slo-threshold.json', dict(selected_threshold=slo_threshold, source=str(E2_DEST) + '/slo-tuning.json'))
        results = []
        for seed, baseline in frozen['eval_order']:
            config, _, _ = e3_config(base, seed, frozen['capacity_rps'], slo_threshold)
            study.event('e3-eval-start', seed=seed, baseline=baseline)
            record = measure(dest / 'eval' / f'seed-{seed}' / baseline, baseline, config)
            results.append(record)
            save(dest / 'progress.json', results)
        save(dest / 'complete.json', dict(results=results, selected_threshold=slo_threshold,
                                          completed_unix_s=time.time()))
    except BaseException as exc:
        save(dest / 'error.json', dict(error=repr(exc), unix_s=time.time()))
        raise
    finally:
        study.remove_scaler()
        current = study.k.get('deployment', 'vllm')['spec']['template']['spec']['containers']
        if current[0]['args'] != trial[0]['args']:
            raise RuntimeError('Unexpected serving change; refusing blind restoration')
        study.fixed(1)
        study.control.cleanup_empty()
        rollout(original)
        study.warmup()
        save(dest / 'restored.json', dict(unix_s=time.time(), deployment=study.k.get('deployment', 'vllm')))


def execute(root, frozen):
    import fcntl
    from .episodes import save

    root = Path(root)
    with (root / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        threshold = require_completed_e2(root)
        require_admission_calibration(root)
        capacity = require_qualified_two_gpu_capacity(root)
        if frozen.get('capacity_rps') != capacity:
            raise RuntimeError('Frozen E3 plan does not match qualified two-GPU mixed capacity')
        dest = root / DEST
        dest.mkdir(exist_ok=False)
        save(dest / 'frozen-plan.json', frozen)
        _run_suite(root, dest, frozen, threshold)


def wait_then_execute(root, frozen, poll_s=30):
    import os
    import time
    from .episodes import save

    root = Path(root)
    (root / 'e3-waiter.pid').write_text(str(os.getpid()))
    print('e3 waiter polling for E2 complete.json and restored.json', flush=True)
    e2 = root / E2_DEST
    while True:
        if (e2 / 'error.json').exists() and not (e2 / 'complete.json').exists():
            save(root / 'revision-20260912/e3-waiter-error.json',
                 dict(error='E2 failed; E3 not started', unix_s=time.time()))
            raise RuntimeError('E2 failed; E3 not started')
        if all((e2 / name).exists() for name in ('complete.json', 'restored.json', 'slo-tuning.json')):
            print('e3 waiter starting execute after E2 restore', flush=True)
            break
        time.sleep(poll_s)
    while True:
        try:
            execute(root, frozen)
            return
        except BlockingIOError:
            time.sleep(poll_s)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--config', type=Path, default=Path('configs/revision-20260930.json'))
    parser.add_argument('--plan', type=Path, default=Path('configs/revision-20260930-e3-b3-b5-b6-plan.json'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--wait-for-e2', action='store_true')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    base = json.loads(args.config.read_text())
    if args.freeze:
        capacity = require_qualified_two_gpu_capacity(args.root)
        print(json.dumps(freeze(base, capacity, args.plan), indent=2))
        return
    frozen = json.loads(args.plan.read_text())
    if frozen != plan(base, frozen['capacity_rps']):
        raise ValueError('Frozen E3 plan differs from current code/config')
    if args.wait_for_e2:
        wait_then_execute(args.root, frozen)
        return
    if args.execute:
        execute(args.root, frozen)
        return
    print(json.dumps(plan(base, frozen['capacity_rps']), indent=2))


if __name__ == '__main__':
    main()
