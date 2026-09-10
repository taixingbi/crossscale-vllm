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
    dest = root/'profile-prefill4096-control'
    dest.mkdir(exist_ok=False)
    (root/'study.pid').write_text(str(__import__('os').getpid()))
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
        result = study.sweep('profile-one-prefill4096', 1, [.01,.015,.02,.025,.05,.075], duration=1800)
        save(dest/'complete.json',dict(completed_unix_s=time.time(),profile=result))
        study.event('prefill4096-profile-complete',sustainable_rps=result['sustainable_rps'])
    finally:
        current=study.k.get('deployment','vllm')['spec']['template']['spec']['containers']
        if current[0]['args'] != trial[0]['args']:
            raise RuntimeError('Unexpected serving change; refusing blind restore')
        apply_and_wait(original)
        study.warmup()
        save(dest/'restored.json',dict(unix_s=time.time(),deployment=study.k.get('deployment','vllm')))
        study.event('prefill-4096-diagnostic-restored')
