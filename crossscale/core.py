from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

BASELINES = ("B0", "B1", "B2", "B3", "B4", "B5", "B6", "no-tenant", "oracle-eta", "ready-only")


def config(path):
    c = json.loads(Path(path).read_text())
    for key in ("duration_s", "drain_s", "fast_interval_s", "slow_interval_s", "slots_per_replica", "prefill_tokens_s", "decode_tokens_s", "queue_target", "request_timeout_s"):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if not 1 <= c["initial_replicas"] <= c["max_replicas"]:
        raise ValueError("invalid replica bounds")
    if c["provisioning_lag_s"] < 0 or c["eta_error"] < -1:
        raise ValueError("lag >= 0 and ETA error >= -1 required")
    starts = [p["start_s"] for p in c["phases"]]
    if not starts or starts[0] != 0 or starts != sorted(set(starts)) or starts[-1] >= c["duration_s"]:
        raise ValueError("phases must start at zero and increase within duration")
    for t in c["tenants"].values():
        if any(t[k] <= 0 for k in ("input_median", "output_median", "ttft_s", "tpot_s", "weight")) or t["sigma"] < 0:
            raise ValueError("invalid tenant parameters")
    for p in c["phases"]:
        if set(p["rates"]) != set(c["tenants"]) or any(not math.isfinite(x) or x < 0 for x in p["rates"].values()):
            raise ValueError("each phase needs nonnegative finite rates for every tenant")
    return c


def workload(c):
    """Open-loop piecewise Poisson arrivals, independent of system responses."""
    rng = random.Random(c["seed"])
    rows = []
    for n, phase in enumerate(c["phases"]):
        end = c["phases"][n + 1]["start_s"] if n + 1 < len(c["phases"]) else c["duration_s"]
        for tenant, rate in sorted(phase["rates"].items()):
            if rate == 0:
                continue
            t = phase["start_s"]
            spec = c["tenants"][tenant]
            while True:
                t += rng.expovariate(rate)
                if t >= end:
                    break
                lengths = [max(2, min(16384, round(rng.lognormvariate(math.log(spec[k]), spec["sigma"])))) for k in ("input_median", "output_median")]
                rows.append(dict(tenant=tenant, offered_s=t, input_tokens=lengths[0], output_tokens=lengths[1]))
    rows.sort(key=lambda r: (r["offered_s"], r["tenant"]))
    return [dict(r, id=i) for i, r in enumerate(rows)]


def quantile(xs, p):
    if not xs:
        return None
    return _sorted_quantile(sorted(xs), p)


def _sorted_quantile(xs, p):
    if not xs:
        return None
    x = (len(xs) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return xs[lo] + (xs[hi] - xs[lo]) * (x - lo)


def summarize(rows, c):
    result = {}
    grouped = {tenant: [] for tenant in c["tenants"]}
    for row in rows:
        if row["tenant"] in grouped:
            grouped[row["tenant"]].append(row)
    for tenant, spec in c["tenants"].items():
        rs = grouped[tenant]
        done = [r for r in rs if r["status"] == "completed"]
        good = [r for r in done if r.get("ttft_s") is not None and r.get("tpot_s") is not None and r["ttft_s"] <= spec["ttft_s"] and r["tpot_s"] <= spec["tpot_s"]]
        result[tenant] = {"offered": len(rs), "completed": len(done), "good": len(good), "goodput": len(good) / len(rs) if rs else None,
                          "rejected": sum(r["status"] == "rejected" for r in rs),
                          "timeout": sum(r["status"] == "timeout" for r in rs),
                          "errors": sum(r["status"] == "error" for r in rs),
                          "deferred": sum(r.get("admission_delay_s", 0) > 0 for r in rs)}
        for metric in ("ttft_s", "tpot_s", "admission_delay_s", "dispatch_lag_s"):
            values = sorted(r[metric] for r in done if r.get(metric) is not None)
            for p in (0.95, 0.99):
                result[tenant][f"p{round(p*100)}_{metric}"] = _sorted_quantile(values, p)
    # Missing tenants make the headline undefined, not silently reweighted.
    wg = None if any(v["goodput"] is None for v in result.values()) else sum(c["tenants"][t]["weight"] * v["goodput"] for t, v in result.items()) / sum(t["weight"] for t in c["tenants"].values())
    gs = [v["goodput"] for v in result.values() if v["goodput"] is not None]
    fairness = sum(gs)**2 / (len(gs)*sum(x*x for x in gs)) if gs and any(gs) else None
    return {"tenants": result, "weighted_slo_goodput": wg, "jain_goodput": fairness,
            "completed_tokens_s": sum(r.get("actual_output_tokens", r["output_tokens"]) for r in rows if r["status"] == "completed") / c["duration_s"],
            "tokens_rate_denominator": "offered duration; includes drain completions",
            "latency_population": "completed requests only; failures remain in goodput denominator"}


def write_run(out, c, rows, series, mode, baseline, extra=None):
    p = Path(out)
    p.mkdir(parents=True, exist_ok=False)
    for name, data in (("requests", rows), ("timeseries", series)):
        with (p / f"{name}.jsonl").open("w") as stream:
            for row in data:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
    (p / "config.json").write_text(json.dumps(c, indent=2))
    summary = summarize(rows, c) | (extra or {})
    (p / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    # Preserve the original JSON-array hash without materializing a second trace.
    trace_hash = hashlib.sha256()
    trace_hash.update(b"[")
    for index, row in enumerate(rows):
        if index:
            trace_hash.update(b", ")
        trace = {k: row[k] for k in ("id", "tenant", "offered_s", "input_tokens", "output_tokens")}
        trace_hash.update(json.dumps(trace, sort_keys=True).encode())
    trace_hash.update(b"]")
    (p / "manifest.json").write_text(json.dumps({"mode": mode, "baseline": baseline, "seed": c["seed"], "trace_sha256": trace_hash.hexdigest()}, indent=2))
    return summary
