"""Publication-export figures from committed request and lifecycle checkpoints."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path('results/full-experiments-20260908/run/revision-20260912')
out=root/'figures';out.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
suites=json.loads((root/'e4-e7-request-outcomes.json').read_text())
e8=json.loads((root/'e8-request-outcomes.json').read_text())
selected=[]
for s in suites:
 for c in s['comparisons']:
  if c['cohort']!='whole':continue
  metric='A_goodput' if s['suite'].startswith('e4-') else 'weighted_slo_goodput'
  if c['metric']!=metric:continue
  if (c['left'],c['right']) not in [('B6','B5'),('CrossScale','B5'),('eta-0','no-eta')]:continue
  label=s['suite'].split('-')[0].upper()+(' '+c['lag'] if c['lag']!='all' else '')
  if s['suite'].startswith('e7-'):label+=' controlled' if 'controlled' in s['suite'] else ' natural'
  selected.append((label+(' (A goodput)' if metric=='A_goodput' else ''),c))
selected += [('E8',next(c for c in e8['comparisons'] if c['cohort']=='whole' and c['metric']=='weighted_slo_goodput' and (c['left'],c['right'])==('B6','B5')))]
fig,ax=plt.subplots(figsize=(8,6))
for i,(label,c) in enumerate(selected):
 mean=100*c['mean_difference'];lo,hi=[100*v for v in c['paired_bootstrap_95']]
 ax.plot([lo,hi],[i,i],color='black',linewidth=1.5);ax.plot(mean,i,'o',color='black',markersize=4)
ax.axvline(0,color='gray',linewidth=1);ax.axvline(5,color='gray',linestyle='--',linewidth=1)
ax.set_yticks(range(len(selected)),[a for a,_ in selected]);ax.invert_yaxis()
ax.set_xlabel('ETA-aware minus Ready-only goodput (percentage points)')
ax.set_title('Paired whole-run outcomes: no established +5-point benefit')
fig.text(.02,.015,'Five paired seeds per contrast; 95% seed-bootstrap intervals. E4 uses A goodput; others weighted goodput.\nSource: frozen live E4–E8, Oct 1–4, 2026. B TTFT amended to 3 s. Intervals are not multiplicity-adjusted.',fontsize=8)
fig.tight_layout(rect=(0,.07,1,1))
for ext in ['png','pdf']:fig.savefig(out/f'eta-benefit-checkpoints.{ext}',dpi=180)
plt.close(fig)
cost=json.loads((root/'e8-cost-scaling.json').read_text())
fig,axes=plt.subplots(1,5,figsize=(15,3.8),sharey=True)
markers={'B2':'o','B3':'s','B5':'^','B6':'D'}
for ax,seed in zip(axes,range(901,906)):
 for r in cost['runs']:
  if r['seed']!=seed:continue
  ax.scatter(r['estimated_compute_usd'],100*r['weighted_slo_goodput'],marker=markers[r['baseline']],facecolors='none',edgecolors='black',label=r['baseline'],s=45)
  ax.annotate(r['baseline'],(r['estimated_compute_usd'],100*r['weighted_slo_goodput']),xytext={'B2':(3,8),'B3':(3,-12),'B5':(3,8),'B6':(3,-12)}[r['baseline']],textcoords='offset points',fontsize=8)
 ax.set_xlim(2,4);ax.set_title(f'Seed {seed}');ax.set_xlabel('Allocation estimate (USD)');ax.margins(.2)
axes[0].set_ylabel('All-offered weighted SLO goodput (%)')
fig.suptitle('E8 observed cost–SLO points, matched by workload seed')
fig.text(.01,.01,'Source: recorded EC2 launch/state evidence, Oct 3–4, 2026; 1 h arrivals + 180 s drain. $1.006/g5.xlarge-hour public price.\nLaunch-based allocation includes idle/pending instances; not invoice cost. Startup/reset, storage, network, CPU and EKS excluded. No interpolated frontier.',fontsize=8)
fig.tight_layout(rect=(0,.12,1,.92))
for ext in ['png','pdf']:fig.savefig(out/f'e8-observed-cost-slo.{ext}',dpi=180)
print(out)
