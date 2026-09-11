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
