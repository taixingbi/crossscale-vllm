# Single-GPU short-context profile — 2026-09-08

**Highest consecutively passing tested rate: 0.2 requests/second.** All 1,220 offered requests completed across 18 runs. There were 226 TTFT misses, no TPOT misses, no transport errors, and no timeouts. This is a workload-specific tested point, not an estimate of general model capacity.

Measurement window: 2026-09-08T21:20:17.030301+00:00 to 2026-09-08T22:16:00.398068+00:00. Six rates × three seeds (17, 18, 19), each with a 180-second Poisson arrival horizon. Requests drain before the next episode. At sparse rates, the runner can return before 180 seconds if the final scheduled request has already completed; the configured workload and throughput denominator remain 180 seconds.

## Predeclared qualification

Every tenant must achieve at least 95% goodput in every seed, and all lower tested rates must also pass. A request is good only if both TTFT and TPOT meet its tenant targets. All failures remain in the denominator. Runs are invalid if maximum client dispatch lag exceeds 50 ms; every run passed this check, with a worst case of 33.01 ms.

## Results

- 0.1 RPS: 3/3 seeds passed; mean weighted goodput 100.00%; seed range 100.00%–100.00%.
- 0.2 RPS: 3/3 seeds passed; mean weighted goodput 99.17%; seed range 97.50%–100.00%.
- 0.3 RPS: 2/3 seeds passed; mean weighted goodput 98.19%; seed range 94.58%–100.00%.
- 0.4 RPS: 2/3 seeds passed; mean weighted goodput 95.96%; seed range 87.88%–100.00%.
- 0.6 RPS: 0/3 seeds passed; mean weighted goodput 79.42%; seed range 74.69%–84.01%.
- 0.8 RPS: 0/3 seeds passed; mean weighted goodput 64.85%; seed range 56.62%–70.33%.

At 0.3 RPS, seed 19 missed the criterion for tenants A and B. One B request had TTFT 1.506 seconds against a 1.5-second target, illustrating the sensitivity of this finite-sample boundary. At 0.4 RPS, two seeds passed and one failed. Both 0.6 and 0.8 RPS failed all seeds. Mean weighted goodput alone would hide some tenant failures.

## Serving and workload conditions

One warm g5.xlarge GPU served Llama 3.1 8B Instruct with a 4,096-token context limit, four concurrent sequences, eager execution, and the deployment’s default prefix-cache behavior. The CPU load-generator pod accessed the Kubernetes Service directly. No admission or HPA was active. The vLLM Deployment spec was identical before and after the sweep, and the serving pod remained Running with zero restarts.

Tenant arrival mix was A:B:C = 4:2:1. Prompt/output medians were A 128/64, B 512/128, C 1024/256 tokens; lognormal sigma 0.25. TTFT targets were 0.5/1.5/5 seconds; TPOT targets were 0.05/0.08/0.12 seconds; weights were 3/2/1. The corpus was generated using the serving model tokenizer and reused from the pilot. All pre-generated traces fit the context limit. Three representative requests warmed the model before the sweep.

## Interpretation and limits

This calibrates only the shortened-prompt, warm-cache condition. It does not calibrate the full long-context workload or establish E0, E1, E2, two-GPU scaling efficiency, or an admission-policy benefit. The harness B0 label means pass-through here, not the formal two-GPU B0 baseline.

Three seeds are limited evidence; low-rate tenants have very few samples, including only one tenant C request in one run. Rates were tested in ascending order, so time/cache effects are not randomized. Repeated text and prefix caching reduce workload realism. The 0.2 RPS result is the highest consecutively passing tested point; it is not an interpolated saturation boundary or a statistically guaranteed production SLO. Do not extrapolate it linearly to two or four GPUs.

## Evidence

This directory contains the exact plan, configuration, token IDs, runner, dependency versions, per-run manifests/trace hashes, all request records, and summaries. Raw Prometheus-format vLLM snapshots and Kubernetes object snapshots remain in the local results/profile-20260908 archive.

## Final verification and cleanup

All 18 saved traces were regenerated from their exact configurations and matched request IDs, arrival times, tenants, and requested lengths. All request counts matched the predeclared plan. The temporary CPU load-generator pod was confirmed absent and its temporary EKS access entry removed. The existing vLLM pod was retained.
