"""Frozen one-hour mixed trace with real HPA scale-down and EC2 observations."""
import argparse
import copy
import hashlib
import json
import random
import time
from pathlib import Path
from . import revision_e3 as engine
from .core import workload
from .revision_e2 import offered_rates
from .revision_e5 import verify_frozen_trace
from .study import Study
from .kube import ready, stamp

DEST='revision-20260912/e8-long-trace'
PLAN=Path('configs/revision-20261003-e8-plan.json')
TRACE_DIR=Path('configs/revision-20261003-e8-traces')
SEEDS=(901,902,903,904,905)
BASELINES=('B2','B3','B5','B6')
DOWN=dict(stabilizationWindowSeconds=60,selectPolicy='Max',policies=[dict(type='Pods',value=1,periodSeconds=60)])


def run_config(base, seed, capacity, threshold):
    c,_,_=engine.e3_config(base,seed,capacity,threshold)
    low=offered_rates(capacity,.65); high=offered_rates(capacity,1.65)
    rag=dict(low);rag['C']*=4
    c.update(duration_s=3600,drain_s=180,phases=[dict(start_s=t,rates=r) for t,r in
        zip((0,600,1200,1800,2400,3000),(low,high,low,rag,high,low))])
    rows=workload(c)
    return c,rows,{t:sum(r['tenant']==t for r in rows) for t in c['tenants']}


def plan(base):
    if base['tenants']['B']['ttft_s']!=3: raise ValueError('Requires amended condition')
    entries=[]
    for seed in SEEDS:
        _,rows,counts=run_config(base,seed,.025,.8)
        if not all(counts.values()): raise ValueError('Missing tenant in prespecified seed')
        entries.append(dict(seed=seed,counts=counts,sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()))
    order=[[s,b] for s in SEEDS for b in BASELINES];random.Random(20261007).shuffle(order)
    return dict(phase='e8-long-trace',capacity_rps=.025,eval_seeds=list(SEEDS),baselines=list(BASELINES),
        eval_order=order,order_seed=20261007,traces=entries,duration_s=3600,drain_s=180,
        burst_s=[600,1200],all_bursts_s=[[600,1200],[2400,3000]],policy_audit=True,
        phases=['low','burst','recover','RAG-heavy (C fourfold)','burst','low'],phase_seconds=600,
        slo_revision='revision-20260930-b-ttft-3s',
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        scaler=dict(min=2,max=4,threshold='Frozen E2 threshold; B2 queue target 5',scale_down=DOWN),
        ec2_observation_interval_s=15,
        analysis=dict(primary='all-offered weighted SLO goodput and EC2 allocated GPU-hours',
            secondary=['cost per SLO-success','scale-outs','scale-downs and direction reversals','A goodput','P99 TTFT','actual delay/reject actions','tokens/s'],
            contrasts=['B6-B5','B5-B3','B6-B3','B3-B2'],cohorts=['whole run','each six phase intervals'],
            bootstrap_samples=10000,bootstrap_seed=20261007,practical_effect=.05,resampling_unit='paired seed',
            frontier='Observed nondominated run-level cost/goodput points with paired uncertainty; no interpolated optimum'),
        cost_scope='Integrate actual EC2 state/lifecycle during arrival+drain; report startup/reset separately from measurement. Price-based compute estimate, not invoice attribution.',
        limitations=['NodePool automatic disruption remains disabled; HPA pod scale-down does not terminate idle EC2 nodes during a run. Count these allocated GPUs and do not claim node cost savings.',
            'Public Linux on-demand pricing and lifecycle bounds must be verified before cost reporting; discounts, EBS, network and EKS charges are separate.',
            'Observe scale-down rather than force it; missing metrics may prevent it.',
            'RAG-heavy raises C arrival frequency while preserving original length distributions.',
            'First burst summary from shared engine is not the full two-burst E8 analysis.',
            'SLO amendment, sparse per-phase counts, and admission/scaling feedback limit interpretation.'])


class LongStudy(Study):
    def install_scaler(self, baseline, threshold=1):
        super().install_scaler(baseline,threshold)
        obj=self.k.get('scaledobject','vllm')
        if obj['metadata'].get('labels',{}).get('crossscale-experiment')!='full-20260908':
            raise RuntimeError('Refuse unrelated scaler mutation')
        self.k.patch('scaledobject','vllm',{'spec':{'advanced':{'horizontalPodAutoscalerConfig':{
            'behavior':{'scaleDown':copy.deepcopy(DOWN)}}}}})


class LifecycleState:
    def __init__(self,study,eta):
        self.study,self.eta=study,eta
        self.next_poll=0;self.capture=None;self.seen=set()
    def __call__(self,obs):
        now=time.time()
        if now>=self.next_poll:
            self.study.control.remember_claims()
            ids={c.get('status',{}).get('providerID','').rsplit('/',1)[-1] for c in obs['nodeclaims']}
            self.seen.update(i for i in ids if i.startswith('i-'))
            if not self.seen: raise RuntimeError('No EC2 identities for cost evidence')
            response=self.study.control.ec2.describe_instances(InstanceIds=sorted(self.seen))
            instances=[]
            for reservation in response['Reservations']:
                for i in reservation['Instances']:
                    row={k:i.get(k) for k in ('InstanceId','InstanceType','LaunchTime','State','StateTransitionReason','Placement','InstanceLifecycle')}
                    row['LaunchTime']=row['LaunchTime'].isoformat() if row['LaunchTime'] else None
                    instances.append(row)
            if {i['InstanceId'] for i in instances}!=self.seen: raise RuntimeError('Incomplete EC2 response')
            self.capture=dict(read_started_unix_s=now,read_finished_unix_s=time.time(),instances=instances)
            self.next_poll=now+15
        obs['ec2_lifecycle']=self.capture
        pods=[p for p in obs['pods'] if not p['metadata'].get('deletionTimestamp')]
        return dict(observed_unix_s=obs['observed_unix_s'],ready=sum(ready(p) for p in pods),
            desired=obs['deployment']['spec']['replicas'],pending_eta_unix_s=[
                stamp(p['metadata']['creationTimestamp'])+self.eta for p in pods if not ready(p)])


def require_e7(root):
    d=Path(root)/'revision-20260912/e7-natural-ablations'
    if not all((d/n).exists() for n in ('complete.json','restored.json')): raise RuntimeError('E7 must complete and restore')
    rows=json.loads((d/'complete.json').read_text())['results']
    expected={(s,b) for s in (871,872,873,874,875) for b in ('B3','B5','no-tenant','B6')}
    if len(rows)!=20 or {(r['seed'],r['baseline']) for r in rows}!=expected or not all(r['dispatch_valid'] for r in rows):
        raise RuntimeError('Invalid E7 predecessor')


def execute(root,frozen):
    import fcntl
    from .episodes import save
    root=Path(root)
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base=json.loads((root/'configs/revision-20260930.json').read_text())
        # Recompute using portable frozen rows for hashes; generation is checked to 1ns below.
        declared=plan(base)
        for target,source in zip(declared['traces'],frozen['traces']): target['sha256']=source['sha256']
        if frozen!=declared: raise ValueError('E8 frozen plan mismatch')
        require_e7(root)
        if engine.require_qualified_two_gpu_capacity(root)!=.025: raise RuntimeError('Capacity mismatch')
        threshold=engine.require_completed_e2(root);engine.require_admission_calibration(root)
        eta=json.loads((root/'e0-prefill4096/cold-new-node/summary.json').read_text())['training_p90_s']
        if not 0<eta<2400: raise ValueError('Missing independent ETA')
        traces={}
        for entry in frozen['traces']:
            seed=entry['seed']; rows=json.loads((root/TRACE_DIR/f'seed-{seed}.json').read_text())
            traces[seed]=verify_frozen_trace(rows,run_config(base,seed,.025,threshold)[1],entry['sha256'])
        dest=root/DEST;dest.mkdir(exist_ok=False);save(dest/'frozen-plan.json',frozen)
        engine._run_suite(root,dest,frozen,threshold,config_factory=run_config,traces=traces,
            study_factory=LongStudy,state_factory=LifecycleState)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('/tmp/experiments'))
    p.add_argument('--freeze',action='store_true');p.add_argument('--execute',action='store_true');a=p.parse_args()
    if a.freeze:
        base=json.loads(Path('configs/revision-20260930.json').read_text());frozen=plan(base)
        TRACE_DIR.mkdir(exist_ok=False)
        for s in SEEDS: (TRACE_DIR/f'seed-{s}.json').write_text(json.dumps(run_config(base,s,.025,.8)[1],indent=2)+'\n')
        with PLAN.open('x') as f: json.dump(frozen,f,indent=2);f.write('\n')
    elif a.execute: execute(a.root,json.loads(PLAN.read_text()))
    else: p.error('Choose --freeze or --execute')
if __name__=='__main__': main()
