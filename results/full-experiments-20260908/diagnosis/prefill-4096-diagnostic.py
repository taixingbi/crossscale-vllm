"""Replay the two lowest-rate misses alone; diagnostic, not capacity samples."""
import copy
import asyncio
import fcntl
import json
import time
from pathlib import Path
from crossscale import live
from crossscale.study import Study, SERVICE, MODEL
from crossscale.episodes import save, ready

root = Path('/tmp/experiments')
with (root/'suite.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    dest = root/'diagnosis-prefill-4096'
    dest.mkdir(exist_ok=False)
    study = Study(root)
    study.idle()
    before = study.k.get('deployment', 'vllm')
    save(dest/'deployment-before.json', before)
    original = before['spec']['template']['spec']['containers']
    trial = copy.deepcopy(original)
    args = trial[0]['args']
    assert args[args.index('--max-num-batched-tokens')+1] == '1024'
    args[args.index('--max-num-batched-tokens')+1] = '4096'
    def apply_and_wait(containers):
        study.k.patch('deployment', 'vllm', {'spec': {'template': {'spec': {'containers': containers}}}})
        deadline = time.monotonic()+1200
        while time.monotonic()<deadline:
            pods=study.k.get('pods', selector='app=vllm')['items']
            if len(pods)==1 and not pods[0]['metadata'].get('deletionTimestamp') and ready(pods[0]) and pods[0]['spec']['containers'][0]['args']==containers[0]['args']:
                return
            time.sleep(3)
        raise TimeoutError('Trial/restore rollout did not become Ready')
    try:
        study.event('prefill-4096-rollout-start')
        apply_and_wait(trial)
        save(dest/'deployment-trial.json', study.k.get('deployment', 'vllm'))
        study.warmup()
        config = json.loads((root/'profile-one-bounded/rps-0.01-seed-17/run/config.json').read_text())
        config.update(duration_s=2, drain_s=180)
        cases = []
        for seed, rid in ((17,7),(19,4)):
            source = root/f'profile-one-bounded/rps-0.01-seed-{seed}/run/requests.jsonl'
            row = next(json.loads(l) for l in source.read_text().splitlines() if json.loads(l)['id']==rid)
            cases.append({k:row[k] for k in ('tenant','input_tokens','output_tokens','id')})
        cases += [dict(tenant='B',input_tokens=3072,output_tokens=256,id=0),dict(tenant='C',input_tokens=8192,output_tokens=1024,id=0)]
        save(dest/'design.json',dict(cases=cases,repetitions=3,purpose='Serial isolated diagnostic; original failures retained; no capacity selection'))
        study.event('prefill-4096-diagnostic-start')
        results=[]
        for rep in range(3):
            for index, case in enumerate(cases):
                row=dict(case,offered_s=1)
                live.workload=lambda c, row=row: [dict(row)]
                out=dest/f'rep-{rep}-case-{index}'
                asyncio.run(live.run(config,'B0',out,SERVICE,MODEL,root/'tokens.json'))
                results += [json.loads(l) for l in (out/'requests.jsonl').read_text().splitlines()]
        save(dest/'complete.json',dict(completed_unix_s=time.time(),results=results))
        study.event('prefill-4096-diagnostic-complete',output=str(dest))
    finally:
        current=study.k.get('deployment','vllm')['spec']['template']['spec']['containers']
        if current[0]['args'] != trial[0]['args']:
            raise RuntimeError('Unexpected serving change; refusing blind restore')
        apply_and_wait(original)
        study.warmup()
        save(dest/'restored.json',dict(unix_s=time.time(),deployment=study.k.get('deployment','vllm')))
        study.event('prefill-4096-diagnostic-restored')
