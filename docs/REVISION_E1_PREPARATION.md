# Revision E1 preparation, 2026-09-12

The isolated-tenant runner is prepared locally; it has not been copied to the
active runner or launched. E0 remains untouched. Current execution scope is
POST_E0_EXECUTION.md.

Frozen isolated plan: configs/revision-20260912/e1-isolated-plan.json.
Use `python -m crossscale.revision_e1 --execute --config configs/default.json
--plan configs/revision-20260912/e1-isolated-plan.json` only after separately
verifying E0 completion, restoration, worker exit and lock release. The module
also requires the E0 completion/restoration artifacts, 30 error-free summaries
per condition, and an exclusive nonblocking lock. Existing output directories
are rejected; partial evidence must be diagnosed before any continuation.

A rates: .05/.1/.2/.4/.8/1.6 RPS. B: .01/.025/.05/.1/.2/.4.
C: .005/.01/.025/.05/.1/.2. Seeds 601–605 at every point ensure five
repetitions around any observed boundary. Arrival horizon is max(600, ceil(100
/ RPS)) seconds; all 90 frozen traces have at least 60 active-tenant requests.
This takes 85 arrival-hours plus drains, warmups and rollouts. Rates, seeds and
horizons do not change based on results. Do not search lower rates afterward
for favorable samples. An unqualified tenant remains unqualified.

Qualification requires at least 95% joint TTFT/TPOT goodput in every fixed
repetition and every lower tested point, with maximum dispatch lag <=50 ms.
Failures remain in the denominator. Inactive tenants remain null in the raw
summary and are excluded only from isolated qualification. No mixed weighted
goodput is inferred from isolated runs. Minimum 60 samples is an operational
floor, not evidence of precise P99 or 95% population coverage; report counts
and uncertainty with results.

The runner uses the original GPU, fixed one replica, no scaler/admission,
4096 batch tokens and unchanged tenant distributions/SLOs. It records installed
metric names and verifies required vLLM/Prometheus waiting/running/KV and token
counter-rate series before measurement. GPU utilization may be unavailable;
missing series remain explicit in telemetry manifests. Every run retains raw
requests, P95/P99 TTFT/TPOT, per-tenant goodput, Kubernetes observation, cluster
snapshots and raw Prometheus queries through the entire arrival/drain horizon.
Original 1024 serving arguments are restored afterward with warmup verification.

Before launch, verify the installed metric preflight and deployed dependency
versions; offline tests cannot validate cluster telemetry. Mixed one/two-GPU
calibration still needs its own frozen plan and runner, with adequate per-tenant
counts and no summing of isolated capacities. This module intentionally does
not launch E2/E3 or any mixed calibration automatically. Continue those under
the revised protocol after the isolated phase and calibration review.

Validation: three offline tests cover fixed trace sample counts, inactive-tenant
qualification versus failures/dispatch invalidity, and consecutive-rate plus
complete-seed requirements. Compilation and whitespace checks passed.
