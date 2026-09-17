"""Rebuild isolated E1 aggregate evidence without altering qualification."""
import json
import random
from pathlib import Path

root = Path('results/full-experiments-20260908/run/revision-20260912/e1-isolated')
complete = json.loads((root/'complete.json').read_text())
rows = []
for tenant in 'ABC':
    rates = sorted({r['rps'] for r in complete['results'] if r['tenant'] == tenant})
    for rate in rates:
        runs = [r for r in complete['results'] if r['tenant'] == tenant and r['rps'] == rate]
        values = [r['summary']['tenants'][tenant]['goodput'] for r in runs]
        rng = random.Random(20260917)
        means = sorted(sum(rng.choices(values, k=len(values)))/len(values) for _ in range(10000))
        rows.append(dict(tenant=tenant, rps=rate, repetitions=len(runs),
                         passed=sum(r['passed'] for r in runs),
                         samples=[r['summary']['tenants'][tenant]['offered'] for r in runs],
                         goodput_by_run=values, mean_goodput=sum(values)/len(values),
                         min_goodput=min(values), max_goodput=max(values),
                         mean_bootstrap_95=[means[249], means[9749]],
                         p99_ttft_s=[r['summary']['tenants'][tenant]['p99_ttft_s'] for r in runs]))
report = dict(capacities=complete['capacities'], rows=rows,
              method='Equal-weight mean across five fixed seeds; percentile bootstrap 10000 resamples, random seed 20260917. Intervals describe run means, not capacity uncertainty or a guarantee. Qualification still requires every repetition and every lower tested rate.',
              limitations=['Isolated tenant capacities cannot be summed into mixed capacity.',
                           'Only tested grid points qualify; boundary is not precisely estimated.',
                           'Five repetitions give limited uncertainty resolution; degenerate intervals do not prove certainty.',
                           'GPU utilization unavailable; missing series are not zero.'],
              source='revision-20260912/e1-isolated/complete.json',
              interval_utc='2026-09-13 to 2026-09-16')
(root/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
