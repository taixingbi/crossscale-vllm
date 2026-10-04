"""Recompute E8 request outcomes and policy audit; lifecycle cost is separate."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crossscale.core import summarize
from crossscale.policy_audit import audit_decisions
from crossscale.revision_compare import paired_comparison


def report(root):
    plan = json.loads((root/'frozen-plan.json').read_text())
    assert (root/'restored.json').exists()
    condition = hashlib.sha256((root/'frozen-plan.json').read_bytes()).hexdigest()
    runs, records = [], {}
    for seed, baseline in plan['eval_order']:
        folder = root/'eval'/f'seed-{seed}'/baseline
        complete = json.loads((folder/'complete.json').read_text())
        config = json.loads((folder/'run/config.json').read_text())
        rows = [json.loads(x) for x in (folder/'run/requests.jsonl').read_text().splitlines()]
        assert len({r['id'] for r in rows}) == len(rows)
        trace = sorted(({k:r[k] for k in ('id','tenant','offered_s','input_tokens','output_tokens')} for r in rows),key=lambda r:r['id'])
        trace_hash = hashlib.sha256(json.dumps(trace,sort_keys=True).encode()).hexdigest()
        audit_rows = [json.loads(x) for x in (folder/'policy-decisions.jsonl').read_text().splitlines()]
        audit = audit_decisions(config, audit_rows)
        offered_ids = {str(r['id']) for r in rows}
        audited_ids = {r['request_id'] for r in audit_rows if r.get('request_id') is not None}
        audit['missing_offered_ids'] = sorted(offered_ids-audited_ids)
        audit['unexpected_ids'] = sorted(audited_ids-offered_ids)
        audit['rows_without_id'] = sum(r.get('request_id') is None for r in audit_rows)
        assert audit['replay_valid'] and not audit['unexpected_ids']
        cohorts = {}
        for index in range(-1,6):
            name = 'whole' if index == -1 else f'phase-{index+1}'
            selected = rows if index == -1 else [r for r in rows if index*600 <= r['offered_s'] < (index+1)*600]
            summary = summarize(selected, config | {'duration_s':3600 if index == -1 else 600})
            # Tiny positive gateway overhead is not evidence of policy deferral.
            for tenant in summary['tenants'].values():
                tenant.pop('deferred', None)
            cohorts[name] = summary
            if index == -1:
                assert abs(summary['weighted_slo_goodput']-complete['summary']['weighted_slo_goodput']) < 1e-12
            for metric, value in [('weighted_slo_goodput',summary['weighted_slo_goodput']),('A_goodput',summary['tenants']['A']['goodput'])]:
                records.setdefault((name,metric),[]).append(dict(seed=seed,baseline=baseline,condition_sha256=condition,trace_sha256=trace_hash,mode='live',dispatch_valid=complete['dispatch_valid'],censored=False,value=value))
        runs.append(dict(seed=seed,baseline=baseline,dispatch_valid=complete['dispatch_valid'],cohorts=cohorts,policy_audit=audit))
    comparisons = []
    for (cohort,metric), rr in records.items():
        for contrast in plan['analysis']['contrasts']:
            left,right = contrast.split('-')
            comparison = paired_comparison(rr,left,right,plan['eval_seeds'],plan['analysis']['practical_effect'],bootstrap_seed=plan['analysis']['bootstrap_seed'],resamples=plan['analysis']['bootstrap_samples'])
            comparisons.append(dict(cohort=cohort,metric=metric,**comparison))
    return dict(plan_sha256=condition,runs=runs,comparisons=comparisons,limitations=[
        'Request outcomes only; EC2 lifecycle cost, scaler audit, and frontier remain separate work.',
        'Per-phase missing tenants leave weighted goodput undefined; incomplete comparisons are descriptive.',
        'Latency quantiles cover completed requests only; rejects remain in offered-goodput denominators.',
        'Decision replay and fixed-state branch differences do not establish causal trajectories.',
        'B TTFT uses documented post-hoc 3-second amendment; do not pool original SLO results.'])


if __name__ == '__main__':
    root=Path('results/full-experiments-20260908/run/revision-20260912/e8-long-trace')
    output=report(root)
    destination=root.parent/'e8-request-outcomes.json'
    destination.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print(destination)
    for row in output['comparisons']:
        if row['cohort']=='whole' and row['metric']=='weighted_slo_goodput':
            print(row['left'],row['right'],row['mean_difference'],row['paired_bootstrap_95'])
