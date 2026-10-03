"""Continue only unattempted E7 cells after the preserved Oracle CLI rejection."""
import argparse
import copy
import json
import sys
from pathlib import Path
from . import revision_e7 as original

DEST='revision-20260912/e7-controlled-continuation-20261003'
OWNER='e7-continuation-20261003'
PLAN=Path('configs/revision-20261003-e7-continuation-plan.json')


def variant_map():
    names=original.variant_map()
    # Same scheduled-release policy as E6: B6 consumes externally supplied ETA.
    # Do not relax the CLI prohibition on simulation-only oracle-eta.
    names['Oracle']=('B6','oracle')
    return names


def plan(base, source=None):
    p=copy.deepcopy(original.plan(base,source))
    if p['eval_order'][:2] != [[872,'B3'],[874,'Oracle']]:
        raise ValueError('Unexpected preserved predecessor order')
    p.update(phase='e7-controlled-continuation-20261003',
        eval_order=p['eval_order'][2:],
        preserved_completed=[[872,'B3']], preserved_failed=[[874,'Oracle']],
        continuation='23 unattempted cells only; do not repeat completed or failed cells',
        gateway_oracle='B6 policy with externally supplied scheduled-release ETA; Oracle remains variant label')
    p['limitations'].append('Oracle seed 874 failed before measurement at CLI startup and is not rerun. Oracle comparisons have at most four complete pairs; report attrition.')
    return p


def require_predecessor(root):
    d=Path(root)/original.DEST
    if not (d/'restored.json').exists() or (d/'complete.json').exists():
        raise RuntimeError('Expected failed original E7 with completed restoration')
    e=json.loads((d/'error.json').read_text())
    if e['error'] != "RuntimeError('Gateway startup failed')":
        raise RuntimeError('Different failure requires diagnosis')
    folders={str(p.relative_to(d/'eval')) for p in (d/'eval').glob('*/*') if p.is_dir()}
    if folders != {'seed-872/B3','seed-874/Oracle'}:
        raise RuntimeError('Unexpected original attempts')
    r=json.loads((d/'eval/seed-872/B3/complete.json').read_text())
    if (r['seed'],r['variant'],r['dispatch_valid']) != (872,'B3',True):
        raise RuntimeError('Original first cell not valid')
    bad=d/'eval/seed-874/Oracle'
    if (bad/'run').exists() or (bad/'complete.json').exists():
        raise RuntimeError('Failed Oracle unexpectedly contains measurement')
    if 'oracle ETA is simulation-only' not in (bad/'gateway.log').read_text():
        raise RuntimeError('Missing diagnosed CLI rejection')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('/tmp/experiments'))
    p.add_argument('--plan',type=Path,default=PLAN)
    p.add_argument('--freeze',action='store_true')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if a.freeze:
        base=json.loads(Path('configs/revision-20260930.json').read_text())
        with a.plan.open('x') as f: json.dump(plan(base),f,indent=2); f.write('\n')
    elif a.execute:
        original.execute(a.root,json.loads(a.plan.read_text()),continuation=sys.modules[__name__])
    else: p.error('Choose --freeze or --execute')

if __name__=='__main__': main()
