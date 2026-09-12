# Full live experiment execution protocol

**2026-09-12 execution revision:** Read [POST_E0_EXECUTION.md](POST_E0_EXECUTION.md)
first for current E1–E8 numbering, E0 → E1 → E2 → E3 priority and the E3 stop
checkpoint. It supersedes conflicting continuation instructions below; the
historical protocol and evidence remain intact.

Recorded before collecting the full-workload E0/E1/E2 measurements. The earlier
short-context pilot and profile remain separate evidence.

## Serving condition

Llama 3.1 8B Instruct, pinned image/model snapshot, g5.xlarge, one GPU per replica,
32,768-token context, eager execution, four concurrent sequences, chunked prefill
with a 1,024-token batch limit, and prefix caching disabled. The full tenant
length distributions and SLOs are those in configs/default.json. Readiness and
an actual long-prompt completion must pass before data collection. Any serving
change after this point starts a separately named condition.

## E0

Thirty independent 2-to-4-replica episodes per cache condition. Conditions are
cached-on-existing-node, cold-new-node, and prebaked-image-new-node. The latter
requires a separately prepared AMI with the pinned container images; it must not
be represented by an ordinary cold node. Model cache contents and image-cache
conditions are recorded separately. Baseline two replicas are retained during
each reset. Only empty experiment GPU NodeClaims may be terminated. The next
cold episode waits for the previous added EC2 instances to terminate.

Observation begins before scale-out. Raw Pod/Node/NodeClaim objects, workload
replica changes, EC2 IDs and timing, failures, and censored episodes are retained.
Each episode has a 2,400-second readiness timeout. First 20 episodes train the
ETA; last 10 are held out. Failures are never silently discarded or retried as
replacement samples. An infrastructure failure is diagnosed before continuing.

## Profiling and feasibility

Profile the full workload with one fixed replica, no admission/scaler, six or
more rates, three seeds, and at least a 180-second arrival horizon per run.
Every tenant must reach 95% SLO goodput in every seed for a rate to qualify;
every lower tested rate must pass too. If no point passes, extend the range
downward with longer runs to obtain tenant samples; do not substitute the
short-context 0.2 RPS result. Measure prefill rate and safe admission concurrency
separately, and verify two-replica scaling before generating an experiment trace.
Maximum client dispatch lag above 50 ms invalidates a run, with its data retained.

## E1 and E2

Before E1/E2, tune the common SLO scaler threshold over 0.8/1.0/1.2 using
training seeds 501 and 502; maximize mean weighted goodput, breaking ties in
favor of 1.0. Keep the queue baseline target at 5. Choose the first five seeds
from 101 onward with nonempty offered samples for every tenant, before any
baseline outcomes are collected; retain the examined seeds and sample counts.
This conditions the Poisson traces on nonempty tenant samples and must be
reported as a limitation. Use the selected threshold for every SLO-based loop.

E1: queue-KEDA and SLO-KEDA, five paired seeds, 300-second normal/burst/recovery
traces. E2: B0 through B6 plus ready-only, five independent paired seeds,
execution order randomized with seed 20260908. All use the same gateway, trace,
serving settings, warmup, HPA settings, scrape interval, and maximum four GPUs.
No scale-down runs during measurement. Single-replica capacities are not assumed
to scale linearly. Collect observer state through the drain window and export
Prometheus data, configuration, all requests, and complete run metadata.

Add a matched-scale-schedule B3/ready-only/B6 comparison using a fixed schedule
recorded independently of the paired test results. Do not describe E2 without
this comparison as a complete causal isolation of coordination.

## Predeclared continuation gate

Continue to E3–E7 only when B6 improves mean run-level weighted goodput by at
least 0.05 over both B3 and ready-only, with paired bootstrap 95% confidence
interval lower bounds above zero. Require tenant C goodput at least 0.50 and
rejection fraction at most 0.50 in every B6 repetition. Report both whole-run
and burst-cohort results. Failure of the gate means retaining the negative
result and marking E3–E7 as not triggered, not completed experiments.

## Sources and operational rules

Use Karpenter's normal NodeClaim termination path and preserve finalizers:
https://karpenter.sh/docs/concepts/disruption/ . Chunked prefill changes the
prefill/decode scheduling tradeoff, so pin and report its token budget:
https://docs.vllm.ai/en/stable/configuration/optimization/ . No unrelated
resources are deleted. Raw data is checkpointed after every completed episode.

## Client timing correction and extended profile, 2026-09-10

The initial 27 profile runs are retained, including six dispatch-invalid runs.
A diagnostic repeat of 0.025 RPS seed 18 with a separate client process still
showed 96 ms lag. Bounding client waits to 100 ms reduced maximum lag to 1.4 ms
on the same trace, with all tenant SLOs passing. No SLO or validity threshold
is relaxed. This supports the timer-wait correction; it does not establish a
particular kernel cause or a sustainable capacity.

Before new outcomes, the corrected one-GPU profile is fixed at rates 0.01,
0.015, 0.02, 0.025, 0.05 and 0.075 RPS, seeds 17/18/19, 1800 seconds per run.
All tenant sample counts are checked before measurement. The lower range and
longer horizon address low-rate overlap and sparse samples; small tenant
samples remain a limitation. Every rate and lower tested rate in this corrected
series must pass all seeds. Initial results remain separately reported.
The corrected profile directories end in -bounded. Subsequent experiments use
the same corrected client, unchanged serving settings and original gates.

## Separate 4096-token serving profile, 2026-09-10

After preserved 1024-condition feasibility failures and serial diagnostics,
a separately named 4096-token batch-budget condition is profiled. Other serving
settings, workload, SLOs and dispatch validity remain unchanged. Before outcomes:
rates .01/.015/.02/.025/.05/.075 RPS, seeds 17/18/19, 1800-second horizons.
The same every-seed/every-lower-rate qualification applies. Results go to
profile-one-prefill4096; original serving budget is restored afterward.
This is exploratory condition selection, not a replacement for original results.
No E1/E2 automatically starts: capacity and condition-specific E0/ETA evidence
must be established first. Original 1024-condition E0 is not relabeled or pooled.

## Separate 4096 two-GPU profile, 2026-09-11

After one-GPU qualification at 0.01 RPS, test two replicas at 0.013, 0.02,
and 0.025 RPS (1.3/2/2.5 times measured one-GPU capacity), seeds 17/18/19.
Before outcomes, extend each arrival horizon to 1800 seconds to sample every
tenant at these low rates. Keep all SLO/dispatch/consecutive-rate rules.
If none qualifies, diagnose before a separately recorded lower-range extension.
Restore one original-condition replica afterward. E0/ETA remains separate.

## Lower-range two-GPU 4096 extension, 2026-09-11

The initial nine runs all dispatch-valid but no rate qualified. Serial replay
of the two lowest-rate B tail misses failed all three repetitions even alone;
lower traffic cannot remove these individual service-time misses. To complete
the lower-range feasibility check, predeclare .005/.008/.01 RPS, seeds
17/18/19, 3600-second horizons; every tenant has offered samples in all nine
traces. Retain the same SLO, dispatch and consecutive-rate criteria.
Output profile-two-low-prefill4096; no prior samples overwritten or pooled
as replacement runs. If none qualifies, record full-workload feasibility
failure and E1/E2 as not run; the E3–E7 gate is unevaluated. Do not keep
searching smaller rates for favorable sparse samples.

## Separate 4096-condition E0, 2026-09-11

The lower two-GPU extension qualified .005 RPS with three passing seeds;
.008 and .01 fail seed 17. This is below the one-GPU .01 RPS qualification
and has only 1–3 tenant C samples per passing seed. It does not demonstrate
positive scaling. Preserve the observed rates without assuming linear scaling.
Before comparisons, collect 30 new E0 episodes in each original cache condition
under the 4096 batch budget, with all other serving settings unchanged.
Use the same 2400-second deadline and first-20/last-10 split. Store under
e0-prefill4096, including new prebake proof and raw observations. Original E0
remains separate; no old timing sample is used to train the new-condition ETA.
