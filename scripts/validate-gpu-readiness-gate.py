import json, subprocess, time, pathlib, sys
sys.path.insert(0,'/Users/h/Desktop/paper/paper11-Crossscale-Vllm/crossscale-vllm')
from crossscale.readiness_gate import CONDITION, OWNER_LABEL, condition_patch
ROOT=pathlib.Path('/Users/h/Desktop/paper/paper11-Crossscale-Vllm/crossscale-vllm/results/readiness-gpu-validation-20261001')
K=['kubectl','--kubeconfig','/tmp/crossscale-continuation-kubeconfig','-n','crossscale']
NAME='crossscale-gate-gpu-validation-20261001'
OWNER='gpu-validation-20261001'
def k(*args,data=None):
    p=subprocess.run(K+list(args),input=None if data is None else json.dumps(data),text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr)
    return p.stdout
def get(kind): return json.loads(k('get',kind,NAME,'-o','json'))
def save(name,x): (ROOT/name).write_text(json.dumps(x,indent=2)+'\n')
def event(x):
    with (ROOT/'events.jsonl').open('a') as f:f.write(json.dumps(dict(unix_s=time.time(),**x))+'\n')
def probe():
    code='import urllib.request,json; req=urllib.request.Request("http://'+NAME+':8080/v1/completions", data=json.dumps({"model":"meta-llama/Llama-3.1-8B-Instruct","prompt":"Reply hello","max_tokens":4,"temperature":0}).encode(), headers={"Content-Type":"application/json"}); print(urllib.request.urlopen(req,timeout=5).read().decode())'
    p=subprocess.run(K+['exec','crossscale-experiment-runner','--','python3','-c',code],capture_output=True,text=True)
    return dict(ok=p.returncode==0,output=p.stdout[-1000:],error=p.stderr[-1000:],unix_s=time.time())
def gate(released):
    code = ('import time; from crossscale.cluster import Cluster; '
            'from crossscale.readiness_gate import patch_gate; k=Cluster(); '
            'p=k.get("pods", '+repr(NAME)+'); '
            'patch_gate(k,p,'+repr(OWNER)+','+repr(released)+',time.time())')
    k('exec','crossscale-experiment-runner','--','sh','-c',
      'cd /tmp/experiments && python3 -c '+__import__('shlex').quote(code))
def endpoint_ready():
    x=json.loads(k('get','endpointslice','-l','kubernetes.io/service-name='+NAME,'-o','json'))
    event(dict(endpoint_slices=x))
    return any(e.get('conditions',{}).get('ready') for s in x['items'] for e in s.get('endpoints',[]))
def wait_endpoint(want,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if endpoint_ready()==want:return time.time()
        time.sleep(.5)
    raise TimeoutError('EndpointSlice readiness did not become '+str(want))
ROOT.mkdir(exist_ok=False)
created={}
lockproc=subprocess.Popen(K+['exec','-i','crossscale-experiment-runner','--','python3','-u','-c',
    'import fcntl,sys; f=open("/tmp/experiments/suite.lock","a"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print("locked",flush=True); sys.stdin.read()'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
if lockproc.stdout.readline().strip()!='locked':raise RuntimeError('Exclusive suite lock unavailable')
try:
    # Create, never apply or adopt an existing resource.
    deployment=json.loads(k('get','deployment','vllm','-o','json'))
    save('deployment-before.json',deployment)
    spec=deployment['spec']['template']['spec']
    spec['restartPolicy']='Never'
    spec['readinessGates']=[dict(conditionType=CONDITION)]
    args=spec['containers'][0]['args']
    args[args.index('--max-num-batched-tokens')+1]='4096'
    pod=dict(apiVersion='v1',kind='Pod',metadata=dict(name=NAME,labels={OWNER_LABEL:OWNER,'app':NAME}),spec=spec)
    svc=dict(apiVersion='v1',kind='Service',metadata=dict(name=NAME,labels={OWNER_LABEL:OWNER}),spec=dict(selector={'app':NAME},ports=[dict(port=8080,targetPort=8000)]))
    save('pod-manifest.json',pod);save('service-manifest.json',svc)
    for kind,obj in [('pod',pod),('service',svc)]:
        k('create','-f','-',data=obj);created[kind]=get(kind)['metadata']['uid']
    deadline=time.monotonic()+2400
    while time.monotonic()<deadline:
        p=get('pod')
        if any(c['type']=='ContainersReady' and c['status']=='True' for c in p.get('status',{}).get('conditions',[])):break
        time.sleep(2)
    else:raise TimeoutError('GPU model startup')
    results=[]
    for lag in [0,15,30,60,90,120]:
        gate(False); wait_endpoint(False)
        before=probe();event(dict(stage='blocked-probe',lag=lag,probe=before))
        if before['ok']:raise RuntimeError('Service reachable with closed gate')
        start=time.time(); target=start+lag
        while time.time()<target:time.sleep(min(.2,target-time.time()))
        requested=time.time();gate(True);observed=wait_endpoint(True)
        after=probe();event(dict(stage='released-probe',lag=lag,probe=after))
        if not after['ok']:raise RuntimeError('Service unreachable after release')
        result=dict(lag_s=lag,start_unix_s=start,target_unix_s=target,patch_requested_unix_s=requested,endpoint_ready_unix_s=observed,observed_lag_s=observed-start,late_s=observed-target,blocked_probe=before,released_probe=after)
        results.append(result);save('progress.json',results)
        if not 0 <= observed-target <= 5:raise RuntimeError('Readiness release exceeds predeclared 5s tolerance')
    save('complete.json',dict(results=results,scope='Single extra vLLM GPU pod readiness and inference-routing validation; not E5 measurement',completed_unix_s=time.time()))
except BaseException as e:
    save('error.json',dict(error=repr(e),unix_s=time.time()));raise
finally:
    k('exec','crossscale-experiment-runner','--','python3','-c','import sys; sys.path.insert(0,"/tmp/experiments"); from crossscale.study import Study; Study("/tmp/experiments").control.remember_claims()')
    for kind,uid in reversed(list(created.items())):
        obj=get(kind)
        if obj['metadata']['uid']!=uid or obj['metadata']['labels'].get(OWNER_LABEL)!=OWNER:raise RuntimeError('Cleanup ownership mismatch')
        k('delete',kind,NAME,'--wait=true','--timeout=60s')
    k('exec','crossscale-experiment-runner','--','python3','-c','import sys; sys.path.insert(0,"/tmp/experiments"); from crossscale.study import Study; Study("/tmp/experiments").control.cleanup_empty()')
    lockproc.communicate(timeout=30)
    save('cleaned.json',dict(resources=created,unix_s=time.time()))
    subprocess.run(['aws','s3','sync',str(ROOT),'s3://crossscale-experiment-results-646821141010-us-east-1/readiness-gpu-validation-20261001/','--region','us-east-1','--only-show-errors'],check=True)
