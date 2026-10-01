# Experiment Git checkpoints

User authorized commits and pushes after each completed phase on 2026-09-09.

## E0 cached-on-existing-node

This checkpoint contains all 30 completed episodes, their closed raw observation
streams, and the condition summary: 20 training, 10 held out, zero failures.
The experiment controller source and protocol are included for reproducibility.
Find the checkpoint commit with `git log --grep="Checkpoint completed cached E0 phase"`.
Cold and prebaked phases remain unfinished and are not included as completed results.

## E0 cold-new-node measurements

All 30 episodes completed with zero measurement failures (20 training, 10 held
out). All closed raw observation streams and episode summaries are checkpointed.
Episode 29 includes AWS insufficient-capacity retries and a measured 2060.989-second
readiness gap; supplementary Karpenter logs and Pod events are preserved.
At this checkpoint, the controller is still performing final node cleanup;
the condition-level summary will be checkpointed after that finishes.
Find this commit with `git log --grep="Checkpoint 30 completed cold-node E0 measurements"`.

Cold-node final cleanup completed; the condition summary confirms 20 training,
10 held-out episodes and zero failures. Training P90 is 1110.118 seconds.
The final summary and remaining EC2 lifecycle records are included in the
`Finalize cold-node E0 phase checkpoint` commit. Prebaked validation is underway.

## E0 prebaked-image-new-node measurements

All 30 episodes completed with zero measurement failures (20 training, 10 held
out). All 30 closed gzip observation streams were fully parsed as JSON and
validated before this checkpoint. The bake verification is included.
Final node cleanup is still running; the condition summary and final lifecycle
records will be checkpointed when available.
Find this commit with `git log --grep="Checkpoint 30 completed prebaked E0 measurements"`.

Prebaked final cleanup completed. The condition summary confirms 20 training,
10 held-out episodes and zero failures; training P90 is 1811.426 seconds.
The final summary and remaining EC2 lifecycle evidence are included in
`Finalize prebaked E0 phase checkpoint`. Full one-GPU profiling has started.

## Initial full one-GPU profile

All 27 runs completed across nine rates and three seeds. No rate qualified
under the predeclared joint tenant-SLO and dispatch-validity requirements.
The controller stopped for diagnosis; no capacity was substituted and E1/E2
have not started. Raw results, telemetry, observer streams and a per-run
validity audit are preserved. An idle observer/event-loop diagnostic is pending.
Find this commit with `git log --grep="Preserve initial full profiling and feasibility diagnosis"`.

## Corrected extended one-GPU profile

All 18 runs completed across six rates and three seeds with 1800-second
arrival horizons. All are dispatch-valid, but no rate qualifies under the
predeclared tenant SLO rule. All JSON and closed gzip streams were parsed.
The controller stopped for diagnosis; E1/E2 have not started.
Find this commit with `git log --grep="Checkpoint corrected full one-GPU profile"`.

## Isolated tail latency diagnostic

All 12 serial requests completed. Both lowest-rate tail requests missed TTFT
in every repetition (B 5490: about 1.57s; C 16384: about 5.49s). Median B/C
controls passed. This is diagnostic evidence, not a capacity estimate.
Find commit with `git log --grep="Checkpoint isolated tail latency diagnosis"`.

## Prefill budget 2048 diagnostic

Twelve serial requests completed. B tail TTFT improved to 1.426–1.430s;
C tail remained above 5s at 5.022–5.027s. Original 1024 budget restored,
Ready and warmup verified. This is separate diagnostic evidence.
Find commit with `git log --grep="Checkpoint 2048-token prefill diagnostic"`.

## Prefill budget 4096 diagnostic

All 12 serial requests completed. B tail TTFT 1.414s and C tail 4.972–4.977s
met their limits in each repetition; controls passed. Capacity is not established.
Original 1024 budget restored and warmup passed.
Find commit with `git log --grep="Checkpoint 4096-token prefill diagnostic"`.

## Separate 4096-token full one-GPU profile

All 18 runs completed; all dispatch-valid. The predeclared consecutive-rate
rule qualifies 0.01 RPS. Higher rates fail at least one seed. All 330 files,
including JSON and closed gzip streams, validated; original 1024 serving
settings restored with Ready and warmup evidence. This exploratory condition
is separate from original E0 and profiling.
Find commit with `git log --grep="Checkpoint full 4096-token one-GPU profile"`.

## Separate 4096 admission calibration

Completed: one slot per replica, empirical prefill throughput 3305.820 tokens/s.
Original serving settings restored; warmup passed. All five JSON files parsed.
Raw evidence commit b512e06.

## Separate 4096-token two-GPU profile

All nine runs completed and dispatch-valid; no tested rate qualified.
All 167 profile/control files validated, including closed gzip streams.
Controller is cleaning up its added GPU before restoring original settings;
restoration evidence will be checkpointed separately when complete.
Find commit with `git log --grep="Checkpoint full 4096-token two-GPU profile"`.

## Two-GPU profile tail diagnosis

Nine serial requests completed; B 6841-token TTFT 1.785–1.787s and
6309-token TTFT 1.660–1.662s fail all three replays without competing
requests. Median B passes. Original settings restored and warmup passed.
Find commit with `git log --grep="Checkpoint isolated two-GPU profile tail diagnosis"`.

## Lower-range 4096-token two-GPU profile

All nine runs completed and dispatch-valid. The consecutive-rate rule qualifies
0.005 RPS; .008 and .01 each fail seed 17. The passing rate has only 1–3
tenant C requests per seed, so capacity is a sparse empirical qualification.
All 167 profile/control files validated, including full closed gzip streams.
Added claim crossscale-gpu-bbmzq / i-000acd7e754206393 terminated normally;
original serving restoration is in progress and will be checkpointed afterward.
Find commit with `git log --grep="Checkpoint lower-range 4096 two-GPU profile"`.

## Separate 4096 cached E0

All 30 cached episodes completed, zero failures; first 20 training and last
10 held out. Training p90 startup gap is 161.014 seconds. All 93 cached
phase and deployment evidence files validated, including full gzip JSONL
streams. Cold-node E0 is running under the existing controller.
Find commit with `git log --grep="Checkpoint separate 4096 cached E0"`.

## Separate 4096 cold E0

All 30 cold-node episodes completed with zero failures; first 20 training and
last 10 held out. Training p90 startup gap is 982.808 seconds. All 90 episode
files validated, including full gzip JSONL streams; the final phase summary
was also parsed and checked. The existing controller verified the prebaked
image and started its first episode without interruption.
Find commit with `git log --grep="Checkpoint separate 4096 cold E0"`.

## Revised E1 isolated preparation — 2026-09-12

Prepared crossscale/revision_e1.py, frozen 90-run isolated A/B/C plan, operational
notes and three passing offline tests. Five fixed seeds per rate, >=60 requests
per active tenant, 85 arrival-hours; no outcome-driven seed replacement.
No runtime source copied, measurement launched or serving state changed.
Mixed calibration and E2/E3 remain subsequent work under POST_E0_EXECUTION.md.

## Separate 4096 prebaked E0 — 2026-09-13

All 30 prebaked episodes completed with zero failures; all 90 condition-specific
E0 episodes are now complete. Training p90 is 1185.753 seconds, with the
first-20/last-10 split preserved. Validated all 651 currently archived E0 files,
including full gzip JSONL observations and lifecycle records. Checkpoint includes
prebake verification and measurement completion. Controller cleanup/restoration
is still active; completion of measurements does not establish restoration.
Find commit with `git log --grep="Checkpoint separate 4096 prebaked E0"`.

## E0 restoration and revised E1 launch — 2026-09-13

E0 restored 1024 with successful warmup, original GPU only; PID exited and
lock released. Checkpoint remaining lifecycle/restoration evidence. Required
vLLM metrics and Prometheus series exist; runtime pins verified. Launched
frozen revised E1 isolated controller PID 35593 with exclusive suite.lock.
Serving rollout and post-rollout telemetry preflight precede measurements.

## Revised isolated E1 completion — 2026-09-17

All 90 frozen runs completed, all dispatch-valid. Highest consecutively passing
tested isolated rates: A .2, B .05, C .01 RPS. These are isolated capacities,
not a mixed capacity or a scaling claim. Completion September 16 18:48:35 UTC;
restoration and inference warmup succeeded afterward. PID 35593 is a zombie,
suite.lock released, original GPU retained and vLLM Ready. Raw evidence synced
from private S3; mixed calibration and E2/E3 remain unfinished.

## Mixed calibration in progress — 2026-09-29

24 of 30 frozen mixed runs are complete and dispatch-valid. One-GPU 0.01 is
4/5, 0.025 is 3/5, 0.05 is 0/5. Two-GPU 0.01 is 4/5 and 0.025 is 3/4 so far.
Seed 704 tenant B is below 95% SLO-goodput at 0.01 on both GPU counts
(182/196, 92.857%), so this grid cannot qualify mixed capacity. The controller
is still running `mixed-gpu-2-rps-0.025-seed-705`; five 0.05 two-GPU seeds
remain. This checkpoint does not include the in-progress run, does not launch
E2, and does not replace the frozen plan. Closed gzip streams are local and in
private S3; Git has the SHA256/size/location manifest plus requests, telemetry
and cluster snapshots. Serving recovery stays blocked until all 30 runs
complete and restore.

## Mixed calibration 26/30 — 2026-09-29 evening

Two more frozen runs completed and remain dispatch-valid: two-GPU 0.025 seed
705 passed (B 0.961) and two-GPU 0.05 seed 701 failed (B 0.949). Two-GPU 0.025
is now 4/5; two-GPU 0.05 is 0/1 so far. The lowest-rate seed-704 B failure is
unchanged, so mixed capacity on this grid remains unqualified. The controller
is still running `mixed-gpu-2-rps-0.05-seed-702`; three 0.05 seeds remain.
The in-progress run is omitted. E2 serving recovery stays blocked until all
30 runs complete and restore.

## Suite blocked at E2–E8 — 2026-09-30

Mixed calibration finished (29 complete, run 28 preserved observer 429). Serving
recovery and the `.95` memory diagnostic completed and restored original 1024
serving. Two-GPU mixed capacity remains null; serial B-tail prefill cannot meet
the 1.5s SLO. Gated E2 execute refused; E3–E8 are also blocked (same capacity
input, missing live controllers, simulation-only oracle). One original GPU is
healthy, `suite.lock` is free, archive PID 42 continues. Ledger:
`results/full-experiments-20260908/run/revision-20260912/suite-blocked.json`.
E2–E8 are not complete. Find commit with
`git log --grep="Record suite blocked at unqualified mixed capacity"`.

## Protocol amendment 3.0s B TTFT — 2026-09-30

Frozen amendment raises only tenant B TTFT to 3.0s and requalifies existing
isolated/mixed traces. Original 1.5s mixed capacity stays null. Amended mixed
capacity is 0.025 RPS on one and two GPUs; E2 .65×/.165× totals are 0.01625 and
0.04125 RPS. Seed 704 was not rerun. E2 was not launched. Ledgers:
`results/full-experiments-20260908/run/revision-20260930/`. Find commit with
`git log --grep="Amend B TTFT to 3s and requalify existing mixed traces"`.

## E2 B2/B3 launched — 2026-09-30

Capacity-normalized E2 is running once under exclusive `suite.lock`, PID
163681, dest `revision-20260912/e2-b2-b3`. Frozen plan SHA `c3654b35…`.
Training seeds 802/803; eval 811/812/813/816/818. Serving rolled to 4096.
Do not launch a duplicate. Find commit with
`git log --grep="Launch capacity-normalized E2 B2/B3"`.

## E3 B3/B5/B6 waiter armed — 2026-09-30

Priority trio frozen before outcomes (seeds 821/822/824/826/828, practical
effect 0.05, Ready-slot admission, slots=1). Waiter polls E2 complete+restore
and will not start from a failed-only E2 error. B2/B4 stay for a later
checkpoint. Find commit with
`git log --grep="Freeze E3 B3/B5/B6 and wait for E2"`.

## E3 B2/B4 complete — October 1, 2026

All ten extension runs completed and are dispatch-valid; total E3 coverage is
25 runs across B2/B3/B4/B5/B6. Complete/restored records verified, PID 168098
exited, and suite.lock released. Original GPU replica is Ready; added instance
i-079a94ab0d0001c80 terminated normally. Private S3 mirrored locally and all
247 phase files (62,973,217 bytes) match the runner's SHA256 hashes, including
forced refresh of mutable state files. Raw evidence is committed with this
entry. Priority negative comparison remains unchanged; combined analysis and
secondary outcomes remain pending. E4 plan/controller were frozen at 62c7983;
E4 is the next phase, not yet a completed experiment.

## E4 complete — October 1, 2026

All 15 frozen B3/B5/B6 noisy-neighbor runs completed and are dispatch-valid.
Complete/restored records are present; PID 169391 exited and suite.lock is free.
One original-condition replica is Ready on the original GPU. Owned added GPU
instances terminated normally. All 367 phase files (424,518,290 bytes) were
mirrored from private S3 and match runner SHA256 hashes; mutable state files
were explicitly refreshed. Raw observations, requests, telemetry, plans, and
restoration are checkpointed with this entry. Outcome analysis remains pending.
E5–E8 remain unrun. E5 requires implementation and live validation of controlled
usable-capacity delay; natural provisioning observations cannot substitute for
its 0/15/30/60/90/120-second controlled conditions.

## E6 ETA-error waiter armed — 2026-10-01

E5 is the live controller. E6 is frozen on E5 traces, lag 60s, seven variants
(no-ETA, ±50/±25/0, scheduled oracle), 35 runs. Waiter polls E5
complete+restore and will not start from a failed-only E5 error. Find commit
with `git log --grep="Freeze E6 ETA-error and wait for E5"`.
