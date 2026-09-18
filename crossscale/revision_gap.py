"""Offline observed provisioning intervals for the revised comparisons.

State samples alone cannot establish that KEDA/HPA caused a scale decision.
The live controller must separately preserve scaler/HPA evidence.
"""
import math


def observed_gap(samples, initial=2, target=4):
    samples = list(samples)
    if not samples:
        raise ValueError('Capacity observations required')
    times = [s['observed_unix_s'] for s in samples]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Observation times must be finite and strictly increasing')
    if samples[0]['ready'] != initial or samples[0]['desired'] != initial:
        raise ValueError('Observation must begin at the declared initial capacity')
    decision = next((s for s in samples if s['desired'] > initial), None)
    requested = next((s for s in samples if s['desired'] >= target), None)
    usable = next((s for s in samples if decision and s['observed_unix_s'] >= decision['observed_unix_s']
                   and s['ready'] >= target), None)
    start = decision['observed_unix_s'] if decision else None
    end = usable['observed_unix_s'] if usable else None
    return dict(decision_unix_s=start, target_requested_unix_s=requested['observed_unix_s'] if requested else None,
                usable_unix_s=end, observation_end_unix_s=times[-1],
                gap_s=end-start if start is not None and end is not None else None,
                censored=decision is not None and usable is None,
                status='no-scale-observed' if decision is None else ('ready' if usable else 'readiness-censored'),
                timing='First observed transitions; resolution bounded by sample cadence',
                scaler_attribution='Requires separate KEDA/HPA evidence')


def gap_cohort(rows, run_start_unix_s, gap):
    """All offered arrivals in [first scale observation, target readiness).

    An unobserved decision has no gap cohort; a censored interval uses the last
    observation as its boundary and must retain its censor flag in reporting.
    Never filter rejects, timeouts or errors from this denominator.
    """
    start = gap['decision_unix_s']
    if start is None:
        return []
    end = gap['usable_unix_s']
    if end is None:
        end = gap['observation_end_unix_s']
    return [r for r in rows if start <= run_start_unix_s+r['offered_s'] < end]
