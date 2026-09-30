"""E2 B2/B3 live comparison under the 2026-09-30 SLO amendment."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def prefill_slo_infeasibility(rows, ttft_s=1.5):
    """Serial long-prompt TTFT versus the frozen B SLO.

    rows are completed diagnostic requests with input_tokens and ttft_s.
    """
    usable = [r for r in rows if r.get('ttft_s') and r.get('input_tokens')]
    if not usable:
        raise ValueError('Expected serial diagnostic TTFT evidence')
    rates = [r['input_tokens'] / r['ttft_s'] for r in usable]
    mean_rate = sum(rates) / len(rates)
    longest = max(r['input_tokens'] for r in usable)
    coverable = mean_rate * ttft_s
    misses = [r for r in usable if r['ttft_s'] > ttft_s]
    return dict(
        samples=len(usable),
        measured_prefill_tokens_s=mean_rate,
        slo_ttft_s=ttft_s,
        longest_prompt_tokens=longest,
        tokens_coverable_in_slo=coverable,
        longest_prompt_required_tokens_s=longest / ttft_s,
        ttft_misses=len(misses),
        infeasible=longest > coverable or bool(misses),
    )


def batch_increase_cannot_meet_slo(rows, batch_tokens=8192, ttft_s=1.5):
    """A larger max-num-batched-tokens cannot cut the measured prefill-token work.

    TTFT includes the full prompt prefill. Increasing the batch window only
    reduces the number of engine steps, not the tokens that must be processed.
    """
    floor = prefill_slo_infeasibility(rows, ttft_s=ttft_s)
    misses = [r for r in rows if r.get('ttft_s') and r['ttft_s'] > ttft_s]
    already_one_chunk = sum(r['input_tokens'] <= batch_tokens for r in misses)
    full_prompt_s = floor['longest_prompt_tokens'] / floor['measured_prefill_tokens_s']
    if not misses:
        reason = 'no SLO misses to justify a larger batch window'
    else:
        reason = (
            f'{already_one_chunk}/{len(misses)} SLO misses already fit in one {batch_tokens}-token '
            f'window; the longest prompt still needs {full_prompt_s:.2f}s of prefill at the '
            f'measured {floor["measured_prefill_tokens_s"]:.0f} tok/s, above the {ttft_s}s SLO.'
        )
    return dict(
        **floor,
        current_batch_tokens=batch_tokens,
        misses_already_one_chunk=already_one_chunk,
        longest_prompt_prefill_s=full_prompt_s,
        justified=False,
        reason=reason,
    )


def diagnostic_b_tails(root, relative='revision-20260912/e2-serving-recovery-20260927/batch8192-eager/complete.json'):
    path = Path(root) / relative
    rows = json.loads(path.read_text())['results']
    return [r['request'] for r in rows if r['case'].startswith('B-source') and r['repetition'] == 0]


def require_qualified_two_gpu_capacity(root):
    root = Path(root)
    amended = root / 'revision-20260930/requalified-mixed-ledger.json'
    if amended.exists():
        ledger = json.loads(amended.read_text())
        capacity = ledger.get('qualified_capacity', {}).get('2')
        if capacity is None:
            raise RuntimeError('Amended mixed capacity is still unqualified')
        if ledger.get('slo_revision') != 'revision-20260930-b-ttft-3s':
            raise RuntimeError('Unexpected SLO revision')
        return capacity
    ledger = json.loads((root / 'revision-20260912/e1-mixed-terminal/terminal-ledger.json').read_text())
    capacity = ledger.get('qualified_capacity', {}).get('2')
    if capacity is not None:
        return capacity
    reason = ledger.get('capacity_reason', 'mixed capacity unqualified')
    try:
        analysis = batch_increase_cannot_meet_slo(diagnostic_b_tails(root))
        reason += (
            f"; serial B-tail prefill {analysis['measured_prefill_tokens_s']:.0f} tok/s covers "
            f"{analysis['tokens_coverable_in_slo']:.0f} tokens in {analysis['slo_ttft_s']}s SLO, "
            f"but the selected prompts reach {analysis['longest_prompt_tokens']} tokens. "
            + analysis['reason']
        )
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
        reason += '; serial B-tail prefill evidence is required before another serving hypothesis'
    raise RuntimeError(
        reason
        + ' Do not substitute isolated rates, sparse historical qualifications, shortened prompts, or relaxed SLOs without docs/PROTOCOL_AMENDMENT_20260930.md.'
    )


LOW_FACTOR = 0.65
HIGH_FACTOR = 1.65
DURATION_S = 300
DRAIN_S = 180
BURST = (60, 180)
TRAIN_START = 801
EVAL_START = 811
THRESHOLDS = (0.8, 1.0, 1.2)
ORDER_SEED = 20260930
DEST = 'revision-20260912/e2-b2-b3'


def offered_rates(capacity_rps, factor):
    total = capacity_rps * factor
    return {'A': total * 4 / 7, 'B': total * 2 / 7, 'C': total / 7}


def run_config(base, seed, capacity_rps, slo_threshold=1):
    from .core import workload
    config = copy.deepcopy(base)
    config.update(seed=seed, duration_s=DURATION_S, drain_s=DRAIN_S,
                  initial_replicas=2, max_replicas=4, slo_threshold=slo_threshold,
                  client_force_close=True, upstream_force_close=True,
                  serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
                  slo_revision='revision-20260930-b-ttft-3s')
    config['phases'] = [
        {'start_s': 0, 'rates': offered_rates(capacity_rps, LOW_FACTOR)},
        {'start_s': BURST[0], 'rates': offered_rates(capacity_rps, HIGH_FACTOR)},
        {'start_s': BURST[1], 'rates': offered_rates(capacity_rps, LOW_FACTOR)},
    ]
    rows = workload(config)
    counts = {t: sum(r['tenant'] == t for r in rows) for t in config['tenants']}
    return config, rows, counts


def select_seeds(base, capacity_rps, start, count):
    examined, selected = [], []
    seed = start
    while len(selected) < count:
        config, rows, counts = run_config(base, seed, capacity_rps)
        ok = all(counts[t] > 0 for t in config['tenants'])
        if ok and any(r['input_tokens'] + r['output_tokens'] > 32768 for r in rows):
            raise ValueError('E2 trace exceeds context')
        examined.append(dict(seed=seed, offered_by_tenant=counts, selected=ok))
        if ok:
            selected.append(seed)
        seed += 1
        if seed > start + 10000:
            raise ValueError('Could not find nonempty-tenant E2 seeds')
    return selected, examined


def plan(base, capacity_rps):
    """Freeze B2/B3 paired traces from amended two-GPU mixed capacity."""
    if capacity_rps != 0.025:
        raise ValueError('E2 plan requires amended two-GPU mixed capacity 0.025')
    if base['tenants']['B']['ttft_s'] != 3.0:
        raise ValueError('E2 plan requires the 3.0s B TTFT amendment')
    import random
    training, train_exam = select_seeds(base, capacity_rps, TRAIN_START, 2)
    evaluation, eval_exam = select_seeds(base, capacity_rps, EVAL_START, 5)
    order = [[seed, baseline] for seed in evaluation for baseline in ('B2', 'B3')]
    random.Random(ORDER_SEED).shuffle(order)
    return dict(
        revision='revision-20260930', phase='e2-b2-b3',
        slo_revision='revision-20260930-b-ttft-3s',
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        capacity_rps=capacity_rps, low_factor=LOW_FACTOR, high_factor=HIGH_FACTOR,
        duration_s=DURATION_S, drain_s=DRAIN_S, burst_s=list(BURST),
        training_seeds=training, training_examined=train_exam, thresholds=list(THRESHOLDS),
        eval_seeds=evaluation, eval_examined=eval_exam, eval_order=order,
        order_seed=ORDER_SEED, queue_threshold=5,
        limitation='300s capacity-normalized traces are sparse at 0.025 RPS; nonempty tenants were required, not 60 mixed samples.',
        matched_scale='forbidden; KEDA/HPA must request 2-to-4',
    )


def freeze(base, capacity_rps, destination):
    frozen = plan(base, capacity_rps)
    payload = (json.dumps(frozen, indent=2, allow_nan=False) + '\n').encode()
    with Path(destination).open('xb') as stream:
        stream.write(payload)
    return dict(plan=str(destination), sha256=hashlib.sha256(payload).hexdigest(),
                training_seeds=frozen['training_seeds'], eval_seeds=frozen['eval_seeds'])


def _run_suite(root, dest, frozen):
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
    study.remove_scaler()
    study.idle()
    study.fixed(1)
    study.control.cleanup_empty()
    before = study.k.get('deployment', 'vllm')
    original = before['spec']['template']['spec']['containers']
    trial = copy.deepcopy(original)
    args = trial[0]['args']
    if args[args.index('--max-num-batched-tokens') + 1] != '1024':
        raise RuntimeError('Expected restored 1024 serving before E2')
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
        raise TimeoutError('E2 serving rollout deadline')

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
        training = []
        for threshold in frozen['thresholds']:
            for seed in frozen['training_seeds']:
                config, _, _ = run_config(base, seed, frozen['capacity_rps'], threshold)
                study.event('e2-training-start', seed=seed, threshold=threshold)
                record = measure(dest / 'training' / f'threshold-{threshold}' / f'seed-{seed}', 'B3', config)
                training.append(record)
                save(dest / 'training-progress.json', training)
        scores = []
        for threshold in frozen['thresholds']:
            wgs = [r['summary']['weighted_slo_goodput'] for r in training if r['slo_threshold'] == threshold]
            mean = sum(wgs) / len(wgs) if wgs and all(x is not None for x in wgs) else None
            scores.append({'threshold': threshold, 'mean_wg': mean, 'training_seeds': frozen['training_seeds']})
        viable = [s for s in scores if s['mean_wg'] is not None]
        if not viable:
            raise RuntimeError('E2 SLO-threshold training produced no weighted goodput')
        selected = max(viable, key=lambda s: (s['mean_wg'], -abs(s['threshold'] - 1)))
        save(dest / 'slo-tuning.json', {'selected_threshold': selected['threshold'], 'candidates': scores})
        results = []
        for seed, baseline in frozen['eval_order']:
            config, _, _ = run_config(base, seed, frozen['capacity_rps'], selected['threshold'])
            study.event('e2-eval-start', seed=seed, baseline=baseline)
            record = measure(dest / 'eval' / f'seed-{seed}' / baseline, baseline, config)
            results.append(record)
            save(dest / 'progress.json', results)
        save(dest / 'complete.json', dict(results=results, selected_threshold=selected['threshold'],
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
        capacity = require_qualified_two_gpu_capacity(root)
        if frozen.get('capacity_rps') != capacity:
            raise RuntimeError('Frozen E2 plan does not match qualified two-GPU mixed capacity')
        dest = root / DEST
        dest.mkdir(exist_ok=False)
        save(dest / 'frozen-plan.json', frozen)
        _run_suite(root, dest, frozen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--config', type=Path, default=Path('configs/revision-20260930.json'))
    parser.add_argument('--plan', type=Path, default=Path('configs/revision-20260930-e2-b2-b3-plan.json'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    base = json.loads(args.config.read_text())
    if args.freeze:
        capacity = require_qualified_two_gpu_capacity(args.root)
        print(json.dumps(freeze(base, capacity, args.plan), indent=2))
        return
    if args.execute:
        frozen = json.loads(args.plan.read_text())
        if frozen != plan(base, frozen['capacity_rps']):
            raise ValueError('Frozen E2 plan differs from current code/config')
        execute(args.root, frozen)
        return
    print(json.dumps(prefill_slo_infeasibility(diagnostic_b_tails(args.root)), indent=2))


if __name__ == '__main__':
    main()

