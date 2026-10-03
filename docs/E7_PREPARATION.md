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
