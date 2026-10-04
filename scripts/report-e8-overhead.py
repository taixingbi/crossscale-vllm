"""Separate E8 observed controller-window allocation from measured load windows."""
import datetime,json
from pathlib import Path
root=Path('results/full-experiments-20260908/run/revision-20260912')
logs=[json.loads(s) for s in (root/'e8-controller-complete.jsonl').read_text().splitlines() if s.startswith('{')]
reads=json.loads((root/'e8-lifecycle-extract.json').read_text())['runs']
cost=json.loads((root/'e8-cost-scaling.json').read_text())
start=min(r['unix_s'] for r in logs); end=json.loads((root/'e8-long-trace/restored.json').read_text())['unix_s']
launches={}
for run in reads:
 for read in run['ec2_reads']:
  for i in read['instances']:
   launch=datetime.datetime.fromisoformat(i['LaunchTime']).timestamp()
   assert i['InstanceId'] not in launches or launches[i['InstanceId']]==launch
   launches[i['InstanceId']]=launch
instances=[]
for iid,launch in launches.items():
 lower_end=upper_end=end
 if iid!='i-063f58e1698afc010':
  events=[r for r in logs if r.get('instance')==iid]
  terminal=[r['unix_s'] for r in events if r['event']=='instance-terminated' or r.get('states')==['terminated']]
  assert terminal
  upper_end=min(terminal)
  prior=[r['unix_s'] for r in events if r['unix_s']<upper_end and r.get('states') and r['states']!=['terminated']]
  assert prior
  lower_end=max(prior)
 lo=max(0,lower_end-max(start,launch))/3600;hi=max(0,upper_end-max(start,launch))/3600
 measured=sum(i['allocated_gpu_hours'] for r in cost['runs'] for i in r['instances'] if i['instance_id']==iid)
 assert lo>=measured-1e-6
 instances.append(dict(instance_id=iid,controller_window_allocated_gpuh_lower=lo,controller_window_allocated_gpuh_upper=hi,measurement_allocated_gpuh=measured,nonmeasurement_allocated_gpuh_lower=lo-measured,nonmeasurement_allocated_gpuh_upper=hi-measured))
output=dict(observed_controller_start_unix_s=start,restored_unix_s=end,instances=instances,
 nonmeasurement_allocated_gpuh_lower=sum(i['nonmeasurement_allocated_gpuh_lower'] for i in instances),
 nonmeasurement_allocated_gpuh_upper=sum(i['nonmeasurement_allocated_gpuh_upper'] for i in instances),
 limitations=['Observed window starts at first controller log, not process launch; earlier unlogged setup excluded.',
 'Allocation includes pending, idle and shutting-down intervals. Not billed runtime or invoice attribution.',
 'Termination bracket uses last observed nonterminated state and first observed terminated state.',
 'Original GPU remains allocated after restoration; later idle time is excluded.',
 'Nonmeasurement combines startup, reset, inter-run cleanup and restoration; not attributed to a baseline.'])
(root/'e8-overhead-allocation.json').write_text(json.dumps(output,indent=2)+'\n')
print(output['nonmeasurement_allocated_gpuh_lower'],output['nonmeasurement_allocated_gpuh_upper'])
