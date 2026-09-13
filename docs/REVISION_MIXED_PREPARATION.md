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
