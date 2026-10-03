# E7 staged execution — October 3, 2026

E0–E6 measured suites are preserved. E7 begins with a controlled fast-policy
ablation, followed by a separately implemented natural slow-loop audit. Completing
this first subphase alone must not mark all E7 complete.

The frozen plan is `configs/revision-20261003-e7-plan.json`, SHA256
`bf93b5485855e501602430dc0a611b803af8bbaae4cef8233e66a70cacd2171b`.
It pairs B3, B5, no-tenant, CrossScale and Oracle on all five original E5 traces
(871–875), 25 cells, randomized with seed 20261005. Each cell has 600 seconds
of arrivals and 180 seconds of drain observation. The measured mixed capacity,
full workload, B TTFT 3s amendment, batch4096 and one admission slot per Ready
replica remain unchanged. No outcome-dependent trace selection is performed.

The same validated readiness gate supplies two usable prewarmed GPUs initially
and releases two more at t=120s (60s after burst onset). All four GPUs remain
allocated. HPA is absent, checked before and after each run and captured by the
observer; these B3/B5 labels denote their admission policies under matched supply,
not live SLO autoscaling comparisons. Natural slow-loop evidence is still pending.

B3 bypasses admission. B5 uses Ready-only weighted budgets without ETA.
CrossScale uses weighted budgets and the nominal release ETA; no-tenant changes
only budgets to equal weights, retaining each tenant's SLO. Oracle uses the same
known scheduled release instant as CrossScale, not future actual readiness;
EndpointSlice propagation is measured. It is a scheduled-release oracle, not a
natural provisioning oracle. No advantage is expected solely from this label.

The new optional gateway audit records every actual admit/delay/reject decision,
request ID, active tenant counts, observed Ready/desired capacity and perceived
ETA. Replay these records against the policy when analyzing outcomes. Tiny
positive admission overhead in request summaries is not evidence of an ETA delay;
use recorded `delay` actions. Report when the sampled workload never exercises a
tenant budget or ETA difference. Unit tests demonstrate those branches under
contention, but cannot establish that a live trace exercises them.

Primary analysis uses all-offered weighted SLO goodput; paired seed bootstrap
10,000 samples, practical effect .05. Contrasts: CrossScale-B5,
CrossScale-no-tenant, B5-B3 and Oracle-CrossScale. Report whole-run, burst and
observed controlled gap, sparse tenant counts and reused-trace dependence.

The controller requires all 35 unique valid E6 cells and restoration, an exclusive
suite.lock, and a new destination `revision-20260912/e7-controlled-ablations`.
It retains failures, restores the original serving template and single GPU, and
cleans only owned empty claims. It does not start the natural-scaling subphase
or E8 automatically. Never restart it over an existing destination.

Launch verified October 3 around 02:23 UTC: PID 188464 is sleeping/running with
suite.lock held, destination and frozen plan created, four replicas requested.
Three added NodeClaims are provisioning and the original GPU is preserved.
Source/frozen plan commit `bac110eddd4339c3cc656586a570397f1293b33b` was
verified on origin/main before launch. All 25 relevant policy, gateway, gate,
E5/E6/E7 tests passed with the HTTP dependency available. The first measurement
starts only after all four models are Ready, routed, and long-prompt tested.
Log: `/tmp/experiments/revision-e7-controlled.log`; PID file: `e7-controller.pid`.
Allow roughly 5.5 hours for cells plus initial model startup and restoration.

## Natural slow-loop subphase prepared while controlled E7 runs

`crossscale/revision_e7_natural.py` and
`configs/revision-20261003-e7-natural-plan.json` are prepared locally, not deployed
into the active runtime. Plan SHA256:
`caecb17f7dacb471b78724d8d10ae02e013b2eaf2c9819014095ea3d2bbebb5e`.
Twenty cells pair B3/B5/no-tenant/B6 on the same five frozen E5 traces, randomized
with seed 20261006. Each has 600 arrival seconds plus 180 drain seconds.
Actual SLO-KEDA/HPA controls 2–4 replicas, with scale-down disabled per run.
The independently measured batch4096 cold-start training P90 is mandatory.
No natural oracle is claimed; Oracle is only the controlled subphase above.

This executor requires all 25 unique dispatch-valid controlled E7 cells and
restoration, plus the exclusive lock, E2 threshold, admission calibration and
qualified mixed capacity. It audits live policy decisions and preserves raw
scaler identities/status/events. No scale-out observed and readiness censored
remain valid scientific classifications; never force a scale-out to obtain a gap.

Thirty-two targeted tests passed including frozen trace validation, prerequisite
uniqueness/restoration, held-lock refusal, live gateway auditing, policy branches,
scaler evidence and gap classification. Once controlled E7 ends, archive/push its
raw evidence, confirm restoration/process exit/lock release, then deploy the new
module, frozen plan and updated `revision_e3.py` with a guarded runtime transfer.
Launch once with `python3 -m crossscale.revision_e7_natural --execute` from
`/tmp/experiments`. This prepared code is not evidence of a started/completed run.

## Preserved startup failure and prospective continuation

At 02:50:55 UTC October 3, the second cell (seed 874, Oracle) failed at gateway
startup. The CLI deliberately rejects `oracle-eta` for live use. This guard was
missed by the original controller validation; policy-level tests alone did not
exercise the CLI boundary. No load was dispatched for that cell. Seed 872/B3
completed dispatch-valid. PID 188464 is still restoring and terminating owned
added instances; do not change its runtime or launch another controller yet.

The correction uses live-supported B6 with externally supplied scheduled-release
ETA, as E6 already did. Oracle remains the recorded variant, and its ETA remains
identical to CrossScale's nominal release. The general CLI guard is preserved.
`revision_e7_continuation.py` freezes only the remaining 23 unattempted cells in
`configs/revision-20261003-e7-continuation-plan.json`; it skips both attempted
cells and refuses any different predecessor failure or unexpected measurement.
Neither the completed nor failed cell is rerun. The original destination is
immutable evidence; the continuation writes a distinct destination.

After continuation, report 24 measured cells plus one startup failure, not 25
successful cells. Oracle comparisons have at most four complete pairs; this
attrition amendment is prospective to all remaining cells and must be disclosed.
Natural E7 still plans five complete pairs for its four non-Oracle baselines.
Its prerequisite now accepts the verified 24-cell combined evidence with this
one explicit failure, never silently treating the missing Oracle as passing.

The continuation source is prepared locally only. Wait for original controller
exit and restoration/lock release, archive and push its raw failure evidence,
then deploy changed `revision_e7.py`, new `revision_e7_continuation.py`, and its
frozen plan under a guarded lock. Launch once with
`python3 -m crossscale.revision_e7_continuation --execute`. Preserve existing
`revision-e7-controlled.log`; use a new continuation log and PID file.

Continuation launch verified October 3 after restoration, original PID 188464 Z,
lock release and one original-condition Ready replica. Original failure evidence:
29 files, 24,273,601 bytes, all SHA256-matched against the runner; private S3 and
Git checkpoint `155e199bcf903bd4ff769cce48453c606dbc21e4` verified remotely.
The failed leaf observer gzip required explicit upload because the archiver
skips streams without a leaf completion/error marker; it is now preserved too.
Continuation plan SHA256 is
`4ccf9f2f81d3170ffd9e59ffa88ab85b51a5a65270f01b35afef7697affbe08b`.
PID 188897 holds suite.lock; log `revision-e7-continuation.log`, PID file
`e7-continuation.pid`. Four replicas are provisioning/prewarming; no cells yet.
Only the continuation runtime files were deployed. Natural E7 remains local.

## Natural E7 launched after controlled checkpoint

October 3 around 09:03 UTC: continuation PID 188897 exited (Z), lock was free,
restored.json present, and one original-condition replica Ready. All 23
continuation cells are dispatch-valid. The 443 files (390,844,534 bytes) were
SHA256-matched runner/local after S3 sync and forced mutable-state copies.
Raw checkpoint `268912175ebc79d14a2d2d651a857e059b1b694c` verified on origin/main.
Combined controlled evidence is 24 valid cells and the retained startup failure.

Deployed natural module, frozen plan and updated E3 engine only under free lock.
Prerequisite/plan checks passed remotely, 21 targeted tests passed locally.
Natural E7 PID 192040 holds suite.lock; new destination created, rollout ongoing.
Log `revision-e7-natural.log`, PID file `e7-natural.pid`. Twenty cells remain,
with 600-second arrivals and 180-second drain each plus startup/reset overhead.
Do not change runtime or start another suite while it runs.
