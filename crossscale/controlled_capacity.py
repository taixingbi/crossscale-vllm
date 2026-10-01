"""Observed Kubernetes gate driver for the frozen prewarmed supply experiment."""
import time
from .readiness_gate import patch_gate
from .revision_e5 import capacity_state


class GateDriver:
    def __init__(self, cluster, owner, baseline_uids, withheld_uids, lag_s, tolerance_s=5):
        self.cluster, self.owner = cluster, owner
        self.baseline, self.withheld = baseline_uids, withheld_uids
        self.lag, self.tolerance = lag_s, tolerance_s
        self.start = None
        self.observed_release = None

    def on_start(self, wall):
        if self.start is not None:
            raise RuntimeError('Controlled run already started')
        self.start = wall

    def __call__(self, snapshot):
        state = capacity_state(snapshot, self.baseline, self.withheld, self.start, self.lag)
        slices = self.cluster.get('endpointslices', selector='kubernetes.io/service-name=vllm')
        routable = {e.get('targetRef', {}).get('uid') for s in slices['items']
                    for e in s.get('endpoints', []) if e.get('conditions', {}).get('ready')}
        snapshot['endpoint_slices'] = slices
        state['routable_uids'] = sorted(routable)
        target = state['release_target_unix_s']
        now = time.time()
        if target is None or now < target:
            if routable & set(self.withheld):
                raise RuntimeError('Withheld pod routed before release')
        else:
            for pod in snapshot['pods']:
                if pod['metadata']['uid'] in self.withheld:
                    try:
                        patch_gate(self.cluster, pod, self.owner, True, now)
                    except RuntimeError as exc:
                        # A concurrent kubelet update requires a fresh snapshot;
                        # never resend a stale full condition list.
                        if 'HTTP 409' not in str(exc):
                            raise
            if state['ready'] == 4 and set(self.baseline + self.withheld) <= routable:
                if self.observed_release is None:
                    self.observed_release = time.time()
                if self.observed_release > target + self.tolerance:
                    raise RuntimeError('Observed controlled release exceeded frozen tolerance')
            if self.observed_release is None and now > target + self.tolerance:
                raise RuntimeError('Controlled release missed frozen readiness tolerance')
        state['observed_release_unix_s'] = self.observed_release
        return state
