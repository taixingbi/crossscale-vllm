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
