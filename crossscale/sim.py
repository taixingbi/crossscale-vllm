"""Toy queueing model for pipeline tests, NOT a validated vLLM simulator."""
import math
import random
from .core import quantile, workload, write_run
from .policy import decision


def run(c, baseline, out):
    rows = workload(c)
    rng = random.Random(c["seed"] + 1000)
    ready = c["max_replicas"] if baseline == "B1" else c["initial_replicas"]
    desired = ready
    pending, running, queue, deferred, series = [], [], [], [], []
    index, next_slow, gpu_seconds = 0, 0, 0
    dt = c["fast_interval_s"]
    horizon = c["duration_s"] + c["drain_s"]
    for step in range(math.ceil(horizon / dt) + 1):
        now = step * dt
        for actual, predicted in pending[:]:
            if actual <= now:
                ready += 1
                pending.remove((actual, predicted))
        for r in running[:]:
            if r["finish_s"] <= now:
                r["status"] = "completed"
                running.remove(r)
        active = {t: sum(r["tenant"] == t for r in running + queue) for t in c["tenants"]}
        new = deferred
        deferred = []
        while index < len(rows) and rows[index]["offered_s"] <= now:
            new.append(rows[index])
            index += 1
        for r in new:
            etas = [a if baseline == "oracle-eta" else p for a, p in pending]
            action = decision(c, baseline, r, now, ready, desired, active, etas)
            if action == "delay":
                deferred.append(r)
            elif action == "reject":
                r.update(status="rejected", admission_delay_s=max(0, now-r["offered_s"]))
            else:
                r["admission_delay_s"] = max(0, now-r["offered_s"])
                queue.append(r)
                active[r["tenant"]] += 1
        while queue and len(running) < ready * c["slots_per_replica"]:
            r = queue.pop(0)
            prefill = r["input_tokens"] / c["prefill_tokens_s"]
            r.update(ttft_s=now-r["offered_s"]+prefill, tpot_s=1/c["decode_tokens_s"], finish_s=now+prefill+(r["output_tokens"]-1)/c["decode_tokens_s"])
            running.append(r)
        for group in (running, queue, deferred):
            for r in group[:]:
                if now-r["offered_s"] >= c["request_timeout_s"]:
                    r["status"] = "timeout"
                    group.remove(r)
        if now >= next_slow and now < c["duration_s"]:
            next_slow = now + c["slow_interval_s"]
            if baseline not in ("B0", "B1", "B4"):
                if baseline == "B2":
                    target = math.ceil(len(queue) / c["queue_target"])
                else:
                    # Completed-request SLO signal; do not read future arrivals.
                    recent = [r for r in rows[:index] if r.get("status") == "completed" and now-r["finish_s"] <= 30]
                    saturation = []
                    for t, spec in c["tenants"].items():
                        samples = [r for r in recent if r["tenant"] == t]
                        if samples:
                            saturation.append(max(quantile([r["ttft_s"] for r in samples], .9)/spec["ttft_s"], quantile([r["tpot_s"] for r in samples], .9)/spec["tpot_s"]))
                    target = math.ceil(ready * max(saturation, default=1))
                # Scale-out only for E1/E2; avoids conflating downscale policy.
                target = min(c["max_replicas"], max(desired, target))
                for _ in range(target-desired):
                    lag = c["provisioning_lag_s"] * rng.uniform(.85, 1.15)
                    pending.append((now+lag, now+c["provisioning_lag_s"]*(1+c["eta_error"])))
                desired = target
            series.append(dict(t_s=now, ready=ready, desired=desired, pending=len(pending), queue=len(queue), running=len(running), deferred=len(deferred)))
        gpu_seconds += ready * dt
        if index == len(rows) and not running and not queue and not deferred and now >= c["duration_s"]:
            break
    for r in rows:
        r.setdefault("status", "timeout")
    return write_run(out, c, rows, series, "simulation", baseline, {"ready_gpu_hours": gpu_seconds/3600, "cost_warning": "ready-time proxy excludes node boot and teardown; not billable GPU-hours", "warning": "synthetic queueing model, not paper evidence"})
