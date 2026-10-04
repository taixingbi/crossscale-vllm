# Full-context live experiment results, October 4, 2026

The completed live measurements do not establish the hypothesized practical
benefit of ETA-aware admission over Ready-only admission. Priority E3 has an
exactly zero B6−B5 paired difference in its five seeds. E8's difference is
+0.15 percentage points, with a seed-bootstrap 95% interval of −0.83 to +1.51
points. Neither establishes the frozen +5-point practical improvement. This
is a negative result under the measured workload and serving condition, not
proof that ETA-aware admission can never help.

All E0–E8 measurement phases have finished. Raw phase evidence is retained in
Git where feasible and in the private S3 archive; earlier large streams have
location/hash manifests. E7 controlled has 24 successful measurements and one
preserved pre-load Oracle startup failure, not 25 successful measurements.
No failed or completed measurement was rerun to improve its result.
Final infrastructure cleanup is still pending;
this document is the results synthesis checkpoint, not a claim of task closure.

## Conditions and interpretation

The measured runtime uses Llama-3.1-8B-Instruct, vLLM 0.28.0 with a pinned
container digest, full 32768-token context, four sequences, eager execution,
prefix caching disabled, and a 4096-token batch budget. The restored service
uses its original 1024-token budget. Separate E0 timing measurements were
collected for the 4096 condition; original 1024 E0 samples are not pooled.

Original mixed calibration did not qualify at B TTFT 1.5 seconds. Serial
serving diagnostics showed long B prompts still missing that threshold even
without contention. The documented September 30 amendment uses B TTFT 3 seconds;
this is a post-hoc SLO relaxation with selection bias, not a demonstrated
serving-performance fix. Both one- and two-GPU amended mixed capacity qualify
at 0.025 total RPS, which does not demonstrate positive scaling. Later offered
loads are normalized to that measured capacity. The calibration's original
failure and its diagnostics remain part of the evidence.

Weighted SLO goodput is the weighted average of tenant success fractions,
with metric weights A:B:C = 3:2:1. Arrival proportions are separately 4:2:1
before workload-phase changes. Rejects, timeouts, and errors stay in the
all-offered denominator. Missing tenants leave weighted goodput undefined;
we do not silently reweight sparse cohorts. Latency quantiles cover completed
requests only. Positive gateway timing overhead is not classified as an ETA
deferral; actual delay actions require decision evidence.

## Paired results

All intervals below are seed-level bootstrap intervals, not request-level
independent-sample intervals. Five seeds and sparse tenant counts limit
precision. Multiple contrasts are reported without multiplicity adjustment.
The machine-readable outputs retain individual pairs and incomplete cohorts.

- E2: ten held-out B2/B3 evaluations, after six threshold-training runs.
  B3−B2 whole-run weighted goodput is zero in all five pairs. Training runs
  are excluded from the held-out comparison. The selected SLO threshold is 0.8.
- Priority E3: B6−B5 is zero in all five pairs. B5−B3 and B6−B3 average
  −0.32 points, interval −6.43 to +6.90. Fourteen runs show no scale-out;
  one is censored before four Ready replicas. Sparse equal outcomes are not
  proof of policy equivalence.
- E3 B2/B4 extension: B3−B2 averages −5 points, interval −15 to 0;
  B6−B4 is zero. The extension ran later than priority E3, so matching seeds
  does not remove execution-period confounding.
- E4 noisy neighbor: primary A goodput B6−B5 is zero. Both B5 and B6 trail
  B3 by 8.52 points, interval −9.91 to −7.28. This experiment does not
  support improved A protection from these admission settings.
- E5 controlled capacity: 90 valid cells across six lags and three baselines.
  B6−B5 whole-run weighted-goodput means range from 0 to +0.95 points;
  intervals include zero. Four GPU instances were prewarmed, with two
  deliberately withheld by readiness gates. This is controlled usable-capacity
  release, not natural EC2 provisioning.
- E6 ETA errors: 35 valid cells. Nominal ETA−no ETA averages −0.95 points,
  interval −2.86 to 0. Signed perturbation contrasts are preserved in the
  data; they do not establish a robust positive benefit. The nominal and
  oracle configurations use the same scheduled release knowledge, so a
  between-run difference is not proof of better oracle information.
- E7 controlled: CrossScale−B5 averages −0.95 points, interval −2.86 to 0;
  CrossScale−no-tenant averages +1.25 points, interval 0 to +2.78.
  Oracle−CrossScale is zero in four available pairs. Its missing fifth pair
  is the preserved startup failure; no five-pair interval is claimed.
- E7 natural: B6−B5 averages +0.77 points, interval 0 to +2.31;
  B6−no-tenant averages −0.18 points, interval −2.86 to +2.31.
- E8: 20 valid one-hour cells. B6−B5 averages +0.15 points, interval
  −0.83 to +1.51. B5−B3 averages −10.67 points, interval −13.06 to −8.27;
  B6−B3 averages −10.52 points, interval −12.22 to −8.78. B3−B2 averages
  −0.43 points, interval −1.02 to +0.06. Both bursts and each of the six
  arrival phases are analyzed separately in the request-outcome artifact.

E7 controlled, E7 natural, and E8 decision audits cover all offered request
IDs and replay without policy mismatches. They record no actual delay actions
and no fixed-state ETA branch differences. This is evidence that the ETA wait
branch was not exercised in these measured requests. It is not evidence of
successful ETA-driven deferral. Earlier E4–E6 have no equivalent recorded
policy audit; their timing fields cannot establish actual deferral.

## Provisioning and allocation cost

The natural scaler audit pins setup Deployment, ScaledObject, and HPA identities.
It retains 531 snapshots with a mismatched/deleting ScaledObject and 11 with
missing/competing target HPAs as unverified. No linked sample introduces an
unpinned HPA. Sequential reads and identity linkage do not establish causality.
The audit includes E2 training and evaluation snapshots, explicitly named by
source path. E4 has three observed completions to four Ready replicas; E8 has
nine censored first-scale intervals and eleven no-scale runs. A desired-replica
change is not proof that four GPUs became usable.

E8 allocation integrates EC2 LaunchTime through the 3600-second arrival plus
180-second drain window and counts idle and pending instances. Observed running
time brackets are also retained, conditional on no unobserved stop/restart
between reads. The maximum observed API-read gap is 16.08 seconds. Mean
allocated GPU-hours per cell are B2 2.100, B3 3.033, B5 2.594, and B6 2.404.
The captured AWS Pricing API product quotes Linux shared-tenancy g5.xlarge at
$1.006 per hour in us-east-1, effective September 1, 2026. Multiplication by
this price is a compute estimate, not invoice attribution or billed runtime.

Automatic node disruption was disabled. HPA pod scale-down therefore does not
imply that idle EC2 instances stopped costing money. The observed per-seed
cost–SLO points are exported without interpolation or an invented optimum.
Observed startup/reset/inter-run cleanup/restoration allocation is separately
bracketed at 5.127–5.208 GPU-hours for the E8 controller window, starting at
its first log record and ending at restoration. Earlier unlogged setup and
original-GPU idle time after restoration are excluded. This overhead is not
attributed to individual baselines and includes shutting-down allocation. Discounts, EBS, network, CPU nodes, and EKS charges are
excluded; no total AWS bill or savings claim is made.

## Reproduction and artifacts

Run the repository scripts with the experiment Python environment:
`report-e2-e3-outcomes.py`, `report-e4-e7-outcomes.py`, `report-e8-outcomes.py`,
`report-natural-scaler-audit.py`, `extract-e8-lifecycle.py`, `report-e8-cost.py`,
and `plot-final-checkpoints.py` under `scripts/`. They consume preserved files
under `results/full-experiments-20260908/run/revision-20260912/`.

The same directory contains paired JSON outputs, lifecycle/price evidence,
scaler audits, and `figures/` with PNG/PDF exports. The S3 archive is
`s3://crossscale-experiment-results-646821141010-us-east-1/full-20260908/`.
E8 raw checkpoint is 6f66ab9; inference validation is 87066be. Later analysis
commits are recorded in Git history. The October 4 post-E8 inference returned
HTTP 200 and the expected answer from one Running/Ready replica on the original
GPU node. Original data, failed attempts, and the unrelated experiment-plan
edit remain preserved.
