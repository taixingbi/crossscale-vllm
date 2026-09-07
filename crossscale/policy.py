"""Shared admission rule. ETA grants waiting time, never dispatch slots."""
import math


def decision(c, baseline, request, now, ready, desired, active, pending_etas):
    if baseline in ("B0", "B1", "B2", "B3"):
        return "admit"
    spec = c["tenants"][request["tenant"]]
    prefill = request["input_tokens"] / c["prefill_tokens_s"]
    remaining = spec["ttft_s"] - (now - request["offered_s"]) - prefill
    if remaining <= 0:
        return "reject"
    total = max(0, ready) * c["slots_per_replica"]
    # B5 is the deliberately optimistic desired-capacity ablation.
    perceived = desired * c["slots_per_replica"] if baseline == "B5" else total
    used = sum(active.values())
    weight = 1 if baseline == "no-tenant" else spec["weight"]
    denominator = len(c["tenants"]) if baseline == "no-tenant" else sum(t["weight"] for t in c["tenants"].values())
    budget = max(1, math.floor(perceived * weight / denominator)) if perceived else 0
    if used < perceived and active.get(request["tenant"], 0) < budget:
        return "admit"
    if baseline in ("B6", "no-tenant", "oracle-eta") and pending_etas:
        # Only defer if a conservative ETA still fits this request's TTFT budget.
        if min(pending_etas) + c["eta_margin_s"] <= now + remaining:
            return "delay"
    return "reject"
