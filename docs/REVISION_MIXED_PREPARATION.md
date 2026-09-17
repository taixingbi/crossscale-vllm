# Mixed calibration preparation — September 13

The active isolated E1 controller remains unchanged. `crossscale/revision_mixed.py`
is an offline planning and qualification module, not a live controller. No mixed
rates are frozen yet and no mixed measurements have started. The rates used in
unit tests are test fixtures, not an approved experimental rate grid.

The offline CLI `python3 -m crossscale.revision_mixed --help` documents how to
persist a plan with explicit `--rates` and `--plan` arguments. It exclusively
creates the destination, refuses to overwrite an existing plan, and returns
the exact file SHA-256, run count, arrival/drain hours and minimum runtime.
Provisioning, rollouts, warmups, export and restoration add to that minimum.
There is no execution option. No actual rate grid was frozen by this tooling
change. Runtime is material: even a single .01 RPS test-fixture point across
both replica counts and five seeds requires about 194.4 arrival-hours to target
100 C requests per run. Review total duration before declaring the real grid;
do not silently reduce the sample requirement or substitute favorable seeds.

The builder uses five fixed seeds 701–705 and identical 4:2:1 tenant traces for
one and two fixed replicas. Horizons target 100 offered C requests, with a hard
minimum of 60 for every tenant. It does not search seeds. Qualification retains
the 50 ms dispatch limit and 95% per-tenant SLO-goodput requirement. Capacity
requires every seed and every lower tested rate to pass separately at each GPU
count; it never assumes linear scaling.

Before launch: freeze a scientifically justified rate grid and total runtime,
persist the generated plan, implement the exclusive-lock controller with
restoration and ownership checks, and verify telemetry. The mixed controller
must wait for isolated E1 completion, restoration and lock release. Reuse the
installed token counters and record unavailable GPU utilization explicitly.

The E2/E3 audit identified outstanding work:

- Current B5 uses desired capacity for admission, while B6 uses ready capacity
  plus ETA-conditioned deferral. This is more than an ETA-only difference;
  resolve the revised ablation definition before measurement and preserve the
  historical policy as historical evidence.
- The historical baseline runner has a fixed observation horizon and fixed
  60–180 second burst summary. Revised comparisons need actual scale-decision
  and usable-readiness cohorts, explicit censoring, and readiness/drain tracking.
- E2 must use actual KEDA/HPA decisions. The historical manual matched schedule
  is unsuitable as a replacement for the required 2-to-4 decision.
- Freeze disjoint training/test seeds, scaler settings, baseline order and the
  practical effect criterion before evaluation outcomes. Missing mixed capacity
  must be reported as a limitation, not replaced with a sum of isolated rates.

Validation: `python3 -m unittest tests.test_revision_mixed tests.test_revision_e1`
passes seven tests, including paired trace identity, sample sufficiency, missing
tenant/dispatch rejection, complete consecutive-rate qualification, runtime/hash
reporting and refusal to overwrite a frozen plan.

## September 17 execution declaration

Isolated E1 has completed all 90 valid runs and restored original serving.
Freeze mixed total rates .01/.025/.05 RPS, five seeds 701–705, paired across
one and two fixed GPUs. The low anchor is the historical exploratory one-GPU
.01 point; .025 and .05 extend upward to test overlap sensitivity. This is a
new qualification with substantial per-tenant samples, not reuse of historical
qualification. Do not sum isolated rates or infer two-GPU capacity from one GPU.
No lower-rate seed search or outcome-driven replacement is authorized by this
plan. If .01 fails, capacity is unqualified on this grid and the E2 input remains
unestablished; report that limitation before choosing a different experiment.

Frozen plan configs/revision-20260912/e1-mixed-plan.json SHA256
`c4b3a2ef8ce5a9689dac039ce78ce1c2eb4713ad1192df3e4b0ae7e2df4cc051`.
30 runs, 311.111 arrival-hours plus 1.5 drain-hours: at least 312.611 hours
(13.03 days), excluding provisioning, rollouts, warmups, export and restoration.
The longest individual arrival horizon is 19h26m40s. Sample requirements and
seeds are unchanged; long quiet log intervals are expected.

Explicit controller: python -m crossscale.revision_mixed_live --execute
--config configs/default.json --plan configs/revision-20260912/e1-mixed-plan.json.
It checks isolated completion/restoration, takes suite.lock, rejects an existing
output directory, records all outcomes and restores one original-condition
replica with inference warmup. Original GPU deletion preference and owned-only
cleanup are retained. No E2/E3 automatically launches from this controller.
Kubernetes raw snapshots every 5s, Prometheus every 10s, all request timing retained.
The 10s query step keeps even 19-hour runs below the Prometheus range point limit.
The slower fixed-capacity snapshot cadence avoids exhausting runner storage;
default cadence for provisioning observers remains 1s. GPU utilization remains
explicitly unavailable if no exporter series exists. E2/E3 implementation and
policy audit can proceed offline during this long-running calibration.
