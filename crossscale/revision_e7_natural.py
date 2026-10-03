"""E7 natural slow-loop/tenant audit, run only after controlled E7 restoration."""
import argparse
import hashlib
import json
import random
from pathlib import Path
from . import revision_e3 as engine
from .revision_e5 import run_config, verify_frozen_trace
from .revision_e7 import DEST as CONTROLLED_DEST, VARIANTS

DEST = 'revision-20260912/e7-natural-ablations'
BASELINES = ('B3', 'B5', 'no-tenant', 'B6')
PLAN = Path('configs/revision-20261003-e7-natural-plan.json')
SOURCE_PLAN = Path('configs/revision-20261001-e5-plan.json')


def plan(base, source):
    if base['tenants']['B']['ttft_s'] != 3 or source['capacity_rps'] != .025:
        raise ValueError('Requires amended calibrated condition')
    seeds = source['eval_seeds']
    order = [[s,b] for s in seeds for b in BASELINES]
    random.Random(20261006).shuffle(order)
    return dict(phase='e7-natural-ablations', capacity_rps=.025,
        slo_revision='revision-20260930-b-ttft-3s',
        serving_condition='full-context-32768-seqs4-batch4096-eager-prefix-cache-off',
        eval_seeds=seeds, eval_order=order, order_seed=20261006,
        baselines=list(BASELINES), traces=source['traces'],
        duration_s=600, drain_s=180, burst_s=[60,360], policy_audit=True,
        scaling='Actual SLO-KEDA/HPA, min 2 max 4, scale-down disabled during each run; no manual scale-up',
        eta='Independent batch4096 cold-new-node E0 training P90; required, no 60s fallback',
        threshold='Frozen E2 threshold, no retuning',
        analysis=dict(primary='weighted SLO goodput over all offered requests',
            contrasts=['B6-B5','B6-no-tenant','B5-B3'],
            cohorts=['whole run','burst','observed natural provisioning gap'],
            secondary=['A goodput','P99 TTFT','actual delay/reject actions','GPU utilization','tokens/s'],
            bootstrap_samples=10000, bootstrap_seed=20261006, practical_effect=.05,
            resampling_unit='paired seed',
            audit='Replay policy decisions; pin ScaledObject/Deployment/HPA identities and observed desired/Ready transitions'),
        limitations=['Oracle exists only in the separately labeled controlled E7 subphase; no future natural readiness is known.',
            'Admission feedback may alter slow scaling, so this is not a causal isolation of tenant/ETA components.',
            'No scale-up observed and readiness censored are explicit outcomes, never manual scale-up replacements.',
            'E5 traces reused; sparse counts and nonempty-tenant seed selection limit inference.',
            'Some natural cold starts exceed the observation horizon.'])


def require_controlled(root, seeds):
    dest = Path(root)/CONTROLLED_DEST
    if not all((dest/n).exists() for n in ('complete.json','restored.json')):
        raise RuntimeError('Controlled E7 must complete and restore')
    rows = json.loads((dest/'complete.json').read_text())['results']
    expected = {(s,v[0]) for s in seeds for v in VARIANTS}
    if len(rows)!=len(expected) or {(r['seed'],r['variant']) for r in rows}!=expected or not all(r['dispatch_valid'] for r in rows):
        raise RuntimeError('Controlled E7 incomplete, duplicate, or invalid')


def execute(root, frozen):
    import fcntl
    from .episodes import save
    root = Path(root)
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        base = json.loads((root/'configs/revision-20260930.json').read_text())
        source = json.loads((root/SOURCE_PLAN).read_text())
        if frozen != plan(base, source): raise ValueError('Natural E7 plan mismatch')
        require_controlled(root, frozen['eval_seeds'])
        if engine.require_qualified_two_gpu_capacity(root)!=.025:
            raise RuntimeError('Mixed capacity mismatch')
        threshold = engine.require_completed_e2(root)
        engine.require_admission_calibration(root)
        eta = json.loads((root/'e0-prefill4096/cold-new-node/summary.json').read_text())['training_p90_s']
        if not 0 < eta < 2400: raise ValueError('Invalid independent E0 ETA')
        traces = {}
        for entry in frozen['traces']:
            seed = entry['seed']
            rows = json.loads((root/f'configs/revision-20261001-e5-traces/seed-{seed}.json').read_text())
            traces[seed] = verify_frozen_trace(rows,run_config(base,seed,.025,threshold)[1],entry['sha256'])
        dest = root/DEST
        dest.mkdir(exist_ok=False)
        save(dest/'frozen-plan.json',frozen)
        engine._run_suite(root,dest,frozen,threshold,config_factory=run_config,traces=traces)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('/tmp/experiments'))
    p.add_argument('--plan',type=Path,default=PLAN)
    p.add_argument('--freeze',action='store_true')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if a.freeze:
        frozen=plan(json.loads(Path('configs/revision-20260930.json').read_text()),json.loads(SOURCE_PLAN.read_text()))
        payload=(json.dumps(frozen,indent=2)+'\n').encode()
        with a.plan.open('xb') as f: f.write(payload)
        print(hashlib.sha256(payload).hexdigest())
    elif a.execute: execute(a.root,json.loads(a.plan.read_text()))
    else: p.error('Choose --freeze or --execute')

if __name__=='__main__': main()
