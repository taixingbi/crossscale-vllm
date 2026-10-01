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
