"""Collect separate 4096-serving E0 evidence without reusing original ETA data."""
import copy
import fcntl
import json
import os
import time
from pathlib import Path
from crossscale.episodes import Episodes, ready, save
from crossscale.study import Study

root = Path('/tmp/experiments')


class SeparateEpisodes(Episodes):
    def event(self, event, **details):
        details = dict(details, serving_condition='prefill4096', e0_root=str(self.root))
        super().event(event, **details)
        row = dict(unix_s=time.time(), event=event, **details)
        with (root/'e0'/'events.jsonl').open('a') as f:
            f.write(json.dumps(row)+'\n')
        row['e0_prefill4096'] = {
            name: len(list((self.root/name).glob('episode-*/summary.json')))
            for name in ('cached-on-existing-node', 'cold-new-node', 'prebaked-image-new-node')
        }
        save(root/'status.json', row)

    def remember_claims(self):
        super().remember_claims()
        # Keep the task-wide ownership ledger current for subsequent cleanup.
        save(root/'e0'/'ownership.json', self.ownership)


with (root/'suite.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    dest = root/'e0-prefill4096'
    dest.mkdir(exist_ok=False)
    (root/'study.pid').write_text(str(os.getpid()))
    study = Study(root)
    study.idle()
    study.fixed(1)
    study.control.cleanup_empty()
    before = study.k.get('deployment', 'vllm')
    save(dest/'deployment-before.json', before)
    original = before['spec']['template']['spec']['containers']
    trial = copy.deepcopy(original)
    args = trial[0]['args']
    assert args[args.index('--max-num-batched-tokens')+1] == '1024'
    args[args.index('--max-num-batched-tokens')+1] = '4096'
    save(dest/'ownership.json', study.control.ownership)
    study.control = SeparateEpisodes(dest)

    def apply_and_wait(containers):
        study.k.patch('deployment', 'vllm', {'spec': {'template': {'spec': {'containers': containers}}}})
        deadline = time.monotonic()+1200
        while time.monotonic()<deadline:
            pods = study.k.get('pods', selector='app=vllm')['items']
            if len(pods)==1 and not pods[0]['metadata'].get('deletionTimestamp') and ready(pods[0]) and pods[0]['spec']['containers'][0]['args']==containers[0]['args']:
                return
            time.sleep(3)
        raise TimeoutError('E0 trial/restore rollout did not become Ready')

    try:
        study.control.event('e0-prefill4096-rollout-start')
        apply_and_wait(trial)
        study.warmup()
        save(dest/'deployment-trial.json', study.k.get('deployment', 'vllm'))
        results = []
        for name, nodeclass in (
            ('cached-on-existing-node', 'crossscale-gpu'),
            ('cold-new-node', 'crossscale-gpu'),
            ('prebaked-image-new-node', 'crossscale-gpu-prebaked'),
        ):
            results.append(study.control.condition(name, nodeclass, repetitions=30))
        save(dest/'complete.json', dict(completed_unix_s=time.time(), conditions=results))
        study.control.event('e0-prefill4096-complete')
    except Exception as exc:
        save(dest/'error.json', dict(unix_s=time.time(), error=repr(exc)))
        study.control.event('needs-diagnosis', error=repr(exc))
        # Preserve the failure state for inspection, including serving settings.
        raise
    else:
        current = study.k.get('deployment','vllm')['spec']['template']['spec']['containers']
        if current[0]['args'] != trial[0]['args']:
            raise RuntimeError('Unexpected serving change; refusing blind restore')
        study.fixed(1)
        study.control.cleanup_empty()
        study.k.patch('nodepool', 'crossscale-gpu', {'spec': {'template': {'spec': {'nodeClassRef': {'group': 'karpenter.k8s.aws', 'kind': 'EC2NodeClass', 'name': 'crossscale-gpu'}}}}})
        apply_and_wait(original)
        study.warmup()
        save(dest/'restored.json', dict(unix_s=time.time(), deployment=study.k.get('deployment','vllm')))
        study.control.event('e0-prefill4096-restored')
