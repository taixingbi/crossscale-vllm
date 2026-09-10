# Full experiment operations

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
