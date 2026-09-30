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
