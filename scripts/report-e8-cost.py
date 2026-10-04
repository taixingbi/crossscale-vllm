"""E8 launch-based allocation estimate and sampled running-time bounds, not billing."""
import datetime
import sys
import json
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crossscale.revision_compare import paired_comparison

root=Path('results/full-experiments-20260908/run/revision-20260912')
source=json.loads((root/'e8-lifecycle-extract.json').read_text())
outcomes=json.loads((root/'e8-request-outcomes.json').read_text())
prices=json.loads((root/'e8-public-price.json').read_text())
products=[json.loads(p) for p in prices['PriceList']]
assert len(products)==1
product=products[0]
rates=[float(d['pricePerUnit']['USD']) for t in product['terms']['OnDemand'].values() for d in t['priceDimensions'].values() if d['unit']=='Hrs']
assert len(rates)==1
price=rates[0]
results=[]
for run in source['runs']:
    start,end=run['start_unix_s'],run['end_unix_s']
    reads=run['ec2_reads']; instances={}
    gaps=[b['read_started_unix_s']-a['read_finished_unix_s'] for a,b in zip(reads,reads[1:])]
    assert reads[0]['read_finished_unix_s']<=start and end-reads[-1]['read_finished_unix_s']<20
    for read in reads:
        for instance in read['instances']:
            assert instance['InstanceType']=='g5.xlarge' and instance.get('InstanceLifecycle') is None
            assert instance['State']['Name'] in ('pending','running')
            instances.setdefault(instance['InstanceId'],[]).append((read,instance))
    allocations=[]
    for iid,history in instances.items():
        launch=datetime.datetime.fromisoformat(history[0][1]['LaunchTime']).timestamp()
        assert all(i['LaunchTime']==history[0][1]['LaunchTime'] for _,i in history)
        running=[r for r,i in history if i['State']['Name']=='running']
        assert running
        pending=[r for r,i in history if i['State']['Name']=='pending']
        # Monotone pending->running is required; no unobserved stop/restart is assumed.
        assert not pending or pending[-1]['read_finished_unix_s']<=running[0]['read_started_unix_s']
        upper_start=max(start,launch,max((r['read_started_unix_s'] for r in pending),default=launch))
        lower_start=max(start,running[0]['read_finished_unix_s'])
        lower_end=min(end,running[-1]['read_started_unix_s'])
        allocations.append(dict(instance_id=iid,launch_unix_s=launch,
            allocated_gpu_hours=(end-max(start,launch))/3600,
            running_gpu_hours_lower=max(0,lower_end-lower_start)/3600,
            running_gpu_hours_upper=max(0,end-upper_start)/3600))
    outcome=next(r for r in outcomes['runs'] if (r['seed'],r['baseline'])==(run['seed'],run['baseline']))
    summary=outcome['cohorts']['whole']; good=sum(t['good'] for t in summary['tenants'].values())
    allocated=sum(i['allocated_gpu_hours'] for i in allocations)
    changes=run['desired_changes']; differences=[b['desired']-a['desired'] for a,b in zip(changes,changes[1:])]
    results.append(dict(seed=run['seed'],baseline=run['baseline'],instances=allocations,
        allocated_gpu_hours=allocated,estimated_compute_usd=allocated*price,
        running_gpu_hours_lower=sum(i['running_gpu_hours_lower'] for i in allocations),
        running_gpu_hours_upper=sum(i['running_gpu_hours_upper'] for i in allocations),
        good_requests=good,estimated_usd_per_slo_success=allocated*price/good if good else None,
        weighted_slo_goodput=summary['weighted_slo_goodput'],
        observed_scale_outs=sum(d>0 for d in differences),observed_scale_downs=sum(d<0 for d in differences),
        direction_reversals=sum(a*b<0 for a,b in zip(differences,differences[1:])),
        max_ec2_read_gap_s=max(gaps),sampling_assumption='No unobserved stop/restart between EC2 reads.'))
for r in results:
    # Compare identical seed/workload only; cross-seed points are not interchangeable.
    r['nondominated_within_seed']=not any(q['seed']==r['seed'] and q['allocated_gpu_hours']<=r['allocated_gpu_hours'] and q['weighted_slo_goodput']>=r['weighted_slo_goodput'] and (q['allocated_gpu_hours']<r['allocated_gpu_hours'] or q['weighted_slo_goodput']>r['weighted_slo_goodput']) for q in results)
output=dict(public_usd_per_instance_hour=price,price_sku=product['product']['sku'],runs=results,
    scope='3600 seconds arrivals plus full 180-second drain; launch-based allocation includes pending and idle instances.',
    limitations=['Estimate, not invoice or account billing attribution. Startup/reset and final cleanup outside the measurement window are excluded and require separate accounting.',
        'Running-time bounds are sampling brackets conditional on no unobserved stop/restart; launch-based allocation is not billed runtime.',
        'Public on-demand Linux shared-tenancy price; discounts, EBS, network, CPU, and EKS charges excluded.',
        'Automatic node disruption disabled; pod scale-down does not imply EC2 savings.',
        'Nondominance compares only equal-seed workloads; no interpolated optimum.'])
plan=json.loads((root/'e8-long-trace/frozen-plan.json').read_text())
comparisons=[]
for metric in ['allocated_gpu_hours','estimated_compute_usd','estimated_usd_per_slo_success']:
 records=[dict(seed=r['seed'],baseline=r['baseline'],condition_sha256=outcomes['plan_sha256'],trace_sha256=next(t['sha256'] for t in plan['traces'] if t['seed']==r['seed']),mode='live',dispatch_valid=True,censored=False,value=r[metric]) for r in results]
 for left,right in [('B6','B5'),('B5','B3'),('B6','B3'),('B3','B2')]:
  comparison=paired_comparison(records,left,right,plan['eval_seeds'],0,bootstrap_seed=20261007)
  comparison['practical_benefit_supported']=None
  comparison['practical_effect']=None
  comparisons.append(dict(metric=metric,interpretation='Negative difference means lower estimated allocation/cost; no prespecified practical cost threshold',**comparison))
output['paired_cost_comparisons']=comparisons
(root/'e8-cost-scaling.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
for b in ['B2','B3','B5','B6']:
    rr=[r for r in results if r['baseline']==b]
    print(b,'mean allocated GPUh',sum(r['allocated_gpu_hours'] for r in rr)/5,'scaleouts',sum(r['observed_scale_outs'] for r in rr),'scaledowns',sum(r['observed_scale_downs'] for r in rr))
