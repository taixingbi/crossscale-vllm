# Post-E0 execution order — user revision, 2026-09-12

This revision supersedes the old E1–E7 numbering and automatic continuation
gate in FULL_EXPERIMENT_PROTOCOL.md. Preserve all historical results and labels;
new artifacts must use a distinct `revision-20260912` root and explicit phase
names. Current authorization is E0 completion, then E1, E2, and the priority
E3 B3/B5/B6 comparison. E4–E8 are deferred until the E3 checkpoint is reviewed.
Do not optimize for an expected baseline ordering or suppress negative results.

## Transition from E0

Let the existing e0-prefill4096 controller finish without interruption. Verify
30 episodes in each cache condition, errors/censoring, completion/restoration,
worker exit and suite.lock before another controller starts. Preserve the
first-20 training / last-10 held-out ETA split. Checkpoint raw evidence to S3
and locally, then commit/push each completed phase and verify the remote commit.
The active controller does not automatically launch these new phases.

Continue under the separately named 4096 batch-token serving condition with
the same model, full workload distributions, SLOs and dispatch-validity rules.
Reapply and record this condition after E0 restores 1024. Keep the original GPU,
maximum four GPUs, exclusive suite.lock, ownership-aware cleanup, and archiver.
Inspect live worker state on every continuation; never run duplicate suites.

## E1 — single-GPU capacity profiling

Fix one Ready vLLM replica on one GPU, warmed, with no autoscaler or admission.
Sweep A, B and C separately, at least three independent repetitions per point
(use five around the capacity boundary). Predeclare rates, seeds, horizon and
sample sufficiency before collecting outcomes; retain every failed/invalid run.
Compute R_ref,A/B/C as the highest consecutively passing tested rate with at
least 95% TTFT-and-TPOT SLO goodput in every valid repetition. Inactive tenants
are excluded from isolated-tenant qualification, never treated as failures or
fabricated passing samples. Report sample counts and uncertainty.

Also measure the intended mixed-tenant reference load and verify the two-GPU
mixed capacity used by E2. Do not sum isolated capacities or assume linear
scaling. The historical .01 RPS single-GPU and .005 RPS two-GPU qualifications
are sparse exploratory evidence, not proof of positive scaling. If calibration
is infeasible, report the specific limitation; do not silently loosen SLOs or
search seeds for favorable results.

Collect waiting queue, running requests, KV usage, prompt/generation tokens/s,
P95/P99 TTFT and per-tenant SLO goodput throughout each run and drain. Verify
installed metric names and availability before measurement. Missing series are
explicitly unavailable, not zero. Deliver offered-load versus SLO-goodput curves
with per-run evidence, aggregate uncertainty and frozen calibration artifacts.

## E2 — provisioning-gap baseline

Run B2 Queue-KEDA and B3 SLO-KEDA only, initially two Ready GPUs. Use 65% of
measured two-GPU mixed capacity before t=60 seconds and 165% afterward (fixed
choices within the user's 60–70% / 150–180% ranges). KEDA/HPA must actually request
2 to 4 replicas. Do not substitute a manual replica patch for that decision.
Keep comparable initial cache/node conditions and use five paired seeds with
identical offered traces across baselines. Freeze scaler settings on disjoint
training seeds before evaluation; retain training results.

Capture desired/ready/pending replicas, queue depth, P99 TTFT and per-tenant SLO
goodput, retaining raw request timing and provisioning events. Observe through
actual readiness and drain; if the observation horizon is insufficient, label
it censored. Plot scale decision to usable GPU readiness against SLO failures.
Report whether a provisioning gap occurred, not that it necessarily occurred.

## E3 — priority headline comparison and go/no-go

First run B3 SLO-KEDA, B5 hierarchical without ETA, and B6 CrossScale. Use five
paired seeds, identical arrival traces/token IDs, serving configuration, initial
capacity/cache state, and randomized baseline order fixed before outcomes.
Audit real policy behavior: B5 and B6 must differ in ETA use as specified.
The broader headline set also includes B2 and B4 Admission-only, but obtain
the priority trio and evaluate the checkpoint before broadening experiments.

Primary metric: weighted SLO goodput over ALL offered requests (including
rejects/failures). Secondary: Gold/A goodput, P99 TTFT, reject/defer fraction,
GPU utilization and tokens/s. Report whole-run and provisioning-gap cohorts,
paired run-level differences and bootstrap 95% intervals for B6-B5, B5-B3 and
B6-B3. Predeclare a practical effect criterion before test outcomes; the user's
desired ordering is a hypothesis, not an acceptance requirement for reporting.
Retain any historical gate analysis under its historical name, not as a reason
to skip this new E3 trio. Avoid claiming a causal decomposition from ordering
alone; identify other differences or use matched scale schedules as needed.

Stop expansion at this checkpoint and report whether B6's additional benefit
over B5 is supported and concentrated between scale decision and readiness.
If B6 and B5 are similar, report weak ETA evidence; if B5/B6 are similar to B3,
report weak fast-admission evidence. Inconclusive low-count results remain
inconclusive. Do not automatically start E4–E8 even for a favorable result.

## Deferred roadmap (not currently authorized to launch)

- E4: A/B constant, C 1x to 4x; A protection, C defer/reject and utilization.
- E5: controlled usable-capacity lag 0/15/30/60/90/120 seconds; B3/B5/B6.
  Validate real readiness gating; do not present simulation as live evidence.
- E6: ETA multiplicative errors -50/-25/0/+25/+50%, plus oracle and no ETA.
- E7: B3, B5, CrossScale-noTenant, CrossScale, Oracle; audit actual admission,
  slow scaling, ETA and tenant-weight differences. Oracle is explicitly labeled.
- E8: 30–60 minute low/burst/recover/RAG-heavy/burst/low trace, GPU-hours,
  weighted goodput, cost per SLO-success, scale-outs and scale-down oscillation;
  cost–SLO frontier. Use actual instance lifecycle/billing evidence and disclose
  cost assumptions; ready-time GPU-hours are not AWS cost.

After E3 evidence is secured, retain one healthy original GPU/replica and avoid
leaving added experiment GPUs idle. Follow existing scoped cleanup rules while
preserving evidence needed for a user-approved later phase.
