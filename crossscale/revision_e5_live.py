"""Execute frozen E5 with real Kubernetes readiness gates and observed routing."""
import argparse
import asyncio
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

from . import revision_e5 as design
from .controlled_capacity import GateDriver
from .episodes import Observer, save
from .kube import ready
from .live import run
from .readiness_gate import CONDITION, OWNER_LABEL, patch_gate
from .revision_e3 import require_completed_e2, require_admission_calibration
from .study import Study, SERVICE, MODEL, PROMETHEUS, probe
from .telemetry import collect

DEST='revision-20260912/e5-controlled-prewarmed-capacity'
OWNER='e5-20261001'


def execute(root, frozen):
    root=Path(root)
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base=json.loads((root/'configs/revision-20260930.json').read_text())
        generated_plan=design.plan(base)
        if ({k:v for k,v in frozen.items() if k!='traces'} !=
                {k:v for k,v in generated_plan.items() if k!='traces'}):
            raise ValueError('Frozen E5 plan mismatch')
        traces={}
        for entry in frozen['traces']:
            seed=entry['seed']
            rows=json.loads((root/f'configs/revision-20261001-e5-traces/seed-{seed}.json').read_text())
            traces[seed]=design.verify_frozen_trace(rows,design.run_config(base,seed,.025,.8)[1],entry['sha256'])
        e4=root/'revision-20260912/e4-noisy-neighbor'
        records=json.loads((e4/'complete.json').read_text())['results']
        if (len(records)!=15 or not all(r['dispatch_valid'] for r in records)
                or not (e4/'restored.json').exists() or (e4/'error.json').exists()):
            raise RuntimeError('E4 must complete and restore')
        for name in ('readiness-validation-20261001','readiness-gpu-validation-20261001'):
            evidence=root/name
            results=json.loads((evidence/'complete.json').read_text())['results']
            if ([r['lag_s'] for r in results]!=list(design.LAGS)
                    or not (evidence/'cleaned.json').exists() or (evidence/'error.json').exists()
                    or not all(not r['blocked_probe']['ok'] and r['released_probe']['ok']
                               and 0<=r['late_s']<=5 for r in results)):
                raise RuntimeError('Readiness validation incomplete')
        threshold=require_completed_e2(root);require_admission_calibration(root)
        dest=root/DEST;dest.mkdir(exist_ok=False);save(dest/'frozen-plan.json',frozen)
        (root/'study.pid').write_text(str(os.getpid()))
        study=Study(root);k=study.k
        study.remove_scaler();study.idle();study.fixed(1);study.control.cleanup_empty()
        before=k.get('deployment','vllm');save(dest/'deployment-before.json',before)
        original=copy.deepcopy(before['spec']['template'])
        trial=copy.deepcopy(original)
        args=trial['spec']['containers'][0]['args']
        if args[args.index('--max-num-batched-tokens')+1]!='1024':
            raise RuntimeError('Expected restored serving condition')
        args[args.index('--max-num-batched-tokens')+1]='4096'
        trial['metadata']['labels'][OWNER_LABEL]=OWNER
        trial['spec']['readinessGates']=[dict(conditionType=CONDITION)]
        changed=False

        def live_pods():
            return [p for p in k.get('pods',selector='app=vllm')['items']
                    if not p['metadata'].get('deletionTimestamp')]

        def set_gates(withheld):
            for p in live_pods():
                patch_gate(k,p,OWNER,p['metadata']['uid'] not in withheld,time.time())

        def wait_routes(uids,timeout=30):
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                pods=live_pods()
                s=k.get('endpointslices',selector='kubernetes.io/service-name=vllm')
                ids={e.get('targetRef',{}).get('uid') for v in s['items'] for e in v.get('endpoints',[])
                     if e.get('conditions',{}).get('ready')}
                if ids==set(uids) and {p['metadata']['uid'] for p in pods if ready(p)}==set(uids):return
                time.sleep(.5)
            raise TimeoutError('Service routes do not match actual usable capacity')

        try:
            # Recreate avoids exceeding the four-GPU limit with rolling surge.
            changed=True
            k.patch('deployment','vllm',{'spec':{'replicas':4,'strategy':{'type':'Recreate','rollingUpdate':None},'template':trial}})
            until=time.monotonic()+2400
            while time.monotonic()<until:
                pods=live_pods();study.control.remember_claims()
                candidates=[p for p in pods if p['metadata'].get('labels',{}).get(OWNER_LABEL)==OWNER]
                for p in candidates:
                    patch_gate(k,p,OWNER,True,time.time())
                if len(pods)==4 and len(candidates)==4 and all(ready(p) for p in candidates):break
                time.sleep(3)
            else:raise TimeoutError('Four-model prewarm startup deadline')
            nodes={c['status'].get('nodeName') for c in study.control.claims()
                   if c['metadata']['name'] in study.control.ownership['initial_claims']}
            pods.sort(key=lambda p:(p['spec']['nodeName'] not in nodes,p['metadata']['name']))
            baseline=[p['metadata']['uid'] for p in pods[:2]]
            withheld=[p['metadata']['uid'] for p in pods[2:]]
            identities=baseline+withheld
            wait_routes(identities)
            study.warmup()
            # Full-context direct inference proves each prewarmed engine independently.
            proofs={p['metadata']['uid']:asyncio.run(probe([dict(input_tokens=16384,output_tokens=2)],
                    study.tokens,'http://'+p['status']['podIP']+':8000')) for p in pods}
            save(dest/'prewarm-proof.json',dict(pods=pods,inference=proofs,baseline=baseline,withheld=withheld))
            results=[]
            for seed,lag,baseline_name in frozen['eval_order']:
                study.idle();set_gates([]);wait_routes(identities);study.warmup()
                set_gates(withheld);wait_routes(baseline)
                config,_,_=design.run_config(base,seed,.025,threshold)
                folder=dest/'eval'/f'seed-{seed}'/f'lag-{lag}'/baseline_name
                driver=GateDriver(k,OWNER,baseline,withheld,lag)
                gateway=None
                with Observer(k,folder,interval_s=.5,capture_scaler=True,state_builder=driver) as observer:
                    save(folder/'config.json',config)
                    log=(folder/'gateway.log').open('w')
                    try:
                        gateway=subprocess.Popen([sys.executable,'-m','crossscale.cli','gateway','--config',str(folder/'config.json'),
                            '--baseline',baseline_name,'--state',str(folder/'state.json'),'--url',SERVICE,'--host','0.0.0.0'],
                            cwd=root,stdout=log,stderr=log)
                        until=time.monotonic()+60
                        while True:
                            if gateway.poll() is not None:raise RuntimeError('Gateway startup failed')
                            try:
                                with urlopen('http://127.0.0.1:8080/metrics',timeout=2):break
                            except OSError:
                                if time.monotonic()>until:raise TimeoutError('Gateway startup')
                                time.sleep(.5)
                        if k.get('hpa')['items'] or k.get('scaledobject','vllm',missing_ok=True):
                            raise RuntimeError('Controlled schedule requires no autoscaler')
                        study.event('e5-measure-start',seed=seed,lag=lag,baseline=baseline_name)
                        summary=asyncio.run(run(config,baseline_name,folder/'run','http://127.0.0.1:8080',MODEL,
                                                root/'tokens.json',trace=traces[seed],on_start=driver.on_start))
                        until=summary['start_unix_s']+config['duration_s']+config['drain_s']
                        while time.time()<until:
                            if observer.error:raise RuntimeError(observer.error)
                            time.sleep(min(2,until-time.time()))
                        study.idle()
                        collect(PROMETHEUS,summary['start_unix_s'],time.time(),5,folder/'telemetry')
                    finally:
                        if gateway is not None:
                            gateway.terminate()
                            try:gateway.wait(timeout=15)
                            except subprocess.TimeoutExpired:gateway.kill();gateway.wait()
                        log.close()
                if driver.observed_release is None:raise RuntimeError('No observed controlled release')
                rows=[json.loads(x) for x in (folder/'run/requests.jsonl').read_text().splitlines()]
                valid=max((r.get('dispatch_lag_s',0) for r in rows),default=0)<=.05
                record=dict(seed=seed,lag_s=lag,baseline=baseline_name,dispatch_valid=valid,summary=summary,
                            nominal_release_unix_s=driver.start+60+lag,observed_release_unix_s=driver.observed_release)
                save(folder/'complete.json',record);results.append(record);save(dest/'progress.json',results)
                if not valid:raise RuntimeError('Dispatch validity exceeded')
            save(dest/'complete.json',dict(results=results,completed_unix_s=time.time()))
        except BaseException as exc:
            save(dest/'error.json',dict(error=repr(exc),unix_s=time.time()));raise
        finally:
            if changed:
                # Restore exact original template, removing keys added by merge patch.
                for p in live_pods():
                    if p['metadata'].get('labels',{}).get(OWNER_LABEL)==OWNER:
                        patch_gate(k,p,OWNER,True,time.time())
                study.fixed(1);study.control.cleanup_empty()
                restore=copy.deepcopy(original)
                restore['metadata']['labels'][OWNER_LABEL]=None
                restore['spec']['readinessGates']=original['spec'].get('readinessGates')
                k.patch('deployment','vllm',{'spec':{'replicas':1,'template':restore,'strategy':before['spec']['strategy']}})
                study.control.wait_ready(1);study.warmup()
                save(dest/'restored.json',dict(unix_s=time.time(),deployment=k.get('deployment','vllm')))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('/tmp/experiments'))
    p.add_argument('--plan',type=Path,required=True);a=p.parse_args();execute(a.root,json.loads(a.plan.read_text()))

if __name__=='__main__':main()
