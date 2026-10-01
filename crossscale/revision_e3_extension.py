"""Frozen B2/B4 extension; preserves priority trio results and identical traces."""
import argparse
import json
import random
from pathlib import Path
from . import revision_e3 as priority

DEST = 'revision-20260912/e3-b2-b4'

def plan(base, capacity):
    frozen = priority.plan(base, capacity)
    frozen.update(phase='e3-b2-b4', baselines=['B2', 'B4'], order_seed=20261001,
                  limitation='Separate extension after priority results; same seeds/traces, B4 fixed at two GPUs.',
                  matched_scale='B2 actual KEDA; B4 fixed two replicas with no autoscaler')
    frozen['eval_order'] = [[seed, baseline] for seed in frozen['eval_seeds'] for baseline in ('B2','B4')]
    random.Random(frozen['order_seed']).shuffle(frozen['eval_order'])
    return frozen

def execute(root, frozen):
    import fcntl
    from .episodes import save
    root = Path(root)
    with (root/'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = root/priority.DEST
        if (source/'error.json').exists() or not (source/'restored.json').exists():
            raise RuntimeError('Priority comparison must complete and restore')
        records = json.loads((source/'complete.json').read_text())['results']
        expected = {(s,b) for s in frozen['eval_seeds'] for b in priority.BASELINES}
        if len(records)!=15 or {(r['seed'],r['baseline']) for r in records}!=expected:
            raise RuntimeError('Incomplete priority comparison')
        base = json.loads((root/'configs/revision-20260930.json').read_text())
        capacity = priority.require_qualified_two_gpu_capacity(root)
        if frozen != plan(base, capacity):
            raise ValueError('Extension plan mismatch')
        threshold = priority.require_completed_e2(root)
        priority.require_admission_calibration(root)
        dest = root/DEST
        dest.mkdir(exist_ok=False)
        save(dest/'frozen-plan.json', frozen)
        priority._run_suite(root, dest, frozen, threshold)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/tmp/experiments'))
    parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args()
    execute(args.root,json.loads(args.plan.read_text()))

if __name__=='__main__':
    main()
