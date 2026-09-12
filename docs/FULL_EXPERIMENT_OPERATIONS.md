# Full experiment operations

**Current continuation scope (2026-09-12):** Follow
[POST_E0_EXECUTION.md](POST_E0_EXECUTION.md) after the active E0 finishes.
Run new E1 capacity profiling, E2 B2/B3, then priority E3 B3/B5/B6; stop
expansion at E3 and report the evidence. Do not automatically run E4–E8 or use
the historical numbering/gate to skip the new E3 comparison.

Started 2026-09-08. This is a live, unfinished measurement suite. Do not confuse
the earlier short-context results with these full-workload measurements.
The scientific contract is in FULL_EXPERIMENT_PROTOCOL.md.

## Scope and current workers

Repository: `/Users/h/Desktop/paper/paper11-Crossscale-Vllm/crossscale-vllm`.
AWS account `646821141010`, region `us-east-1`, EKS cluster `crossscale`.
Always use kubeconfig `/tmp/crossscale-continuation-kubeconfig`; the default
context points at a different, stale cluster. Namespace `crossscale`, GPU
NodePool `crossscale-gpu`, deployment `vllm`. Maximum four g5.xlarge GPUs.
Do not change CPU nodes or unrelated resources.

Pod `crossscale-experiment-runner` runs the controller on a CPU node. Its
working directory is `/tmp/experiments`. At initial launch:

- Cached E0 worker PID 65, `e0-cached.log`, `cached.pid`.
- Remaining suite PID 140, `study.log`, `study.pid`, `status.json`.
- S3 archiver PID 141, `archive.log`, `archive.pid`, `archive-status.json`.

Inspect PID files and `/proc/<pid>/stat` rather than trusting these historical
PIDs. Zombie processes are not running. The suite has an exclusive `suite.lock`.
Never launch a duplicate controller. The suite waits for cached E0, then runs
cold E0, prebaked E0, full profiling, admission calibration, threshold tuning,
E1, E2 and matched-scale comparisons. The predeclared gate determines E3–E7.
`requires-E3-E7` needs further implementation and measurements; it is not done.
`measurement-suite-finished` still requires analysis and external cleanup.
`needs-diagnosis` requires inspection, not an automatic restart.

The pod's initial sleep lifetime is 48 hours from approximately 22:56 UTC Sep 8.
Inspect its remaining lifetime if work takes longer. Artifacts are checkpointed
to private S3 every minute, including closed observation streams. No credentials
are stored in the experiment directory. Check archive status for errors.

## Inspect and recover evidence

```sh
kubectl --kubeconfig /tmp/crossscale-continuation-kubeconfig -n crossscale get pods -o wide
kubectl --kubeconfig /tmp/crossscale-continuation-kubeconfig -n crossscale exec crossscale-experiment-runner -- cat /tmp/experiments/progress.json /tmp/experiments/archive-status.json
kubectl --kubeconfig /tmp/crossscale-continuation-kubeconfig -n crossscale exec crossscale-experiment-runner -- tail -n 20 /tmp/experiments/study.log
aws s3 sync s3://crossscale-experiment-results-646821141010-us-east-1/full-20260908/ results/full-experiments-20260908/run/ --region us-east-1 --only-show-errors
```

Completed episode directories have `summary.json`; load runs have `complete.json`.
`progress.json` refreshes every minute with actual E0 counts, latest event and
worker state. The older `status.json` only updates at top-level study events and
can show an old phase while nested E0 measurements proceed; use progress/logs.
Never erase a failed/partial directory or silently replace a failed seed.
Preserve the error and classify the observation as censored/invalid before a
diagnosed continuation. E0 ETA uses only the first 20 training episodes.
The final controller source manifest and bundle are under the local preflight
directory. Cached E0 was launched before the later EC2 lifecycle recorder and
prebaked verification additions; its scale/readiness measurement logic is the
same. Its completed raw Kubernetes observations remain the source of truth.

The initial GPU claim is `crossscale-gpu-2kh95`, EC2 `i-063f58e1698afc010`,
node `ip-10-42-9-196.ec2.internal`. Preserve it. The ownership file records
the initial claim and task-added claims. Cleanup only permits owned claims with
no non-DaemonSet live workloads and waits for actual EC2 termination. Never
remove Karpenter finalizers. A newly encountered unrelated workload blocks cleanup.

## Prebaked image

Dedicated unjoined builder: `i-0ac6a7cc78eff3d9e`, root volume
`vol-07e11ba9e4116d953` (delete on termination). It shut itself down after
pulling the pinned container images. AMI `ami-006c1eb16c0aa3517`, snapshot
`snap-069b9afd24f88a76e`, custom NodeClass `crossscale-gpu-prebaked`.
Wait until the AMI is available before terminating this stopped builder.
The suite verifies the bake marker and pinned image inventory on a newly
provisioned proof pod before collecting prebaked E0. A pending AMI is not proof
of a valid bake. Preserve failure evidence if the proof fails.

## Finish and scoped cleanup

After eligible measurements and reporting, retain one healthy full-context
vLLM replica on the original GPU and confirm a real inference response. Restore
NodePool limit `nvidia.com/gpu: 1` and reference to NodeClass `crossscale-gpu`.
The suite normally reduces to one itself; confirm rather than assuming.

Retain local and private S3 result evidence. Remove only these temporary items,
after checking they are no longer used:

- Owned empty GPU NodeClaims, using normal Karpenter deletion and confirmed
  EC2 termination. Do not delete the original claim.
- ScaledObject `vllm` only if labeled `crossscale-experiment=full-20260908`.
- The `crossscale-gateway` scrape job in monitoring secret
  `monitoring-kube-prometheus-prometheus-scrape-confg`, key
  `additional-scrape-configs.yaml`. Saved original is in preflight. Preserve any
  other subsequent scrape changes; remove just the task's job/target.
- Proof pod, runner pod/service account, `crossscale-gateway` service, namespace
  Role/RoleBinding `crossscale-experiment-control`, ClusterRole/Binding
  `crossscale-experiment-observer` from deploy/experiment-runner.yaml.
- EKS Pod Identity association `a-v1ju3aeqnjs5xpivl`; IAM role
  `crossscale-experiment-observer` with inline policies
  `observe-experiment-termination` and `checkpoint-experiment-results`.
- Unused NodeClass `crossscale-gpu-prebaked`, dedicated builder if still present,
  AMI and its recorded snapshot after all associated nodes are terminated.
- Temporary EKS access entry for `arn:aws:iam::646821141010:user/taixingbi`.
  Delete this last, after all Kubernetes work. It was created for this task.

Heartbeat `finish-crossscale-full-experiments` checks this task every 15 minutes.
Pause it once evidence, report, inference validation and scoped cleanup are done.
User authorized phase pushes on 2026-09-09: commit and push each completed
phase, verify the remote commit, then continue. The existing detached controller
advances automatically; checkpoint completed phases at the next heartbeat without
interrupting an active measurement. Preserve the unrelated pre-existing edit in
docs/EXPERIMENT_PLAN.md. Track checkpoints in docs/EXPERIMENT_PUSH_CHECKPOINTS.md.

## Profiling diagnosis, 2026-09-10

Original study PID 140 stopped after 27 initial profile runs; all preserved and
pushed at 22859c8. Six were dispatch-invalid. Idle timing diagnostics found
under 6 ms lag both with and without a shared observer process. A separate
load process repeated 0.025 RPS seed 18: all tenant SLOs passed, but maximum
dispatch lag remained 96 ms. This does not establish observer contention.
The next diagnostic uses client waits capped at 100 ms while retaining the
absolute arrival deadline, measured lag and unchanged 50 ms validity limit.
Serving settings are unchanged. Results are under diagnosis-bounded-wait-load;
script bounded-wait-diagnostic.py, log bounded-wait-diagnostic.log in the runner.
It holds suite.lock and must finish before any continuation. It is diagnostic
evidence, not a replacement sample or measured capacity. Inspect complete.json.
The original study.pid still points to the stopped controller; do not restart
it blindly. Runner sleep expires around 22:56 UTC today.

Bounded-wait diagnostic completed: 1.363 ms maximum lag, all tenant goodput 1.0.
Continuation uses scripts/continue-bounded-profile.py copied to runner root,
nohup with study-bounded.log. It acquires suite.lock and updates study.pid.
The corrected six-rate one-GPU sweep takes approximately nine hours. Inspect
runner lifetime before 22:56 UTC; comparisons may extend beyond that time.
Original E0 and profile directories are not rerun or overwritten.

Corrected profile completed all 18 runs at 19:57 UTC Sep 10. All dispatch-valid;
no sustainable rate. Results checkpoint b9a04e8 verified on origin/main.
Controller 22907 is now a zombie. Do not restart the completed sweep.
At 20:09 UTC, isolated-tail-diagnostic.py was launched under suite.lock, logging
isolated-tail-diagnostic.log and writing diagnosis-isolated-tail. It replays the
two 0.01 RPS TTFT misses (B 5490 tokens and C 16384 tokens) serially, alongside
median-length B/C controls, three repetitions each. It preserves original IDs
and token offsets and does not select capacity. Inspect complete.json before
further serving changes. This diagnostic does not update study.pid.
Runner still expires near 22:56 UTC; safely migrate after diagnostics if needed.

Isolated tail diagnostic completed 12 requests; both tail cases fail TTFT in
all three repetitions while median controls pass. Evidence pushed at 930c0a0.
At 20:27 UTC, prefill-2048-diagnostic.py started under suite.lock, logging
prefill-2048-diagnostic.log. It temporarily changes only the batch token budget
1024 to 2048, repeats the same 12 serial requests, then restores original
container settings and validates warmup. This is a separate diagnostic serving
condition, not a continuation of the frozen 1024-token experiment. Inspect
run/diagnosis-prefill-2048/complete.json AND restored.json; complete.json alone
does not prove restoration. Each rollout has a 1200-second deadline. The script
does not update study.pid; inspect log/process/lock before starting anything.
No E0 data may be silently combined with a changed serving condition.

2048 diagnostic restored the original budget and passed warmup. All 12 requests
completed; B tail now passes TTFT (1.426–1.430s), C tail narrowly fails
(5.022–5.027s). Checkpoint 9f428fa verified remotely. The same isolated diagnostic
with budget 4096 started around 20:44 UTC, log prefill-4096-diagnostic.log,
output diagnosis-prefill-4096. It holds suite.lock and restores 1024 afterward;
check both complete.json and restored.json. Original GPU claim is preserved;
current original-condition pod after restoration is vllm-5b64c7b7d9-bx4zp
(pod name will change again during the next trial). Runner migration is due
before its 22:56 UTC expiry, after this short trial completes.

4096 diagnostic finished and restored 1024 with successful warmup. All 12
requests completed; B tail TTFT about 1.414s, C tail 4.972–4.977s. This is not
a sustainable capacity result. Evidence pushed and verified at c064224.
At 21:00 UTC runner renewal preparation began while suite.lock was confirmed
free. No pod deletion has occurred. Full backup transfer is running in local
exec session 16488 to /tmp/crossscale-runner-renewal.tgz (1.2GiB source); wait
for exit and validate the tar before renewal. Saved original pod is
/tmp/crossscale-runner-old.json; replacement /tmp/crossscale-runner-renewed.json
uses sleep infinity, same image/resources/service account and fresh projected
credentials. Dependency pins saved in /tmp/crossscale-runner-requirements.txt.
After backup validation, recreate only the idle runner, restore /tmp/experiments,
install those pins, remove stale PID files, restart only the S3 archiver and
verify archive status. Do not restart any completed controller or diagnostic.
Runner old sleep expiry remains 22:56 UTC. Original GPU claim stays unchanged.

Runner renewal completed about 21:30 UTC Sep 10. The full tar transfer failed
with a connection reset; it is NOT a usable backup. A validated 281-file runtime
bundle /tmp/crossscale-runner-runtime.tgz restored code, token corpus, configs,
ownership, summaries and completion records into the renewed same-name pod.
Raw observations/requests remain in private S3 and the local run mirror, not
in the renewed runner. Do not treat missing raw files there as missing runs.
Same image and dependency pins were restored. PID1 now sleeps indefinitely;
no 22:56 expiry. Historical PID files moved to historical-pids. Only archiver
PID 42 restarted, log archive-renewed.log. No measurement controller is running.
Original vLLM pod vllm-5b64c7b7d9-gdn8h remains Ready on the original GPU.
Next: assess a separately named 4096-token full-workload profile with unchanged
SLOs; isolated success alone does not authorize treating it as calibrated capacity.
Any changed-condition E0/ETA use must be separately measured and documented.

At about 21:33 UTC the new scripts/profile-prefill4096.py was launched as
profile-prefill4096.py in the renewed runner, log profile-prefill4096.log.
It acquires suite.lock and updates study.pid, rolls to batch budget 4096, runs
18 full-profile repetitions into profile-one-prefill4096, then restores 1024.
Control evidence: profile-prefill4096-control. See protocol amendment. Expect
about nine hours. It does not start comparisons or reuse original E0 as new
condition evidence. Inspect study.pid, log and restoration before any next step.

4096 full profile completed all 18 dispatch-valid runs, qualifying 0.01 RPS.
Original serving settings restored. Evidence checkpoint 01b79f6. Next separate
admission calibration uses scripts/admission-prefill4096.py, output
admission-prefill4096, same predeclared three repetitions of prefill lengths
256/3072/8192 and concurrency 1/2/4 with rotated median tenant requests.
It holds suite.lock and restores 1024 after calibration. No E0 is reused.

4096 admission completed with one slot and 3305.820 prefill tokens/s. Restored
1024 and warmup passed. Next: scripts/profile-two-prefill4096.py, log
profile-two-prefill4096.log, output profile-two-prefill4096 and control sibling.
Three rates .013/.02/.025, seeds 17/18/19, 1800-second horizons, about 4.5 hours
plus provisioning. Holds suite.lock and updates study.pid. Restores one replica
and original budget afterward. Does not start E1/E2 or reuse original E0.

Two-GPU 4096 profile completed all nine dispatch-valid runs, no qualified rate;
raw checkpoint 9153cfb. All six SLO misses are B TTFT on 6014–7578-token
prompts. Added claim crossscale-gpu-gwfqm / i-079bdf9ea55349c8d terminated;
original 1024 settings restored and warmup passed at 11:39 UTC Sep 11.
Next diagnostic scripts/diagnose-two-profile-tail4096.py replays the two
lowest-rate B misses (6841 and 6309 tokens, preserved IDs) plus B median,
three serial repetitions on one 4096 replica, then restores 1024.
Output diagnosis-two-profile-tail4096, log diagnose-two-profile-tail4096.log.
Holds suite.lock and updates study.pid. No capacity replacement or E0 reuse.

Isolated B tail replay completed: 6841-token TTFT about 1.786s, 6309-token
about 1.661s, all three fail even alone; median passes. Raw checkpoint bc8d78c.
Restoration passed. Next scripts/profile-two-low-prefill4096.py, matching
runner filename/log, output profile-two-low-prefill4096 and control sibling.
Nine one-hour runs at .005/.008/.01, seeds 17/18/19; protocol amendment
records terminal feasibility rule. Holds suite.lock, updates study.pid, restores
one original replica and removes only owned added GPU after completion.

Lower two-GPU extension completed all nine dispatch-valid runs; .005 RPS
qualified, higher rates failed. Raw checkpoint 5ece64d verified remotely.
Added claim crossscale-gpu-bbmzq / i-000acd7e754206393 terminated normally.
Next script scripts/e0-prefill4096.py collects separate 4096-serving E0:
30 cached, 30 cold, 30 prebaked episodes. It acquires suite.lock, updates
study.pid, keeps task-wide ownership current, and logs to e0-prefill4096.log.
Output e0-prefill4096; original e0 remains separate. status.json includes
new-condition counts under e0_prefill4096; progress.json's e0 counts continue
to describe ORIGINAL E0, while its latest event identifies the new condition.
On failure it preserves current state and writes error.json; do not blindly
restart (the fresh-start script rejects an existing output directory).
On success it restores one original-condition replica and warmup, recording
restored.json. No comparisons start automatically. Push each cache phase as
its summary appears, without interrupting the controller. Allow roughly two
days for these startup measurements based on original timing evidence.
