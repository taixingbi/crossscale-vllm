"""Durable real-cluster scale-out episodes; only dedicated experiment resources."""
import argparse
import gzip
import json
from pathlib import Path
import threading
import time

from .cluster import Cluster, can_delete_empty_claim
from .kube import ready, stamp, extract


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


class Observer:
    def __init__(self, cluster, out, eta=60):
        self.cluster, self.out, self.eta = cluster, Path(out), eta
        self.stop = threading.Event()
        self.started = threading.Event()
        self.error = None

    def loop(self):
        try:
            with gzip.open(self.out / 'observations.jsonl.gz', 'wt') as stream:
                while not self.stop.is_set():
                    obs = self.cluster.snapshot()
                    stream.write(json.dumps(obs) + '\n')
                    stream.flush()
                    pods = [p for p in obs['pods'] if not p['metadata'].get('deletionTimestamp')]
                    save(self.out / 'state.json', {
                        'observed_unix_s': obs['observed_unix_s'],
                        'ready': sum(ready(p) for p in pods), 'desired': obs['deployment']['spec']['replicas'],
                        'pending_eta_unix_s': [stamp(p['metadata']['creationTimestamp']) + self.eta for p in pods if not ready(p)]})
                    self.started.set()
                    self.stop.wait(1)
        except Exception as exc:
            self.error = repr(exc)
            save(self.out / 'observer-error.json', {'error': self.error, 'unix_s': time.time()})
            self.started.set()

    def __enter__(self):
        self.out.mkdir(parents=True, exist_ok=False)
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        if not self.started.wait(60) or self.error:
            raise RuntimeError('observer failed to start: ' + str(self.error))
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(100)
        if self.thread.is_alive():
            raise RuntimeError('observer failed to stop cleanly')
        if self.error and args[0] is None:
            raise RuntimeError('observer failed: ' + self.error)


class Episodes:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.k = Cluster()
        import boto3
        self.ec2 = boto3.client('ec2', region_name='us-east-1')
        identity = self.root / 'ownership.json'
        if identity.exists():
            self.ownership = json.loads(identity.read_text())
        else:
            self.ownership = {'initial_claims': [p['metadata']['name'] for p in self.claims()], 'owned_claims': [], 'started_unix_s': time.time()}
            save(identity, self.ownership)

    def event(self, event, **details):
        row = dict(unix_s=time.time(), event=event, **details)
        with (self.root / 'events.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)

    def claims(self):
        return self.k.get('nodeclaims', selector='karpenter.sh/nodepool=crossscale-gpu')['items']

    def remember_claims(self):
        owned = set(self.ownership['owned_claims'])
        for claim in self.claims():
            if claim['metadata']['name'] not in self.ownership['initial_claims']:
                owned.add(claim['metadata']['name'])
            provider = claim.get('status', {}).get('providerID', '')
            instance = provider.rsplit('/', 1)[-1]
            path = self.root / 'instances' / (instance + '-first.json')
            if instance.startswith('i-') and not path.exists():
                self.record_instance(instance, 'first')
        self.ownership['owned_claims'] = sorted(owned)
        save(self.root / 'ownership.json', self.ownership)

    def record_instance(self, instance, stage):
        response = self.ec2.describe_instances(InstanceIds=[instance])
        rows = [{key: i.get(key) for key in ('InstanceId', 'ImageId', 'InstanceType', 'LaunchTime', 'State', 'StateTransitionReason', 'Placement')}
                for reservation in response['Reservations'] for i in reservation['Instances']]
        for row in rows:
            if row.get('LaunchTime'):
                row['LaunchTime'] = row['LaunchTime'].isoformat()
        folder = self.root / 'instances'
        folder.mkdir(exist_ok=True)
        save(folder / (instance + '-' + stage + '.json'), {'observed_unix_s': time.time(), 'instances': rows})

    def wait_ready(self, count, timeout=2400):
        end, last_log = time.monotonic() + timeout, 0
        while time.monotonic() < end:
            pods = self.k.get('pods', selector='app=vllm')['items']
            live = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
            n = sum(ready(p) for p in live)
            self.remember_claims()
            if len(live) == count and n == count and len(pods) == count:
                return live
            if time.monotonic() - last_log > 30:
                self.event('waiting-ready', target=count, ready=n, pods=len(pods))
                last_log = time.monotonic()
            for pod in live:
                for container in pod.get('status', {}).get('containerStatuses', []):
                    if container.get('restartCount', 0) >= 3:
                        raise RuntimeError('repeated container failure: ' + pod['metadata']['name'])
            time.sleep(3)
        raise TimeoutError(f'{count} replicas not Ready within {timeout}s')

    def baseline(self):
        self.k.scale(2)
        pods = self.wait_ready(2)
        for pod in pods:
            self.k.patch('pods', pod['metadata']['name'], {'metadata': {'annotations': {'controller.kubernetes.io/pod-deletion-cost': '100'}}})
        return pods

    def cleanup_empty(self):
        pods = self.k.get('pods', all_namespaces=True)['items']
        claims = [c for c in self.claims() if can_delete_empty_claim(c, pods, set(self.ownership['owned_claims']))]
        for claim in claims:
            current_pods = self.k.get('pods', all_namespaces=True)['items']
            if not can_delete_empty_claim(claim, current_pods, set(self.ownership['owned_claims'])):
                raise RuntimeError('node acquired a workload during reset; refusing termination')
            name = claim['metadata']['name']
            provider = claim.get('status', {}).get('providerID')
            if not provider or not provider.rsplit('/', 1)[-1].startswith('i-'):
                raise RuntimeError('refusing claim without known EC2 instance: ' + name)
            instance = provider.rsplit('/', 1)[-1]
            self.record_instance(instance, 'before-termination')
            self.event('terminate-empty-claim', claim=name, instance=instance)
            self.k.request('DELETE', self.k.path('nodeclaims', name), {'preconditions': {'uid': claim['metadata']['uid']}})
            end, last_log = time.monotonic() + 900, 0
            while time.monotonic() < end:
                response = self.ec2.describe_instances(InstanceIds=[instance])
                states = [i['State']['Name'] for r in response['Reservations'] for i in r['Instances']]
                if states == ['terminated'] and self.k.get('nodeclaims', name, missing_ok=True) is None:
                    self.record_instance(instance, 'terminated')
                    self.event('instance-terminated', claim=name, instance=instance)
                    break
                if time.monotonic() - last_log > 30:
                    self.event('waiting-termination', instance=instance, states=states)
                    last_log = time.monotonic()
                time.sleep(5)
            else:
                raise TimeoutError('EC2 termination not confirmed: ' + instance)

    def verify_prebake(self, nodeclass):
        proof = self.root / 'prebaked-verification.json'
        if proof.exists():
            return
        name = 'crossscale-prebake-proof'
        if self.k.get('pods', name, missing_ok=True):
            raise RuntimeError('prebake proof pod already exists; inspect before resuming')
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'crossscale'},
               'spec': {'restartPolicy': 'Never', 'nodeSelector': {'node.kubernetes.io/instance-type': 'g5.xlarge', 'karpenter.sh/nodepool': 'crossscale-gpu'},
                        'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}],
                        'containers': [{'name': 'proof', 'image': 'public.ecr.aws/aws-cli/aws-cli:2.36.17',
                                        'command': ['/bin/sh', '-c', 'test -f /proof/complete && grep -F "56b291b6179fe5e6e6ad5c509d362e745280ccdbe81ecbc0f5155b1cab0ebfc5" /proof/images.txt && grep -F "aws-cli" /proof/images.txt'],
                                        'resources': {'requests': {'cpu': '100m', 'memory': '64Mi', 'nvidia.com/gpu': '1'}, 'limits': {'memory': '128Mi', 'nvidia.com/gpu': '1'}},
                                        'volumeMounts': [{'name': 'complete', 'mountPath': '/proof/complete', 'readOnly': True}, {'name': 'images', 'mountPath': '/proof/images.txt', 'readOnly': True}]}],
                        'volumes': [{'name': 'complete', 'hostPath': {'path': '/var/lib/crossscale-image-bake.complete', 'type': 'File'}},
                                    {'name': 'images', 'hostPath': {'path': '/var/log/crossscale-baked-images.txt', 'type': 'File'}}]}}
        self.k.request('POST', self.k.path('pods'), pod)
        end = time.monotonic() + 2400
        while time.monotonic() < end:
            actual = self.k.get('pods', name)
            self.remember_claims()
            phase = actual.get('status', {}).get('phase')
            if phase == 'Succeeded':
                claims = [c for c in self.claims() if c.get('status', {}).get('nodeName') == actual['spec']['nodeName']]
                if len(claims) != 1 or claims[0]['spec']['nodeClassRef']['name'] != nodeclass:
                    raise RuntimeError('proof ran on an unexpected node class')
                save(proof, {'pod': actual, 'nodeclaim': claims[0]})
                self.k.request('DELETE', self.k.path('pods', name), {'preconditions': {'uid': actual['metadata']['uid']}})
                while self.k.get('pods', name, missing_ok=True):
                    time.sleep(2)
                self.cleanup_empty()
                self.event('prebaked-image-verified', image=claims[0]['status']['imageID'])
                return
            if phase == 'Failed':
                save(self.root / 'prebaked-verification-failed.json', actual)
                raise RuntimeError('prebaked image verification failed')
            self.event('waiting-prebake-verification', phase=phase)
            time.sleep(30)
        raise TimeoutError('prebaked image verification timed out')

    def condition(self, name, nodeclass, repetitions=30):
        if name not in ('cached-on-existing-node', 'cold-new-node', 'prebaked-image-new-node'):
            raise ValueError(name)
        nodeclass_object = self.k.get('nodeclass', nodeclass)
        if not ready(nodeclass_object):
            raise RuntimeError('EC2NodeClass is not Ready: ' + nodeclass)
        self.k.patch('nodepool', 'crossscale-gpu', {'spec': {'template': {'spec': {'nodeClassRef': {'group': 'karpenter.k8s.aws', 'kind': 'EC2NodeClass', 'name': nodeclass}}}}})
        self.baseline()
        if name == 'cached-on-existing-node':
            self.k.scale(4)
            self.wait_ready(4)
            self.baseline()
        else:
            self.cleanup_empty()
            if name == 'prebaked-image-new-node':
                self.verify_prebake(nodeclass)
        condition = self.root / name
        condition.mkdir(exist_ok=True)
        for index in range(repetitions):
            dest = condition / f'episode-{index:02d}'
            if (dest / 'summary.json').exists():
                continue
            if dest.exists():
                raise RuntimeError(f'incomplete episode needs diagnosis before resuming: {dest}')
            self.baseline()
            if name != 'cached-on-existing-node':
                self.cleanup_empty()
                if len(self.claims()) != 2:
                    raise RuntimeError('cold episode requires exactly two surviving GPU claims')
            before = self.k.snapshot()
            self.event('episode-start', condition=name, index=index)
            failure = None
            try:
                with Observer(self.k, dest) as observer:
                    time.sleep(2)
                    self.k.scale(4)
                    self.wait_ready(4)
                    time.sleep(3)
                    if observer.error:
                        raise RuntimeError(observer.error)
            except Exception as exc:
                failure = repr(exc)
            summary = extract(dest / 'observations.jsonl.gz')
            summary.update(condition=name, index=index, nodeclass=nodeclass, error=failure,
                           split='train' if index < 20 else 'held-out',
                           initial_claims=[p['metadata']['name'] for p in before['nodeclaims']])
            save(dest / 'summary.json', summary)
            self.event('episode-complete', condition=name, index=index, statistics=summary['gap_statistics'], error=failure)
            if failure:
                raise RuntimeError('episode failed; retained as censored: ' + failure)
            self.baseline()
            if name != 'cached-on-existing-node':
                self.cleanup_empty()
        summaries = [json.loads((condition / f'episode-{i:02d}' / 'summary.json').read_text()) for i in range(repetitions)]
        from .core import quantile
        training = [e['gap_s'] for s in summaries[:20] for e in s['episodes'] if e['gap_s'] is not None]
        heldout = [e['gap_s'] for s in summaries[20:] for e in s['episodes'] if e['gap_s'] is not None]
        result = {'condition': name, 'episodes': len(summaries), 'training_completed': len(training), 'heldout_completed': len(heldout),
                  'training_p90_s': quantile(training, .9), 'heldout_gaps_s': heldout,
                  'failures': sum(s['error'] is not None for s in summaries)}
        save(condition / 'summary.json', result)
        self.event('condition-complete', **result)
        return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--condition', required=True, choices=['cached-on-existing-node', 'cold-new-node', 'prebaked-image-new-node'])
    p.add_argument('--nodeclass', default='crossscale-gpu')
    args = p.parse_args()
    Episodes(args.out).condition(args.condition, args.nodeclass)


if __name__ == '__main__':
    main()
