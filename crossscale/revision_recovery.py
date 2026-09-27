"""Frozen serving diagnostics after E1; diagnostic results are not capacity."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

RECOVERY = 'e2-serving-recovery-20260927'


def build_plan(base, mixed):
    mixed = Path(mixed)
    sources, traces = [], []
    for replicas in (1, 2):
        path = mixed / f'mixed-gpu-{replicas}-rps-0.01-seed-704/run/requests.jsonl'
        payload = path.read_bytes()
        sources.append(dict(path=str(path.relative_to(mixed)),
                            sha256=hashlib.sha256(payload).hexdigest()))
        rows = [json.loads(line) for line in payload.splitlines()]
        if any(r['status'] != 'completed' or r['dispatch_lag_s'] > .05 for r in rows):
            raise ValueError('Expected complete, dispatch-valid source evidence')
        traces.append(rows)
    keys = ('id', 'tenant', 'offered_s', 'input_tokens', 'output_tokens')
    if [{k: r[k] for k in keys} for r in traces[0]] != [
            {k: r[k] for k in keys} for r in traces[1]]:
        raise ValueError('Diagnostic source traces are not paired')
    misses = [{r['id'] for r in rows if r['tenant'] == 'B' and r['ttft_s'] > base['tenants']['B']['ttft_s']}
              for rows in traces]
    if not misses[0] or misses[0] != misses[1]:
        raise ValueError('Expected identical nonempty B-tail failure sets')
    cases = [dict(name=f'B-source-704-id-{r["id"]}',
                  request={k: r[k] for k in keys if k != 'offered_s'})
             for r in traces[0] if r['id'] in misses[0]]
    for tenant, length, output in [('A', 256, 128), ('B', 3072, 256),
                                    ('C', 8192, 1024), ('C', 16384, 1024)]:
        cases.append(dict(name=f'{tenant}-control-{length}',
                          request=dict(id=0, tenant=tenant, input_tokens=length, output_tokens=output)))
    config = copy.deepcopy(base)
    config.update(duration_s=1, drain_s=180, initial_replicas=1, max_replicas=1,
                  client_force_close=True, upstream_force_close=True)
    return dict(phase=RECOVERY, repetitions=3, sources=sources, cases=cases, config=config,
                conditions=[dict(name=f'batch{batch}-{mode}', batch_tokens=batch, eager=eager)
                            for batch, mode, eager in [(4096, 'eager', True), (8192, 'eager', True),
                                                      (4096, 'compiled', False), (8192, 'compiled', False)]],
                selection='Diagnostic only; no automatic capacity qualification or E2 launch',
                limitations=['Cases selected from failures, not an unbiased capacity sample.',
                             'New serving conditions require new calibration and condition-specific ETA evidence.',
                             'Larger batch or compilation may regress performance or fail startup; retain all failures.'])


def require_completed_mixed(root):
    mixed = Path(root) / 'revision-20260912/e1-mixed'
    if (mixed / 'error.json').exists():
        raise RuntimeError('Mixed calibration error requires diagnosis')
    if not all((mixed / f).exists() for f in ('complete.json', 'restored.json', 'frozen-plan.json')):
        raise RuntimeError('Frozen mixed calibration must complete and restore before diagnostics')
    plan = json.loads((mixed / 'frozen-plan.json').read_text())
    complete = json.loads((mixed / 'complete.json').read_text())
    expected = [r['name'] for r in plan['runs']]
    actual = [r['name'] for r in complete['results']]
    if len(expected) != 30 or len(actual) != 30 or set(actual) != set(expected):
        raise RuntimeError('All 30 frozen runs must be accounted for')
    return mixed


def condition_containers(original, condition):
    containers = copy.deepcopy(original)
    args = containers[0]['args']
    args[args.index('--max-num-batched-tokens') + 1] = str(condition['batch_tokens'])
    if '--enforce-eager' in args:
        args.remove('--enforce-eager')
    if condition['eager']:
        args.append('--enforce-eager')
    return containers


def execute(root, frozen):
    import asyncio
    import fcntl
    import os
    import time
    from .episodes import Observer, ready, save
    from .study import Study, SERVICE, MODEL
    from .live import run
    from . import live

    root = Path(root)
    with (root / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mixed = require_completed_mixed(root)
        if frozen != build_plan(json.loads((root / 'configs/default.json').read_text()), mixed):
            raise ValueError('Frozen recovery plan differs from source evidence/config')
        dest = root / 'revision-20260912' / RECOVERY
        dest.mkdir(exist_ok=False)
        save(dest / 'frozen-plan.json', frozen)
        (root / 'study.pid').write_text(str(os.getpid()))
        save(dest / 'source-manifest.json', {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), Path(live.__file__), root / 'tokens.json')})
        study = Study(root)
        before = study.k.get('deployment', 'vllm')
        original = before['spec']['template']['spec']['containers']
        args = original[0]['args']
        if before['spec']['replicas'] != 1 or args[args.index('--max-num-batched-tokens') + 1] != '1024':
            raise RuntimeError('Expected one replica in restored 1024 condition')
        if study.k.get('scaledobject', 'vllm', missing_ok=True) or study.k.get('hpa')['items']:
            raise RuntimeError('Unexpected scaler; refusing diagnostic mutation')
        save(dest / 'deployment-before.json', before)
        known = [original] + [condition_containers(original, c) for c in frozen['conditions']]
        original_nodes = {c.get('status', {}).get('nodeName') for c in study.control.claims()
                          if c['metadata']['name'] in study.control.ownership['initial_claims']}

        def rollout(containers):
            study.k.patch('deployment', 'vllm', {'spec': {'template': {'spec': {'containers': containers}}}})
            deadline = time.monotonic() + 2400
            while time.monotonic() < deadline:
                pods = study.k.get('pods', selector='app=vllm')['items']
                if (len(pods) == 1 and ready(pods[0]) and not pods[0]['metadata'].get('deletionTimestamp')
                        and pods[0]['spec']['containers'][0]['args'] == containers[0]['args']):
                    if pods[0]['spec']['nodeName'] not in original_nodes:
                        raise RuntimeError('Diagnostic replica is not on the preserved original GPU')
                    return
                time.sleep(3)
            raise TimeoutError('Diagnostic rollout did not become Ready within 2400 seconds')

        try:
            study.idle()
            for condition in frozen['conditions']:
                study.event('serving-recovery-condition-start', condition=condition['name'])
                folder = dest / condition['name']
                with Observer(study.k, folder, interval_s=5):
                    rollout(condition_containers(original, condition))
                    save(folder / 'deployment.json', study.k.get('deployment', 'vllm'))
                    for _ in range(3):
                        study.warmup()
                    outcomes = []
                    for rep in range(frozen['repetitions']):
                        cases = frozen['cases'][rep:] + frozen['cases'][:rep]
                        for case in cases:
                            study.idle()
                            out = folder / f'rep-{rep}-{case["name"]}'
                            awaitable = run(frozen['config'], 'B0', out, SERVICE, MODEL,
                                            root / 'tokens.json',
                                            trace=[dict(case['request'], offered_s=.1)])
                            asyncio.run(awaitable)
                            row = json.loads((out / 'requests.jsonl').read_text())
                            outcomes.append(dict(case=case['name'], repetition=rep, request=row,
                                                 dispatch_valid=row.get('dispatch_lag_s', float('inf')) <= .05))
                            save(folder / 'progress.json', outcomes)
                            if row['status'] != 'completed':
                                raise RuntimeError('Diagnostic request failed; evidence preserved')
                            if row.get('dispatch_lag_s', float('inf')) > .05:
                                raise RuntimeError('Diagnostic dispatch invalid; evidence preserved')
                    save(folder / 'complete.json', dict(results=outcomes, completed_unix_s=time.time(),
                                                       diagnostic_only=True))
                study.event('serving-recovery-condition-complete', condition=condition['name'])
            save(dest / 'complete.json', dict(completed_unix_s=time.time(), diagnostic_only=True))
        except BaseException as exc:
            save(dest / 'error.json', dict(error=repr(exc), unix_s=time.time()))
            raise
        finally:
            current = study.k.get('deployment', 'vllm')
            if (current['metadata']['uid'] != before['metadata']['uid']
                    or current['spec']['replicas'] != 1
                    or current['spec']['template']['spec']['containers'] not in known):
                raise RuntimeError('Unexpected deployment change; refusing blind restoration')
            rollout(original)
            study.warmup()
            save(dest / 'restored.json', dict(unix_s=time.time(), deployment=study.k.get('deployment', 'vllm')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--mixed', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        execute(args.root, json.loads(args.plan.read_text()))
    else:
        if args.mixed is None:
            parser.error('--mixed source directory required to freeze plan')
        payload = (json.dumps(build_plan(json.loads(args.config.read_text()), args.mixed), indent=2,
                              allow_nan=False) + '\n').encode()
        with args.plan.open('xb') as stream:
            stream.write(payload)
        print(json.dumps(dict(plan=str(args.plan), sha256=hashlib.sha256(payload).hexdigest(),
                              execution_started=False)))


if __name__ == '__main__':
    main()
