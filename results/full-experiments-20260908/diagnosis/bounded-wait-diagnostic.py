"""Repeat one dispatch-invalid workload in a separate process; retain original."""
import fcntl,json,subprocess,sys,time
from pathlib import Path
from crossscale.study import Study,SERVICE,MODEL,PROMETHEUS
from crossscale.episodes import Observer,save
from crossscale.telemetry import collect
root=Path('/tmp/experiments')
with (root/'suite.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    study=Study(root)
    dest=root/'diagnosis-bounded-wait-load'
    if dest.exists(): raise RuntimeError('Diagnostic already exists; do not replace evidence')
    study.fixed(1)
    study.warmup()
    source=root/'profile-one-low/rps-0.025-seed-18/run/config.json'
    with Observer(study.k,dest):
        save(dest/'config.json',json.loads(source.read_text()))
        study.event('bounded-wait-diagnostic-start',source=str(source),output=str(dest))
        with (dest/'client.log').open('w') as log:
            subprocess.run([sys.executable,'-m','crossscale.cli','live','--config',str(dest/'config.json'),'--baseline','B0','--out',str(dest/'run'),'--url',SERVICE,'--model',MODEL,'--tokens',str(root/'tokens.json')],stdout=log,stderr=log,check=True)
        study.idle()
        summary=json.loads((dest/'run/summary.json').read_text())
        collect(PROMETHEUS,summary['start_unix_s'],time.time(),5,dest/'telemetry')
    rows=[json.loads(l) for l in (dest/'run/requests.jsonl').read_text().splitlines()]
    result={'completed_unix_s':time.time(),'source':str(source),'max_dispatch_lag_s':max(r['dispatch_lag_s'] for r in rows),'tenant_goodput':{t:v['goodput'] for t,v in summary['tenants'].items()},'purpose':'Diagnostic repeat only; does not replace original or select capacity'}
    save(dest/'complete.json',result)
    study.event('bounded-wait-diagnostic-complete',**result)
