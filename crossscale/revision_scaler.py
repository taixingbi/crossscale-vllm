"""Offline identity audit of captured scaler evidence, not causal attribution."""
import math


def audit_scaler_snapshot(snapshot, *, deployment_uid, scaledobject_uid,
                          namespace='crossscale', name='vllm',
                          experiment='full-20260908'):
    """Require pinned identities and a unique, owned HPA targeting the deployment.

    Call with UIDs saved by the future live controller at phase setup. Never
    infer those expected identities from the snapshot being audited. A linked
    result does not prove a scale operation: status can lag, Events can expire,
    and the captured API reads are sequential. Raw evidence remains authoritative.
    """
    if not deployment_uid or not scaledobject_uid:
        raise ValueError('Setup-pinned deployment and ScaledObject UIDs required')
    result = dict(status='unverified', reasons=[], hpa_uid=None,
                  reported_desired_replicas=None, rescale_events=[],
                  read_window=None, causal_attribution=False)

    def reject(reason):
        result['reasons'].append(reason)
        return result

    dep = snapshot.get('deployment') or {}
    meta = dep.get('metadata', {})
    if (meta.get('uid'), meta.get('namespace'), meta.get('name')) != (
            deployment_uid, namespace, name) or meta.get('deletionTimestamp'):
        return reject('deployment-identity-mismatch-or-deleting')
    capture = snapshot.get('scaler')
    if not isinstance(capture, dict):
        return reject('scaler-evidence-unavailable')
    times = [snapshot.get('observed_unix_s'), capture.get('read_started_unix_s'),
             capture.get('read_finished_unix_s')]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times)
            or not times[0] <= times[1] <= times[2]):
        return reject('invalid-observation-window')
    result['read_window'] = times[1:]
    scaler = capture.get('scaledobject') or {}
    meta = scaler.get('metadata', {})
    if (meta.get('uid'), meta.get('namespace'), meta.get('name')) != (
            scaledobject_uid, namespace, name) or meta.get('deletionTimestamp'):
        return reject('scaledobject-identity-mismatch-or-deleting')
    if meta.get('labels', {}).get('crossscale-experiment') != experiment:
        return reject('scaledobject-experiment-label-mismatch')

    def targets_deployment(target, defaults=False):
        return (target.get('name') == name
                and target.get('kind', 'Deployment' if defaults else None) == 'Deployment'
                and target.get('apiVersion', 'apps/v1' if defaults else None) == 'apps/v1')

    if not targets_deployment(scaler.get('spec', {}).get('scaleTargetRef', {}), True):
        return reject('scaledobject-target-mismatch')
    hpas = capture.get('hpa')
    events = capture.get('events')
    if not isinstance(hpas, dict) or not isinstance(hpas.get('items'), list):
        return reject('hpa-list-unavailable')
    if not isinstance(events, dict) or not isinstance(events.get('items'), list):
        return reject('event-list-unavailable')
    candidates = [h for h in hpas['items']
                  if h.get('metadata', {}).get('namespace') == namespace
                  and targets_deployment(h.get('spec', {}).get('scaleTargetRef', {}))]
    # A deleting competitor can still have acted during the read window.
    if len(candidates) != 1:
        return reject('missing-or-competing-target-hpas')
    hpa = candidates[0]
    meta = hpa.get('metadata', {})
    owners = [o for o in meta.get('ownerReferences', []) if o.get('controller') is True]
    if (not meta.get('uid') or not meta.get('name') or meta.get('deletionTimestamp')
            or len(owners) != 1
            or (owners[0].get('uid'), owners[0].get('kind'), owners[0].get('name'),
                owners[0].get('apiVersion')) !=
               (scaledobject_uid, 'ScaledObject', name, 'keda.sh/v1alpha1')):
        return reject('hpa-owner-mismatch-or-deleting')
    desired = hpa.get('status', {}).get('desiredReplicas')
    if type(desired) is not int or desired < 0:
        return reject('hpa-desired-replicas-unavailable')
    result.update(status='identity-linked', hpa_uid=meta['uid'],
                  reported_desired_replicas=desired)
    for event in events['items']:
        ref = event.get('involvedObject', {})
        if (event.get('reason') == 'SuccessfulRescale'
                and (ref.get('uid'), ref.get('kind'), ref.get('namespace'), ref.get('name')) ==
                    (meta['uid'], 'HorizontalPodAutoscaler', namespace, meta['name'])):
            result['rescale_events'].append(event)
    return result
