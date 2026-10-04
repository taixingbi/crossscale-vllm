"""Pinned-identity audit and first observed 2-to-4 provisioning gap."""
from collections import Counter
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crossscale.revision_scaler import audit_scaler_snapshot
from crossscale.revision_gap import observed_gap, gap_cohort
from crossscale.kube import ready
from crossscale.core import summarize
root=Path('results/full-experiments-20260908/run/revision-20260912')
suites=['e2-b2-b3-continuation-20260930','e3-b3-b5-b6','e3-b2-b4','e4-noisy-neighbor','e7-natural-ablations','e8-long-trace']
results=[]
for suite in suites:
 for pinned in sorted((root/suite).rglob('scaler-before.json')):
  folder=pinned.parent
  if not (folder/'run/requests.jsonl').exists():continue
  setup=json.loads(pinned.read_text()); scaler=setup.get('scaledobject')
  if not scaler:continue
  expected_hpas={h['metadata']['uid'] for h in setup['hpa']['items'] if any(o.get('uid')==scaler['metadata']['uid'] for o in h['metadata'].get('ownerReferences',[]))}
  samples=[]; statuses=Counter(); reasons=Counter(); events={}; hpas=set(); changed_hpa=0
  with gzip.open(folder/'observations.jsonl.gz','rt') as stream:
   for line in stream:
    row=json.loads(line)
    samples.append(dict(observed_unix_s=row['observed_unix_s'],desired=row['deployment']['spec']['replicas'],ready=sum(ready(p) for p in row['pods'] if not p['metadata'].get('deletionTimestamp'))))
    audit=audit_scaler_snapshot(row,deployment_uid=setup['deployment_uid'],scaledobject_uid=scaler['metadata']['uid'])
    statuses[audit['status']]+=1; reasons.update(audit['reasons'])
    if audit['hpa_uid']:
     hpas.add(audit['hpa_uid']);changed_hpa+=audit['hpa_uid'] not in expected_hpas
    for event in audit['rescale_events']:events[event['metadata']['uid']]=event
  gap=observed_gap(samples)
  complete=json.loads((folder/'complete.json').read_text()); config=json.loads((folder/'run/config.json').read_text())
  rows=[json.loads(x) for x in (folder/'run/requests.jsonl').read_text().splitlines()]
  selected=gap_cohort(rows,complete['summary']['start_unix_s'],gap)
  summary=summarize(selected,config)
  # Tokens/s uses a different interval; omit rather than reuse whole-run denominator.
  summary.pop('completed_tokens_s');summary.pop('tokens_rate_denominator')
  for t in summary['tenants'].values():t.pop('deferred',None)
  result=dict(source=str(folder.relative_to(root)),samples=len(samples),audit_statuses=dict(statuses),unverified_reasons=dict(reasons),setup_hpa_uids=sorted(expected_hpas),observed_hpa_uids=sorted(hpas),samples_with_unpinned_hpa=changed_hpa,unique_rescale_events=list(events.values()),gap=gap,gap_summary=summary)
  results.append(result);print(result['source'],statuses,gap['status'],flush=True)
output=dict(runs=results,limitations=['Sequential API reads and identity linkage are not proof of causal HPA attribution.','First observed scale decision to four Ready replicas; censored intervals retained. Later E8 bursts and reversal counts are separate.','No-scale runs have no gap cohort; absent tenant goodput is undefined.','Fixed B4 has no autoscaler and is excluded from this identity audit.'])
(root/'natural-scaler-audit.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
