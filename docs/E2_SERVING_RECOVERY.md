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
