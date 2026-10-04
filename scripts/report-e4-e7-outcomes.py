"""Whole/burst request checkpoints; gap, utilization and scaler audits remain separate."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crossscale.core import summarize
from crossscale.revision_compare import paired_comparison
from crossscale.policy_audit import audit_decisions

root=Path('results/full-experiments-20260908/run/revision-20260912')
suites=[('e4-noisy-neighbor',[],[('B6','B5'),('B5','B3'),('B6','B3')]),
 ('e5-controlled-prewarmed-capacity',[],[('B6','B5'),('B5','B3'),('B6','B3')]),
 ('e6-eta-error',[],[('oracle','eta-0'),('eta-0','no-eta')]+[(v,'eta-0') for v in ['eta-m50','eta-m25','eta-p25','eta-p50']]),
 ('e7-controlled-ablations',['e7-controlled-continuation-20261003'],[('CrossScale','B5'),('CrossScale','no-tenant'),('B5','B3'),('Oracle','CrossScale')]),
 ('e7-natural-ablations',[],[('B6','B5'),('B6','no-tenant'),('B5','B3')])]
output=[]
for name,continuations,contrasts in suites:
    plan=json.loads((root/name/'frozen-plan.json').read_text())
    condition=hashlib.sha256((root/name/'frozen-plan.json').read_bytes()).hexdigest()
    runs=[]; records={}; keys=set()
    for source in [name]+continuations:
        assert (root/source/'restored.json').exists()
        for path in sorted((root/source/'eval').rglob('run/requests.jsonl')):
            folder=path.parent.parent
            complete=json.loads((folder/'complete.json').read_text())
            config=json.loads((path.parent/'config.json').read_text())
            seed=config['seed']; variant=folder.name
            lag=next((p for p in folder.parts if p.startswith('lag-')),'all')
            key=(seed,variant,lag); assert key not in keys;keys.add(key)
            rows=[json.loads(x) for x in path.read_text().splitlines()]
            assert len(rows)==len({r['id'] for r in rows})
            trace=sorted(({k:r[k] for k in ('id','tenant','offered_s','input_tokens','output_tokens')} for r in rows),key=lambda r:r['id'])
            trace_hash=hashlib.sha256(json.dumps(trace,sort_keys=True).encode()).hexdigest()
            cohorts={}
            for cohort in (['whole','burst','controlled-gap'] if 'observed_release_unix_s' in complete else ['whole','burst']):
                lo,hi=plan['burst_s']
                if cohort=='controlled-gap':
                    lo=plan['release_trigger_s']; hi=complete['observed_release_unix_s']-complete['summary']['start_unix_s']
                    assert hi>=lo
                selected=rows if cohort=='whole' else [r for r in rows if lo<=r['offered_s']<hi]
                summary=summarize(selected,config|{'duration_s':config['duration_s'] if cohort=='whole' else max(hi-lo,1e-9)})
                for tenant in summary['tenants'].values():tenant.pop('deferred',None)
                if cohort=='whole':assert abs(summary['weighted_slo_goodput']-complete['summary']['weighted_slo_goodput'])<1e-12
                cohorts[cohort]=summary
                for metric,value in [('weighted_slo_goodput',summary['weighted_slo_goodput']),('A_goodput',summary['tenants']['A']['goodput'])]:
                    records.setdefault((lag,cohort,metric),[]).append(dict(seed=seed,baseline=variant,condition_sha256=condition,trace_sha256=trace_hash,mode='live',dispatch_valid=complete['dispatch_valid'],censored=False,value=value))
            audit=None
            if (folder/'policy-decisions.jsonl').exists():
                decisions=[json.loads(x) for x in (folder/'policy-decisions.jsonl').read_text().splitlines()]
                audit=audit_decisions(config,decisions)
                ids={str(r['id']) for r in rows}; seen={d['request_id'] for d in decisions if d.get('request_id') is not None}
                audit['missing_offered_ids']=sorted(ids-seen);audit['unexpected_ids']=sorted(seen-ids)
                assert audit['replay_valid'] and not audit['unexpected_ids']
            runs.append(dict(seed=seed,variant=variant,lag=lag,source=str(folder.relative_to(root)),cohorts=cohorts,policy_audit=audit))
    expected=len(plan['eval_order'])-(1 if continuations else 0)
    assert len(runs)==expected
    comparisons=[]
    for (lag,cohort,metric),rr in records.items():
        for left,right in contrasts:
            comparison=paired_comparison(rr,left,right,plan['eval_seeds'],plan['analysis']['practical_effect'],bootstrap_seed=plan['analysis']['bootstrap_seed'])
            comparisons.append(dict(lag=lag,cohort=cohort,metric=metric,**comparison))
    output.append(dict(suite=name,runs=runs,comparisons=comparisons,limitations=[
        'Whole/burst and recorded controlled-release gap request outcomes; utilization and natural scaler audits remain separate.',
        'No positive admission overhead is interpreted as policy deferral. Missing policy audit remains unknown.',
        'Controlled E7 preserves seed 874 Oracle startup failure; four-pair Oracle contrast is descriptive without bootstrap.',
        'Same documented 3-second B TTFT amendment; controlled scheduled oracle is not perfect natural readiness.']))
(root/'e4-e7-request-outcomes.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
print([(s['suite'],len(s['runs'])) for s in output])
