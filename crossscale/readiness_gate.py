"""Explicit Kubernetes readiness condition for controlled-capacity experiments.

This helper does not launch measurements. The caller must validate actual
EndpointSlice routing and record observed release times before using it in E5.
"""
import math
from datetime import datetime, timezone

CONDITION = 'crossscale.dev/CapacityReleased'
OWNER_LABEL = 'crossscale-controlled-capacity'


def release_schedule(pods, baseline_uids, release_unix_s):
    """Fixed prewarmed pod identities; a monotonic wall-clock release schedule."""
    if not math.isfinite(release_unix_s):
        raise ValueError('Release time must be finite')
    uids = [p['metadata']['uid'] for p in pods]
    if len(uids) != 4 or len(set(uids)) != 4:
        raise ValueError('Exactly four distinct prewarmed pods required')
    if len(set(baseline_uids)) != 2 or not set(baseline_uids) <= set(uids):
        raise ValueError('Exactly two baseline pod identities required')
    return {uid: None if uid in baseline_uids else release_unix_s for uid in uids}


def condition_patch(pod, owner, released, now_unix_s):
    """Build a resource-version-guarded status merge without dropping conditions.

    Kubernetes combines this custom condition with ContainersReady to compute
    Pod Ready. Setting it true never asserts that the model itself is healthy.
    """
    if type(released) is not bool or not owner:
        raise ValueError('Explicit boolean release and nonempty owner required')
    meta = pod['metadata']
    if meta.get('deletionTimestamp'):
        raise ValueError('Refusing a terminating pod')
    if meta.get('labels', {}).get(OWNER_LABEL) != owner:
        raise ValueError('Pod is not owned by this controlled-capacity run')
    gates = pod.get('spec', {}).get('readinessGates', [])
    if {'conditionType': CONDITION} not in gates:
        raise ValueError('Pod does not declare the capacity readiness gate')
    conditions = [dict(c) for c in pod.get('status', {}).get('conditions', [])]
    found = [c for c in conditions if c['type'] == CONDITION]
    if len(found) > 1:
        raise ValueError('Duplicate readiness condition')
    status = 'True' if released else 'False'
    if found and found[0]['status'] == status:
        return None
    conditions = [c for c in conditions if c['type'] != CONDITION]
    conditions.append(dict(type=CONDITION, status=status,
                           lastTransitionTime=datetime.fromtimestamp(now_unix_s, timezone.utc)
                           .isoformat().replace('+00:00', 'Z'),
                           reason='CapacityReleased' if released else 'ControlledDelay',
                           message='Explicit experiment capacity gate'))
    return dict(metadata=dict(uid=meta['uid'], resourceVersion=meta['resourceVersion']),
                status=dict(conditions=conditions))


def desired_release(schedule, uid, now_unix_s):
    if not math.isfinite(now_unix_s):
        raise ValueError('Observation time must be finite')
    # A replacement UID must never inherit permission to serve.
    if uid not in schedule:
        raise ValueError('Unexpected pod identity; controlled experiment must stop')
    when = schedule[uid]
    return when is None or now_unix_s >= when


def patch_gate(cluster, pod, owner, released, now_unix_s):
    patch = condition_patch(pod, owner, released, now_unix_s)
    if patch is None:
        return pod
    name = pod['metadata']['name']
    return cluster.request('PATCH', cluster.path('pods', name) + '/status', patch)
