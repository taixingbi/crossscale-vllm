# E8 long trace — frozen October 3, 2026

Plan `configs/revision-20261003-e8-plan.json`, SHA256
`6ab0a276e52bf6c7552ec53a752d6e8dceb8e14791174e1e16cd95b9943469bb`.
Five prespecified seeds 901–905, four baselines B2/B3/B5/B6, twenty paired cells,
randomized with seed 20261007. Explicit token-ID workload traces are frozen
before outcomes and checked by hash and against declared generation.

Each cell offers one hour of arrivals plus 180 seconds of drain. Six consecutive
600-second phases: low (.65 of measured .025 mixed RPS), burst (1.65), recovery
(low), RAG-heavy (low A/B with C fourfold), burst (1.65), low. Tenant prompt/output
distributions remain unchanged. B TTFT 3s amendment, batch4096, calibrated one
slot per Ready GPU and independent cold E0 P90 ETA remain explicit conditions.

Actual KEDA/HPA controls 2–4 replicas. Unlike prior phases, HPA scale-down is
allowed: 60-second stabilization, at most one pod each 60 seconds. Thresholds
remain E2's frozen SLO threshold and B2 queue target 5. Missing SLO metrics are
not zero; a lack of scale-down or oscillation is reported, not forced away.
No outcome-dependent tuning is allowed.

**Infrastructure limitation:** NodePool automatic disruption stays disabled to
preserve original-cluster protections. An HPA pod scale-down therefore does not
terminate idle GPU EC2 instances during a run. Count them as allocated, never
report a pod-hour reduction as node cost savings. Empty owned nodes are cleaned
normally between runs and at restoration. This measures the existing development
cluster retention policy, not an optimized production node scale-down policy.

The observer records actual EC2 IDs, launch times, states and read windows every
15 seconds, including idle allocated nodes. Kubernetes/HPA/ScaledObject evidence
and admission decision audit continue every observation. Read windows and reused
EC2 samples remain explicit. Cost analysis must integrate lifecycle intervals,
report observation bounds and separate startup/reset from arrival+drain costs.
Verified public Linux on-demand prices yield a compute-cost estimate, not an
invoice. Discounts, EBS/network/EKS charges and invoice availability must be
stated separately. Do not call Ready-time GPU-hours billed usage.

Primary output: all-offered weighted SLO goodput, allocated GPU-hours and an
observed cost–SLO frontier. Secondary: cost per SLO-success, scale-outs, scale-downs
and direction reversals, A goodput, P99 latency, actual delay/reject actions,
utilization/tokens. Paired seed bootstrap 10,000 samples, seed 20261007,
practical goodput difference .05. Analyze each phase and both bursts; the shared
engine's first-burst summary alone is not the full E8 analysis. No interpolation
is an empirically established optimum.

Requires all 20 unique valid natural E7 cells, restoration and free suite.lock;
new destination `revision-20260912/e8-long-trace` refuses overwrite. Twenty-two
targeted tests passed including explicit trace pairing, EC2 idle-node accounting,
Ready slot separation, owned scale-down patch, lock guard and existing gateway/
observer behavior. Launch only after source/plan push and remote validation.
Expected minimum measured duration 21 hours plus rollout, per-run warmups and
ownership-aware cleanup. All errors/censoring remain evidence; no failed reruns.
