# E4 frozen live plan — October 1, 2026

Prepared before E4 outcomes while the E3 extension remains active. This is
implementation and a frozen plan, **not completed measurement**. Do not deploy
the changed shared controller into the active runner until E3 finishes, restores,
exits, and releases `suite.lock`.

`configs/revision-20261001-e4-plan.json` fixes five seeds 841–845 and randomized
B3/B5/B6 order (15 runs). Each run has 1,800 seconds of arrivals and 180 seconds
of drain, two initial GPUs, four maximum, and the unchanged 4096 eager serving
condition with September 30 B TTFT 3s amendment. Use E2's frozen SLO threshold
and the measured admission calibration. No new threshold tuning.

The baseline total offered rate is 65% of measured two-GPU mixed capacity
0.025 RPS, apportioned A:B:C = 4:2:1. A and B stay constant throughout.
Only C increases fourfold between 600 and 1,200 seconds and then returns to its
baseline rate. All baseline variants use identical request IDs, lengths, and
arrival times per seed; the plan includes trace hashes and offered counts.
Seeds are fixed without selection on outcomes. Low request counts remain a
limitation. A noisy-neighbor arrival burst need not cause queueing or scale-out.

Primary outcome is A SLO goodput over all offered A requests. Secondary outcomes
are C SLO goodput, C rejection/defer fractions, P99 TTFT, weighted goodput,
GPU utilization, and tokens/s. Report whole-run and burst cohorts, paired
B6-B5, B5-B3, and B6-B3 differences with 10,000 paired seed bootstrap samples
(seed 20261002), and a 0.05 practical goodput difference. Missing telemetry or
empty cohorts remain unavailable. Before/burst comparisons are descriptive;
they are not a randomized control for a causal effect of tenant C.

`python3 -m crossscale.revision_e4 --plan configs/revision-20261001-e4-plan.json`
requires both E3 groups complete, dispatch-valid, and restored, plus exclusive
suite lock and a fresh output directory. It preserves failures and uses the
existing live controller, actual KEDA/HPA decisions, observer, telemetry, and
restoration. Never launch a second controller or replace a failed run.

Validation: 11 E3/E4 unit tests pass, covering paired workload invariance,
C-only rate change, admission revision, active lock exclusion, and incomplete
or invalid predecessor rejection. Live validation and deployment remain pending
E3 completion. Minimum measured wall time is 8.25 hours plus setup and cleanup.

Launched October 1 after E3 extension checkpoint `24594ab` was pushed and
verified remotely. All 25 E3 runs are dispatch-valid; prior worker exited and
restored the original replica. E4 controller PID 169391 holds suite.lock,
log `/tmp/experiments/revision-e4.log`, output `revision-20260912/e4-noisy-neighbor`.
Deployed shared-controller/module/plan hashes match the local committed files;
plan SHA256 is d0cade969661299c026db2bf07df3ad49bbee862eef30040b83c3c7fa79ad7f5.
Startup begins by applying the trial serving configuration. E4 measurement
completion and restoration are pending; no later phase starts automatically.
