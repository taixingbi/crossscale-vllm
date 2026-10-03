"""Replay recorded live decisions; do not infer ETA use from timing overhead."""
from collections import Counter
from .policy import decision


def audit_decisions(config, rows):
    actions, requests, mismatches = Counter(), {}, []
    tenant_counterfactual, eta_counterfactual = 0, 0
    for index, row in enumerate(rows):
        baseline = row['baseline']
        args = (row['request'], row['now_monotonic_s'], row['ready'],
                row['desired'], row['active'], row['pending_etas_monotonic_s'])
        replay = decision(config, baseline, *args)
        actions[row['action']] += 1
        if replay != row['action']:
            mismatches.append(dict(index=index, recorded=row['action'], replay=replay))
        rid = row.get('request_id')
        if rid is not None:
            requests.setdefault(rid, set()).add(row['action'])
        # Counterfactuals hold observed state fixed: they are branch diagnostics,
        # not alternate trajectories or causal outcome estimates.
        if baseline in ('B6', 'no-tenant', 'oracle-eta'):
            weighted = decision(config, 'B6', *args)
            uniform = decision(config, 'no-tenant', *args)
            tenant_counterfactual += weighted != uniform
            eta_counterfactual += replay != decision(config, baseline, *args[:-1], [])
    return dict(recorded_decisions=sum(actions.values()), action_counts=dict(actions),
        replay_mismatches=mismatches, replay_valid=not mismatches,
        identified_requests=len(requests),
        requests_with_actual_delay=sum('delay' in a for a in requests.values()),
        requests_rejected=sum('reject' in a for a in requests.values()),
        requests_admitted=sum('admit' in a for a in requests.values()),
        tenant_branch_differences=tenant_counterfactual,
        eta_branch_differences=eta_counterfactual,
        limitations=['Decision counts can include repeated delay checks per request.',
            'Counterfactual branch differences hold observed state fixed; no causal trajectory claim.',
            'Missing audit/request IDs require separate coverage checks against offered requests.'])
