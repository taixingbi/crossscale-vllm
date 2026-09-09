"""Read-only Kubernetes observer. Never requests scale-out or deletes nodes."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time


def stamp(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def get(context, namespace, resource, selector=None):
    cmd = ["kubectl", "--context", context, "-n", namespace, "get", resource, "-o", "json", "--request-timeout=10s"]
    if selector:
        cmd.extend(["-l", selector])
    return json.loads(subprocess.check_output(cmd, text=True))


def ready(obj):
    return any(x["type"] == "Ready" and x["status"] == "True" for x in obj.get("status", {}).get("conditions", [])) and not obj["metadata"].get("deletionTimestamp")


def observe(context, namespace, deployment, selector, out, duration, interval, eta_s):
    p = Path(out)
    p.mkdir(parents=True, exist_ok=False)
    end = time.monotonic()+duration
    with (p / "observations.jsonl").open("w") as f:
        while time.monotonic() < end:
            dep = get(context, namespace, "deployment/"+deployment)
            pods = get(context, namespace, "pods", selector)["items"]
            nodes = get(context, namespace, "nodes")["items"]
            claims = get(context, namespace, "nodeclaims")["items"]
            observed = time.time()
            # Raw objects preserve UIDs, owner references, node association and conditions.
            f.write(json.dumps(dict(observed_unix_s=observed, deployment=dep, pods=pods, nodes=nodes, nodeclaims=claims))+"\n")
            f.flush()
            live = [x for x in pods if not x["metadata"].get("deletionTimestamp")]
            pending = [x for x in live if not ready(x)]
            state = dict(observed_unix_s=observed, ready=sum(bool(ready(x)) for x in live), desired=dep["spec"]["replicas"],
                         pending_eta_unix_s=[stamp(x["metadata"]["creationTimestamp"])+eta_s for x in pending])
            tmp = p / "state.tmp"
            tmp.write_text(json.dumps(state))
            tmp.replace(p / "state.json")
            time.sleep(interval)


def extract(path):
    """Report each scale-up episode; incomplete episodes remain censored."""
    episodes, previous, open_episode = [], None, None
    pod_stages = {}
    import gzip
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as stream:
        for line in stream:
            obs = json.loads(line)
            desired = obs["deployment"]["spec"]["replicas"]
            if previous is not None and desired > previous:
                if open_episode:
                    open_episode["censor_reason"] = "superseded_by_scale_up"
                open_episode = dict(scale_observed_unix_s=obs["observed_unix_s"], target=desired, from_replicas=previous, capacity_ready_unix_s=None, gap_s=None)
                episodes.append(open_episode)
            n = sum(bool(ready(x)) for x in obs["pods"])
            if open_episode and n >= open_episode["target"]:
                open_episode["capacity_ready_unix_s"] = obs["observed_unix_s"]
                open_episode["gap_s"] = obs["observed_unix_s"]-open_episode["scale_observed_unix_s"]
                open_episode = None
            elif open_episode and desired < open_episode["target"]:
                open_episode["censor_reason"] = "scale_down_before_ready"
                open_episode = None
            previous = desired
            nodes = {n['metadata']['name']: n for n in obs.get('nodes', [])}
            claims = {n.get('status', {}).get('providerID'): n for n in obs.get('nodeclaims', []) if n.get('status', {}).get('providerID')}
            for pod in obs['pods']:
                metadata = pod['metadata']
                uid = metadata.get('uid', metadata['name'])
                stage = pod_stages.setdefault(uid, {'pod': metadata['name'], 'uid': uid})
                stage['pod_created_unix_s'] = stamp(metadata.get('creationTimestamp'))
                for condition in pod.get('status', {}).get('conditions', []):
                    if condition['status'] == 'True' and condition['type'] in ('PodScheduled', 'Ready'):
                        key = 'pod_scheduled_unix_s' if condition['type'] == 'PodScheduled' else 'vllm_ready_unix_s'
                        ts = stamp(condition.get('lastTransitionTime'))
                        if ts is not None:
                            stage.setdefault(key, ts)
                for container in pod.get('status', {}).get('containerStatuses', []):
                    if container['name'] == 'vllm':
                        started = container.get('state', {}).get('running', {}).get('startedAt')
                        if started:
                            stage.setdefault('container_started_unix_s', stamp(started))
                node = nodes.get(pod.get('spec', {}).get('nodeName'))
                if node:
                    stage['node'] = node['metadata']['name']
                    for condition in node.get('status', {}).get('conditions', []):
                        if condition['type'] == 'Ready' and condition['status'] == 'True':
                            stage.setdefault('node_ready_unix_s', stamp(condition.get('lastTransitionTime')))
                    claim = claims.get(node.get('spec', {}).get('providerID'))
                    if claim:
                        stage['nodeclaim_created_unix_s'] = stamp(claim['metadata'].get('creationTimestamp'))
    if open_episode:
        open_episode["censor_reason"] = "observation_ended"
    from .core import quantile
    gaps = [e['gap_s'] for e in episodes if e['gap_s'] is not None]
    return {"episodes": episodes, "pod_stages": list(pod_stages.values()),
            "gap_statistics": {"completed": len(gaps), "censored": len(episodes)-len(gaps), "p50_s": quantile(gaps, .5), "p90_s": quantile(gaps, .9), "p99_s": quantile(gaps, .99), "min_s": min(gaps, default=None), "max_s": max(gaps, default=None)}, "timing": "poll-observed transitions, not exact HPA decision timestamps; raw Kubernetes conditions retained"}
