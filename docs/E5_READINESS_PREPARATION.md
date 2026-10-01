# E5 readiness capability preparation

E5–E8 are not run. E4 completed and restored at checkpoint 22dd24a. The new
readiness_gate helper is an offline-tested building block, not live validation
or a frozen measurement plan.

Proposed controlled condition uses four prewarmed model replicas with a custom
Kubernetes readiness gate. Two baseline pod UIDs are released; two remain
excluded from Service routing until a predeclared release time. This isolates
controlled usable-capacity delay from natural instance/model startup. Report
prewarmed resource cost separately and do not call the resulting schedule a
natural KEDA provisioning decision. A replaced pod UID aborts the condition.

Before any measured run: validate custom-condition status patch permission,
optimistic resource-version conflicts, preservation of existing health
conditions, actual Ready transitions, EndpointSlice membership, and real HTTP
routing exclusion/release. Validate all six delays (0/15/30/60/90/120 seconds),
record requested and observed times, and predeclare acceptable timing tolerance.
No claim of exact delay from a requested patch timestamp alone. Gate changes
must be scoped to labeled owned pods, with restoration on failure.

Only after capability validation, freeze a complete plan including paired
seeds, workload, baseline behavior, release trigger, horizon, ETA inputs,
metrics and analysis. E6 oracle may use the known controlled schedule but must
be labeled as scheduled-release knowledge, not perfect prediction of natural
EC2 readiness. E7/E8 require their own validated capabilities and frozen plans.

Current validation: three local tests check no early release at all six delays,
replacement UID rejection, ownership/gate checks, condition preservation and
resource-version preconditions. No Kubernetes resource was changed by these
tests; live validation and the experiment controller remain outstanding.

Live CPU routing validation launched October 1 at about 18:21 UTC using
scripts/validate-readiness-gate.py. It creates only the uniquely named
crossscale-gate-validation-20261001 Pod and Service, checks HTTP exclusion
while gated, then release and EndpointSlice readiness for all six delays.
Timing tolerance was fixed at 5 seconds before its outcomes. Source and raw
artifacts are preserved under results/readiness-validation-20261001; automatic
cleanup checks resource UID and ownership label before deletion, then archives
to the matching private S3 prefix. This validates Kubernetes routing only, not
GPU readiness, runner status-patch RBAC, or the complete E5 experiment design.

## CPU validation completed

All six conditions passed real HTTP exclusion/release checks. Observed
EndpointSlice readiness was 1.047/1.104/1.051/1.100/1.189/1.132 seconds after
scheduled release for delays 0/15/30/60/90/120 respectively, within the declared
5-second tolerance. These are observed control-plane delays, not exact zero
latency. Complete and UID-checked cleanup records are present; the process
exited successfully and private S3 upload succeeded. Raw evidence is committed
under results/readiness-validation-20261001. No GPU measurement occurred.

Remaining before E5: runner pods/status permission, four-model prewarming,
actual inference exclusion/release, usable-capacity observation and ETA input
integration, restoration validation, and frozen measurement protocol. A fixed
controlled release schedule must be labeled as such; it cannot be represented
as a natural KEDA decision or natural EC2 provisioning. No E5–E8 result exists.

## GPU validation launched

October 1 about 19:01 UTC: scripts/validate-gpu-readiness-gate.py launched once,
using a separate proof Pod and Service named
crossscale-gate-gpu-validation-20261001. Original vLLM Deployment is unchanged.
Proof uses the pinned full-context model with batch 4096 and the custom gate.
The runner holds suite.lock via PID 173632 for the validation lifetime; local
exec session 47528 owns the controller. Do not launch another suite.

A temporary same-named Role/RoleBinding grants the runner pods/status patch
only for the proof pod name. This exercises the actual in-cluster helper and
permission, not an administrator patch. Remove these two RBAC resources after
validation cleanup. Raw local directory and private S3 prefix are both named
readiness-gpu-validation-20261001. The controller captures pod/service UIDs,
remembers added claims, deletes only its proof resources, and uses the existing
ownership-aware empty-claim cleanup. Startup deadline is 2400 seconds; all six
delays retain the CPU validation's predeclared 5-second release tolerance.
Each released probe requests a real four-token completion; gated probes must
fail to connect. This is capability validation, not a paired E5 result.

## GPU validation completed

All six GPU conditions passed, with real nonempty completion responses after
release and failed connectivity while gated. EndpointSlice release occurred
0.938/1.052/1.010/1.099/1.025/0.998 seconds after the scheduled time for delays
0/15/30/60/90/120. All were within the predeclared five-second tolerance.
The actual runner's status patch helper and pod-scoped permission worked.
Controller exited successfully; proof Pod/Service and owned empty GPU cleanup
completed, suite.lock released, and temporary Role/RoleBinding were removed
only after checking their rules/subjects against saved manifests. Evidence is
local and private S3 under readiness-gpu-validation-20261001.

This establishes single-pod inference routing control, not a four-replica E5
measurement. Next implement/freeze the controlled-capacity workload controller,
verify two baseline plus two withheld replicas, and integrate ETA observation
without changing the model/SLO condition. E5–E8 remain unrun.

## Controlled phase plan frozen

configs/revision-20261001-e5-plan.json fixes 90 paired runs: five nonempty-tenant
seeds, six nominal delays, and three admission variants. Arrivals last 600s,
drain 180s, burst from 60–360s using .65/.1.65 times the amended measured mixed
capacity. Two of four prewarmed replicas become eligible at t=60+delay. Four
GPUs remain allocated during each run, including when only two can serve.
The randomized order, examined seeds, trace hashes, metrics and paired analysis
are recorded before E5 outcomes. Minimum measurement duration is 19.5 hours.

This is a matched controlled-supply experiment. There is no HPA decision during
measurement: B3 bypasses admission, B5 uses Ready slots, B6 additionally uses
nominal scheduled ETA. Do not describe this as a comparison of slow autoscalers
or natural provisioning. Actual readiness and propagation latency are measured;
a planned or elapsed ETA never increases admission slots. Unexpected pod UIDs,
early release, or lost baseline capacity abort with evidence preserved.

Six local gate/state/plan tests pass. The live suite executor, four-model setup,
EndpointSlice verification and restoration integration are still to be built;
no E5 measurement is running. The healthy original GPU remains the only replica.
