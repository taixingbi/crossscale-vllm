"""Lossless relevant EC2 reads and replica changes from frozen E8 observations."""
import gzip
import json
from pathlib import Path

root=Path('results/full-experiments-20260908/run/revision-20260912/e8-long-trace')
runs=[]
for path in sorted(root.glob('eval/*/*/observations.jsonl.gz')):
    complete=json.loads((path.parent/'complete.json').read_text())
    start=complete['summary']['start_unix_s']
    reads={}; changes=[]; first=None; last=None
    with gzip.open(path,'rt') as stream:
        for line in stream:
            row=json.loads(line); at=row['observed_unix_s']
            first=at if first is None else first; last=at
            lifecycle=row.get('ec2_lifecycle')
            if lifecycle:
                key=lifecycle['read_finished_unix_s']
                if key in reads:
                    assert reads[key]==lifecycle
                reads[key]=lifecycle
            if start<=at<=start+3780:
                replicas=row['deployment']['spec']['replicas']
                if not changes or changes[-1]['desired']!=replicas:
                    changes.append(dict(observed_unix_s=at,desired=replicas))
    runs.append(dict(seed=complete['seed'],baseline=complete['baseline'],start_unix_s=start,
                     end_unix_s=start+3780,observation_first_unix_s=first,observation_last_unix_s=last,
                     ec2_reads=[reads[k] for k in sorted(reads)],desired_changes=changes))
assert len(runs)==20
output=root.parent/'e8-lifecycle-extract.json'
output.write_text(json.dumps(dict(scope='Arrival plus full 180-second drain; extraction only, not billed cost',runs=runs),indent=2)+'\n')
print(output)
