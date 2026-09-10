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
