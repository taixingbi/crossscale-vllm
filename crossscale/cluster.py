"""Small in-cluster API client used by the dedicated experiment runner."""
import json
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Cluster:
    namespace = 'crossscale'
    pool = 'crossscale-gpu'

    def __init__(self):
        self.base = 'https://kubernetes.default.svc'
        self.identity = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.tls = ssl.create_default_context(cafile=str(self.identity / 'ca.crt'))

    def request(self, method, path, body=None, missing_ok=False):
        headers = {'Authorization': 'Bearer ' + (self.identity / 'token').read_text().strip()}
        if body is not None:
            headers['Content-Type'] = 'application/merge-patch+json' if method == 'PATCH' else 'application/json'
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                      method=method, headers=headers)
        try:
            with urlopen(req, context=self.tls, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(f'{method} {path}: HTTP {exc.code}: {exc.read().decode()}') from exc

    @staticmethod
    def path(kind, name=None, all_namespaces=False):
        paths = {
            'deployment': '/apis/apps/v1/namespaces/crossscale/deployments',
            'pods': '/api/v1/pods' if all_namespaces else '/api/v1/namespaces/crossscale/pods',
            'nodes': '/api/v1/nodes',
            'nodeclaims': '/apis/karpenter.sh/v1/nodeclaims',
            'nodepool': '/apis/karpenter.sh/v1/nodepools',
            'nodeclass': '/apis/karpenter.k8s.aws/v1/ec2nodeclasses',
            'scaledobject': '/apis/keda.sh/v1alpha1/namespaces/crossscale/scaledobjects',
            'hpa': '/apis/autoscaling/v2/namespaces/crossscale/horizontalpodautoscalers',
            'events': '/api/v1/namespaces/crossscale/events',
        }
        return paths[kind] + ('/' + name if name else '')

    def get(self, kind, name=None, selector=None, missing_ok=False, all_namespaces=False):
        path = self.path(kind, name, all_namespaces)
        if selector:
            path += '?' + urlencode({'labelSelector': selector})
        return self.request('GET', path, missing_ok=missing_ok)

    def patch(self, kind, name, body):
        return self.request('PATCH', self.path(kind, name), body)

    def scale(self, replicas):
        if type(replicas) is not int or not 1 <= replicas <= 4:
            raise ValueError('experiment replica count must be in [1,4]')
        if self.get('scaledobject', 'vllm', missing_ok=True):
            raise RuntimeError('remove the experiment scaler before manually scaling')
        if self.get('hpa', selector=None)['items']:
            raise RuntimeError('manual scaling requires no HPA in the experiment namespace')
        return self.patch('deployment', 'vllm', {'spec': {'replicas': replicas}})

    def snapshot(self):
        import time
        dep = self.get('deployment', 'vllm')
        pods = self.get('pods', selector='app=vllm')['items']
        nodes = self.get('nodes')['items']
        claims = self.get('nodeclaims', selector='karpenter.sh/nodepool=crossscale-gpu')['items']
        return dict(observed_unix_s=time.time(), deployment=dep, pods=pods, nodes=nodes, nodeclaims=claims)


def can_delete_empty_claim(claim, pods, owned_names):
    """Fail closed: never terminate baseline/foreign claims or active workloads."""
    metadata = claim['metadata']
    if metadata['name'] not in owned_names:
        return False
    if metadata.get('labels', {}).get('karpenter.sh/nodepool') != 'crossscale-gpu':
        return False
    node = claim.get('status', {}).get('nodeName')
    if not node:
        return False
    for pod in pods:
        if pod.get('spec', {}).get('nodeName') != node:
            continue
        if pod.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
            continue
        if any(owner.get('kind') == 'DaemonSet' for owner in pod['metadata'].get('ownerReferences', [])):
            continue
        # Terminating workloads still count until they are actually gone.
        return False
    return True
