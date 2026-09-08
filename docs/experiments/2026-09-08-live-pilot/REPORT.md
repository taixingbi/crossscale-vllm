# Live single-GPU pilot — 2026-09-08

The in-cluster repeat completed all 57 offered requests. Weighted tenant SLO goodput was 87.31%; eight requests missed TTFT targets (seven tenant A, one tenant B). No requests failed, timed out, or were rejected. Output throughput was 51.925 tokens/s using the 120-second offered window, including drain completions.

One warm g5.xlarge GPU served Llama 3.1 8B Instruct with 4,096-token context, four concurrent sequences, and eager execution. Seed 17 offered 0.35 / 0.8 / 0.35 requests/s across three 40-second phases. Prompt/output medians were A 128/64, B 512/128, C 1024/256 tokens; lengths used lognormal sigma 0.25. The corpus came from the serving model tokenizer. All sampled total lengths fit the configured context.

Tenant goodput: A 25/32 (78.13%), B 18/19 (94.74%), C 6/6 (100%). These are small samples from one seed; no confidence or saturation claim is supported.

The first local port-forward run had six ServerDisconnectedError failures and is preserved in run/. The same trace completed without errors using a separate CPU load-generator pod and the Kubernetes Service; its results are in run-incluster/. Both trace hashes match. This supports using in-cluster load generation; it does not establish the precise disconnect cause. The repeat also had a warmer prefix cache.

This is a shortened-prompt functionality/load pilot, not formal E0/E1/E2 or sustainable-RPS calibration. The harness labels pass-through as B0; this uses one GPU rather than the formal two-GPU baseline. No admission or autoscaling was active. Repeated corpus and prefix caching limit workload realism. TTFT/TPOT are client measurements and latency tails are conditional on completion.

Artifacts include exact config, trace hashes, all request records, deployment/pod snapshots, pinned serving image digest, load-generator image ID and package versions, warmup/tokenizer provenance, and raw vLLM metrics before/after the in-cluster run. The temporary CPU load-generator pod was deleted, temporary namespace access revoked, and local port-forward stopped. The existing vLLM pod remained Running with zero restarts.

## Published evidence

This directory includes both request-level runs, configs, summaries, trace hashes, token corpus, and load-generator package versions. Deployment/pod snapshots and raw server metrics remain in the local results archive; they are not included in this published directory.
