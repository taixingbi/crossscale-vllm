"""Single-replica open-loop sweep. Caller fixes capacity before running."""
import copy
import json
from pathlib import Path
from .live import run


async def sweep(c, out, url, model, tokens, rates, seeds, duration, target):
    if duration <= 0 or not 0 < target <= 1 or any(r <= 0 for r in rates):
        raise ValueError("positive rates/duration and target in (0,1] required")
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    mix = c['phases'][0]['rates']
    total = sum(mix.values())
    if total <= 0:
        raise ValueError('profile mix must contain traffic')
    results = []
    for rate in sorted(set(rates)):
        for seed in seeds:
            cc = copy.deepcopy(c)
            cc.update(seed=seed, duration_s=duration, initial_replicas=1, max_replicas=1)
            cc['phases'] = [{'start_s': 0, 'rates': {t: rate*v/total for t,v in mix.items()}}]
            summary = await run(cc, 'B0', root/f'rps-{rate}-seed-{seed}', url, model, tokens)
            passed = all(v['goodput'] is not None and v['goodput'] >= target for v in summary['tenants'].values())
            results.append(dict(rps=rate, seed=seed, passed=passed, summary=summary))
    # Require every lower load to pass too; do not cherry-pick a noisy high point.
    sustainable = None
    for rate in sorted(set(rates)):
        if all(r['passed'] for r in results if r['rps'] == rate):
            sustainable = rate
        else:
            break
    report = dict(sustainable_rps=sustainable, target_per_tenant=target, results=results,
                  requirement='verify one Ready GPU, no autoscaler, warmed model before sweep',
                  limitation='highest passing tested point, not interpolated saturation; dispatch lag must be inspected')
    (root/'profile.json').write_text(json.dumps(report, indent=2))
    return report
