"""Replay the two lowest-rate misses alone; diagnostic, not capacity samples."""
import asyncio
import fcntl
import json
import time
from pathlib import Path
from crossscale import live
from crossscale.study import Study, SERVICE, MODEL
from crossscale.episodes import save

root = Path('/tmp/experiments')
with (root/'suite.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    dest = root/'diagnosis-isolated-tail'
    dest.mkdir(exist_ok=False)
    study = Study(root)
    study.idle()
    config = json.loads((root/'profile-one-bounded/rps-0.01-seed-17/run/config.json').read_text())
    config.update(duration_s=2, drain_s=180)
    cases = []
    for seed, rid in ((17,7),(19,4)):
        source = root/f'profile-one-bounded/rps-0.01-seed-{seed}/run/requests.jsonl'
        row = next(json.loads(l) for l in source.read_text().splitlines() if json.loads(l)['id']==rid)
        cases.append({k:row[k] for k in ('tenant','input_tokens','output_tokens','id')})
    cases += [dict(tenant='B',input_tokens=3072,output_tokens=256,id=0),dict(tenant='C',input_tokens=8192,output_tokens=1024,id=0)]
    save(dest/'design.json',dict(cases=cases,repetitions=3,purpose='Serial isolated diagnostic; original failures retained; no capacity selection'))
    study.event('isolated-tail-diagnostic-start')
    results=[]
    for rep in range(3):
        for index, case in enumerate(cases):
            row=dict(case,offered_s=1)
            live.workload=lambda c, row=row: [dict(row)]
            out=dest/f'rep-{rep}-case-{index}'
            asyncio.run(live.run(config,'B0',out,SERVICE,MODEL,root/'tokens.json'))
            results += [json.loads(l) for l in (out/'requests.jsonl').read_text().splitlines()]
    save(dest/'complete.json',dict(completed_unix_s=time.time(),results=results))
    study.event('isolated-tail-diagnostic-complete',output=str(dest))
