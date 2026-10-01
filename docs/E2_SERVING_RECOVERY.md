# E2 serving recovery — September 27

The user chose to improve serving performance and recalibrate in a separately
documented condition, preserving capacity-normalized E2. Fixed offered loads
are not a substitute for qualified two-GPU capacity. Existing SLOs, workload
distributions, failed evidence, and the active frozen calibration remain intact.

## Diagnosis

The completed one- and two-GPU .01 RPS seed-704 traces contain the same 196 B
requests. Both have 14 TTFT misses and B goodput 182/196 (92.857%), below 95%.
The same request IDs fail: 34, 156, 160, 236, 293, 357, 365, 426, 446, 478,
507, 534, 543 and 608. Their prompts range from 5888 to 10131 tokens. Twelve
arrived with no other measured request still active, as reconstructed from
offered time, TTFT, TPOT and actual output length. That reconstruction is client
evidence, not server queue instrumentation or proof of exclusive GPU activity.
Together with earlier serial diagnostics, this points to long-prompt serving
latency rather than a problem that replica count alone resolves.

Under the original every-seed/every-lower-rate rule, this lowest-rate failure
prevents any point in the existing two-GPU grid from qualifying. Finish the
remaining frozen runs and report that result honestly. Do not rerun seed 704
as a replacement, shorten prompts, relax the SLO, or use the old sparse .005
RPS qualification to launch E2.

## Frozen diagnostic, not a capacity measurement

Plan: `configs/revision-20260912/e2-serving-recovery-plan.json`.
SHA256: `0e92d4d524c2f72a5dabe1d8853dec385007aec5b9f1fe5e44240c83d74cdcda`.
The plan includes SHA256 hashes of both source request files.

On the preserved original GPU, compare in declared order:

1. Batch 4096, eager (diagnostic reference).
2. Batch 8192, eager.
3. Batch 4096, compiled (remove `--enforce-eager`).
4. Batch 8192, compiled.

All other container settings, image, model, precision, context and token corpus
are preserved. Each condition gets three equal warmups, followed by three serial
repetitions of all 14 failed B prompts (original token offsets/output lengths)
and fixed A median, B median, C median and C 16384-token controls. Rotate case
order by repetition as frozen in the executor. Total: 216 diagnostic requests.
Failures and dispatch-invalid evidence stop the diagnostic for inspection;
no silent replacement trial. Rollout timeout is 2400 seconds. Each rollout and
measurement has raw cluster observations; each request has original live-client
timing and response counts. Restoration returns to one original 1024-budget
replica and validates warmup, with a separate restoration record.

These are failure-selected diagnostic cases, not unbiased capacity evidence.
No automatic winning condition or capacity is emitted. Compare per-case TTFT,
TPOT, startup failures and memory feasibility before selecting a candidate.
Larger batches may improve TTFT but worsen decode latency; compilation can add
startup cost and memory demand. These are hypotheses, not promised fixes.
References: [vLLM optimization](https://docs.vllm.ai/en/latest/configuration/optimization/)
and [CUDA graph design](https://github.com/vllm-project/vllm/blob/main/docs/design/cuda_graphs.md).
The installed pinned image's actual behavior must be retained in live evidence.

## Execution handoff

Do not copy changed runtime modules into the active E1 runner. After E1 finishes:

1. Verify all 30 records, complete/restored markers, worker exit, free suite.lock,
   one original GPU, no scaler, and 1024 serving restoration. Archive and push E1.
2. Copy the reviewed `crossscale/revision_recovery.py`, updated `crossscale/live.py`
   (adds explicit trace replay), and frozen plan into the runner. Record the
   deployed source hashes. Do not replace unrelated runtime files.
3. Launch exactly once, with a detached log and PID, from `/tmp/experiments`:

   ```sh
   python -m crossscale.revision_recovery --execute \
     --plan configs/revision-20260912/e2-serving-recovery-plan.json
   ```

   The command acquires suite.lock non-blockingly, verifies full E1 completion
   and restoration, checks frozen source evidence/config, and rejects an existing
   output directory. Output is `revision-20260912/e2-serving-recovery-20260927`.
   Never retry that directory blindly after an error.
4. Inspect all diagnostic outcomes plus restoration. Checkpoint to private S3,
   locally and Git. Select a justified new condition, or diagnose its failures.
5. Before any new capacity outcomes, freeze a separately named one-/two-GPU
   mixed calibration with unchanged SLOs, adequate per-tenant counts, five fixed
   seeds and the same consecutive-rate qualification. Retain the original
   calibration separately. Validate real GPU utilization availability.
6. A changed condition requires its own provisioning/ETA validation and admission
   calibration; old eager-4096 E0 timing must not be silently reused. Only after
   qualified two-GPU capacity exists may E2 use .65x/1.65x rates. Complete the
   revised live KEDA/HPA controller and disjoint scaler training before testing.

As of preparation, no candidate has run and E2 is not unblocked. This recovery
plan is the next authorized work after the active frozen suite, not completion
of E2 or evidence that compilation/larger batches solve the latency floor.

## September 30 infrastructure interruption

The original mixed controller stopped after run 28 (.05 RPS, two GPUs,
seed 703): Kubernetes NodeClaim GET returned HTTP 429, storage reinitializing,
at Unix 1790734291.9062233. The observer stopped; the load completed its frozen
horizon before the observer exception propagated. Preserve its raw requests,
partial observations, observer-error and suite error. It is not a valid complete
measurement and will not be rerun. Runs 1–27 remain complete.

After verified restoration and lock release, `revision_mixed_live` with
`--continue-unstarted` runs only original frozen entries 29–30 in a fresh
`e1-mixed-continuation-20260930` directory. It retains the original frozen plan,
rejects previously attempted remaining runs, and restores the original settings.
A new added GPU is necessary following the failed controller's cleanup; record
this interruption in analysis. No runtime or measurement change is made to
completed runs. The continuation emits no capacity estimate by itself.

The earlier 30-complete-record recovery guard must not be bypassed or supplied
fabricated completion markers. After the two remaining runs, implement a
reviewed terminal-outcome guard accepting the preserved failed run explicitly,
with an honest combined ledger, restoration and archive proof. Existing
lowest-rate failures already preclude qualified capacity; incomplete telemetry
on run 28 cannot improve that conclusion.

## September 30 terminal checkpoint and recovery prerequisite

The continuation completed both untouched frozen entries and restored at Unix
1790773470.4167933 (13:04:30 UTC). Final totals are 29 completed runs and one
preserved observer failure, with no unstarted entries. Run 30 is dispatch-valid
and passes the SLO criterion. Neither one- nor two-GPU mixed capacity qualifies
because the original lowest-rate seed 704 fails tenant B. No failed run was rerun.
Added instance i-0aaa2e019f1f1a9d5 terminated normally; the original GPU remains.

`revision-20260912/e1-mixed-terminal/terminal-ledger.json` accounts for every
frozen entry. Its archive manifest covers 604 files (2,054,688,619 bytes), with
local SHA256 and verified private S3 object sizes, not remote content hashes.
Large observation streams remain in local/private S3 storage; other evidence is
in Git. The old 26-run observation manifest remains a historical checkpoint.

The recovery prerequisite now accepts this explicitly diagnosed terminal path:
canonical frozen-plan identity, original failure/restoration, both continuation
results and subsequent restoration, matching per-run identities, no replacement
of run 28, complete terminal ledger, and unchanged archive hashes for all files.
It still acquires the exclusive lock before checking evidence or mutating the
cluster. Five targeted recovery tests pass, including rejecting missing final
results, altered archived evidence, and fabricated failed-run completion.
This supersedes the earlier requirement for 30 successful completion markers;
it does not qualify capacity or treat the failed observation as valid.

Before launch, the deployed guard detected 14 stale local state.json copies:
S3 sync had retained same-size local versions. Forced S3 downloads corrected
those copies; the manifest was refreshed. The guard then verified every archived
file against the runner, including the full observation streams. Historical
checkpoint bytes remain in Git history. Raw metrics retain their original
trailing whitespace; code/test changes pass diff whitespace checks.

Recovery diagnostic launched September 30 at Unix 1790773917.6969485
(13:11:57 UTC), worker PID 158849, holding suite.lock. Log:
`/tmp/experiments/revision-e2-serving-recovery.log`. The first condition is
batch4096-eager. Source and plan hashes matched local reviewed files before
launch. Inspect diagnostic complete/error and restored markers before another
phase; do not launch this diagnostic again. The terminal evidence checkpoint
is e0decd066bf9143025303f0d1530de87bd426a62, verified on origin/main.

## September 30 diagnostic failure and restored state

The first two conditions each completed 54 serial requests. Among the 42
failure-selected B-tail replays, 4096-eager missed TTFT 42/42 times (range
1.514–2.819 seconds); 8192-eager missed 39/42 (1.478–2.763 seconds).
These diagnostic counts are not capacity estimates or independent workload samples.

4096-compiled failed startup: 32768 context needs 4.0 GiB KV cache but the
runtime reported 3.94 GiB available. Raw startup logs and pod state are retained
in e2-serving-recovery-startup-evidence. The frozen 2400-second timeout expired
at Unix 1790778233.4579518; original 1024 eager settings and warmup restored at
1790778407.2673361. PID 158849 exited and suite.lock is free. The fourth frozen
condition, 8192-compiled, was never attempted. Do not rerun the failed condition
or either completed eager condition. A separately guarded continuation is needed
for the untouched fourth condition, followed by a separately documented memory
configuration diagnostic if required; do not shorten context or relax SLOs.
E2 remains blocked on serving feasibility and qualified two-GPU capacity.

The guarded continuation uses `--continue-unstarted` with the identical frozen
plan and writes to `e2-serving-recovery-20260927-remaining`. It selects only
batch8192-compiled after verifying both complete eager case/repetition sets,
the diagnosed startup timeout, subsequent restoration, startup-only third
condition, and an absent fourth-condition directory. It keeps the same full
context, .90 memory fraction, 2400-second timeout, warmups and 54 serial cases.
The exclusive lock and fresh destination prevent duplicate launch. Six targeted
recovery tests pass; the real preserved evidence selects only the fourth entry.
This is continuation of an untouched condition, not a retry of the failed one.

The untouched 8192-compiled continuation also reached its 2400-second startup
timeout (Unix 1790801533.7617018), then restored one healthy original replica.
Worker 161323 exited and suite.lock is free. Startup logs show 3.87 GiB KV cache
available versus 4.0 GiB required for full context. All four original conditions
are now accounted for: two completed eager trials, two compiled startup failures.
No compiled latency or capacity result exists. Preserve both error/restoration
pairs and do not rerun either failed condition under its original identity.
The next serving hypothesis is a separately frozen compiled condition with a
larger GPU memory fraction, retaining context, precision, workloads and SLOs;
startup feasibility and actual replay outcomes must precede capacity calibration.

## Frozen memory diagnostic, September 30

Plan: configs/revision-20260912/e2-serving-memory-plan.json, SHA256
8fb913127030f3bcf0d1bcc08e38e36797679cf5c46fc691af4041186318cfc6.
New phase e2-serving-memory-20260930 tests compiled batch4096 then batch8192,
with gpu-memory-utilization 0.95 instead of 0.90. This reserves more GPU memory
for serving after both original compiled settings failed KV-cache feasibility.
It is a hypothesis, not a guaranteed startup or latency fix. All other settings,
full 32768 context, precision, source cases, three repetitions, warmups and SLOs
remain unchanged. Total 108 diagnostic requests if both conditions start.
Retain failures; do not infer capacity from these failure-selected cases.

Run revision_recovery with --execute --memory-recovery and the new plan only
after both prior error/restoration pairs are verified and suite.lock is free.
The executor checks the frozen plan against source evidence, acquires the lock,
rejects an existing destination, observes rollouts, and restores original 1024
settings plus warmup. Eight targeted tests pass. Memory fraction .95 reduces
unreserved headroom, so retain actual startup/memory failure evidence and stop
on the first failed condition without silently substituting a new setting.

## Memory diagnostic completed, September 30

Both .95 compiled conditions completed 54 requests each and restored at Unix
1790805139.361672. PID 161648 exited with the lock released; one original GPU
replica is healthy. Increasing the memory fraction solved startup feasibility,
but did not materially improve the selected B-tail latency: batch4096 missed
TTFT 42/42 times (1.517–2.822s), batch8192 missed 39/42 (1.480–2.766s).
These values are similar to the eager diagnostic and do not justify treating
compilation as a latency fix or launching another lengthy capacity calibration.
All 108 request records and observations are preserved. E2 remains blocked;
further serving diagnosis needs a different performance hypothesis, while
retaining model/context/workload/SLO comparability and all negative evidence.

## Prefill-floor infeasibility, September 30

A further 16384-token batch or another compile trial is not protocol-legal
on this evidence. Serial 8192-eager B-tails (repetition 0) prefill at about
3900–4000 tok/s on the original g5.xlarge A10G. Tenant B's 1.5 s TTFT SLO
therefore covers about 5900–6000 tokens. The failed seed-704 prompts reach
5888–10131 tokens; 13 of 14 already fit in one 8192-token engine step (12 of
13 SLO misses), so a larger `max-num-batched-tokens` cannot remove their
prefill work. The remaining
10131-token prompt would still need about 2.5 s of prefill at the measured
rate. Compilation at `.95` GPU memory started but matched eager TTFT. Admission
calibration already recorded 8192-token TTFT above 2 s.

Do not launch another serving diagnostic, rerun seed 704, shorten prompts,
relax SLOs, change GPU/model/precision, or substitute isolated/.005 RPS
qualifications. The mixed terminal ledger remains 29 completed, 1 failed
observer interruption (run 28), 0 unstarted, and `qualified_capacity` 1 and 2
are both null. Capacity-normalized E2 therefore cannot start.

## Observer 429 retries and E2 execute gate

`Cluster.request` now retries Kubernetes GET/PATCH on HTTP 429/502/503 for up
to 120 seconds, honoring `Retry-After` and `retryAfterSeconds`. That is the
failure that killed mixed run 28 (`storage is (re)initializing`). Persistent
429s still fail the observer after the budget. Run 28 remains archived; it is
not rerun. Copied onto the runner (lock free, no live controller; archive PID 42
only) on September 30:

- `crossscale/cluster.py` SHA256 `5484155558b07a47d1256dabf158d3b1db5210213b7d35b99160b54f0d14119d`
- `crossscale/revision_e2.py` SHA256 `285cf9db97e05bc97c159a0913df292f4c061c2ba27ac8e4725fcafa11483fce`

`python -m crossscale.revision_e2 --execute` acquires the exclusive lock and
refuses unless two-GPU mixed capacity is qualified. The live B2/B3 controller
is still unimplemented; a passed capacity gate records that fact rather than
inventing rates. Inspect prefill infeasibility with
`python -m crossscale.revision_e2 --root results/full-experiments-20260908/run`.

## Suite blocked at E2–E8, September 30

E2 execute was run once on the idle runner and refused. `suite.lock` is free and
`revision-20260912/e2-b2-b3` was not created. Original serving is one Ready
1024-budget eager replica on `crossscale-gpu-2kh95`; no scaler is installed.
Archive PID 42 continues. E3–E8 share the unqualified mixed-capacity input
and also lack live controllers/frozen plans. E6/E7 cannot use live `oracle-eta`.
Do not launch historical `study.py` comparisons. Record
`revision-20260912/suite-blocked.json`; it is a blocker ledger, not completion
of E2–E8. Cleanup waits for an explicit amendment or a finished suite.

## Protocol amendment, September 30

[PROTOCOL_AMENDMENT_20260930.md](PROTOCOL_AMENDMENT_20260930.md) changes only
tenant B TTFT 1.5s → 3.0s and requalifies existing traces. Mixed two-GPU
capacity under the new named condition is 0.025 RPS. Original 1.5s mixed
ledger remains null. E2 B2/B3 is running under exclusive `suite.lock`
(PID 163681, dest `revision-20260912/e2-b2-b3`). Offered loads are 0.01625
and 0.04125 RPS.

## E3 waiter, September 30

E3 priority trio B3/B5/B6 is frozen before outcomes. Seeds **821, 822, 824,
826, 828**; randomized 15-run order; practical effect 0.05; admission
`revision-20260912` with calibrated `slots_per_replica=1` and
`prefill_tokens_s=3305.82`. B2/B4 are not in this launch. The waiter
(`e3-waiter.pid`) polls E2 and does not take `suite.lock` until execute.
It starts only after E2 `complete.json` and `restored.json`, and refuses if
E2 has `error.json` without `complete.json`. Plan SHA
`58ecbb11962108a71346dd9a16134829d268ccbf6cbcc74853aed6b239f44921`.

## E2 deployment mismatch, September 30 23:23 UTC

E2 PID 163681 failed before creating the first measurement folder: runner
Observer lacked capture_scaler. Only frozen-plan, deployment-before/trial,
error and restored files exist; no training/evaluation requests were dispatched.
The cluster restored one Ready original-condition replica and released the lock.
The E3 waiter stopped with 'E2 failed; E3 not started'. Preserve both failures.

The tested repository episodes.py is now deployed while idle; its signature
includes capture_scaler=False. Three observer tests passed. Deployed SHA256:
aabf29dab6d936087a4006ef338c0bbf7f56ec51716e138131363a1af2237033.
A guarded fresh-destination continuation is still needed; do not delete the
failed E2 directory or restart the old E3 waiter blindly.

E2 continuation now uses e2-b2-b3-continuation-20260930. Its mandatory guard
requires exactly the five premeasurement artifacts in the failed directory,
the exact Observer TypeError, matching frozen plan and later restoration.
It refuses any attempted measurement evidence and checks capture_scaler support
before cluster work. The E3 controller imports this new E2 destination, so its
next waiter must follow the continuation rather than the preserved failure.
E2's nine and E3's eight targeted tests pass. Existing failed attempts stay intact.

## E2 continuation completed, October 1

The continuation finished six training and ten evaluation runs; all ten
evaluations are dispatch-valid. Training selected SLO threshold 0.8. Completion
and restoration markers are present, PID 164223 exited, suite.lock is free,
and the original replica is Ready in the 1024 serving condition. Raw evidence
is retained under e2-b2-b3-continuation-20260930 and mirrored from private S3.
This records execution completion; actual scale-out, censoring and comparative
SLO results still require analysis, and must not be inferred from run markers.
The frozen E3 trio can now execute against this continuation's tuning record.

## Priority E3 execution completed, October 1

All 15 frozen B3/B5/B6 runs completed and are dispatch-valid. Completion and
restoration records are present; PID 166231 exited, suite.lock is free and
one original-condition replica is Ready. The added baseline instance
 i-01e9666c2d77fe60c terminated normally. Raw requests, observations, gateway
logs and telemetry are archived under e3-b3-b5-b6 and mirrored locally.
The paired go/no-go and provisioning-gap analysis remain pending. Completion
alone does not support the desired baseline ordering or ETA benefit. E3 B2/B4
and E4–E8 remain unrun and must continue after the priority analysis checkpoint.
