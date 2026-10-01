"""Reproducible paired checkpoint; never infer causal benefit from ordering."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crossscale.revision_compare import paired_comparison
from crossscale.revision_gap import observed_gap, gap_cohort
from crossscale.kube import ready

root = Path('results/full-experiments-20260908/run/revision-20260912/e3-b3-b5-b6')
plan = json.loads((root/'frozen-plan.json').read_text())
complete = json.loads((root/'complete.json').read_text())
assert (root/'restored.json').exists() and len(complete['results']) == 15
records, runs = [], []
condition = hashlib.sha256((root/'frozen-plan.json').read_bytes()).hexdigest()
for record in complete['results']:
    folder = root/'eval'/f"seed-{record['seed']}"/record['baseline']
    rows = [json.loads(line) for line in (folder/'run/requests.jsonl').read_text().splitlines()]
    trace = [{k:r[k] for k in ('id','tenant','offered_s','input_tokens','output_tokens')} for r in rows]
    trace.sort(key=lambda r:r['id'])
    samples = []
    with gzip.open(folder/'observations.jsonl.gz', 'rt') as stream:
        for line in stream:
            s=json.loads(line)
            samples.append(dict(observed_unix_s=s['observed_unix_s'],desired=s['deployment']['spec']['replicas'],
                                ready=sum(ready(p) for p in s['pods'] if not p['metadata'].get('deletionTimestamp'))))
    gap=observed_gap(samples)
    counts={t:sum(r['tenant']==t for r in rows) for t in ('A','B','C')}
    runs.append(dict(seed=record['seed'],baseline=record['baseline'],offered=len(rows),tenant_counts=counts,
                     weighted_slo_goodput=record['summary']['weighted_slo_goodput'],gap=gap,
                     gap_offered=len(gap_cohort(rows,record['summary']['start_unix_s'],gap))))
    records.append(dict(seed=record['seed'],baseline=record['baseline'],condition_sha256=condition,
                        trace_sha256=hashlib.sha256(json.dumps(trace,sort_keys=True).encode()).hexdigest(),
                        mode='live',dispatch_valid=record['dispatch_valid'],censored=False,
                        value=record['summary']['weighted_slo_goodput']))
comparisons=[paired_comparison(records,a,b,plan['eval_seeds'],plan['practical_effect'])
             for a,b in [('B6','B5'),('B5','B3'),('B6','B3')]]
out=dict(scope='Priority E3 whole-run weighted SLO goodput over all offered requests',
         slo_revision=plan['slo_revision'],runs=runs,comparisons=comparisons,
         limitations=['Five paired seeds; sparse tenant samples.',
                      'Whole-run censor flag refers to completion of the frozen request horizon, not target readiness.',
                      'Readiness censoring is retained separately in each gap record.',
                      'No causal ETA attribution from ordering; no matched-scale experiment included.',
                      'Negative priority checkpoint does not stop E3 B2/B4 or E4–E8.'])
path=root.parent/'e3-priority-analysis.json';path.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(comparisons,indent=2))
print('Gap statuses:',{s:sum(r['gap']['status']==s for r in runs) for s in {r['gap']['status'] for r in runs}})
