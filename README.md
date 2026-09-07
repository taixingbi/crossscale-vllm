# CrossScale experiments

Provisioning-gap coordination for multi-tenant vLLM. See [实验计划](docs/EXPERIMENT_PLAN.md). This is an experimental prototype, not a validated performance result.

## Local smoke test

Python 3.11+; simulation and core tests use only the standard library.

```sh
python3 -m unittest discover -s tests -v
python3 -m crossscale.cli simulate --baseline B6 --out results/smoke-b6
python3 -m crossscale.cli matrix --experiment E2 --seeds 17 18 19 --out results/simulation
```

Every output directory must be new. Simulation includes B0–B6, ready-only, weight ablation and oracle ETA. `matrix --experiment E4` sweeps lag; E5 sweeps error; E6 ablates components; E7 produces a synthetic one-hour workload. Synthetic output is **not paper evidence**.

## Real vLLM experiment

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[live]'
```

1. Create the environment using [Terraform setup](infra/README.md), or prepare an EKS cluster with GPU device plugin, Karpenter NodePool/EC2NodeClass, KEDA and Prometheus. Fill in image/model placeholders in `deploy/vllm.yaml`; use a dedicated namespace. The optional `infra/` configuration provisions cloud infrastructure; local simulations do not need it. Configure Prometheus discovery of vLLM and the gateway explicitly; annotations alone do not guarantee scraping.
2. Capture E0, then profile one fixed GPU before choosing rates. Use a model-tokenized corpus saved as a JSON integer array (`tokens.json`) with at least 16,384 valid tokens. The runner sends `/v1/completions` with token IDs and deterministic length control; the chosen vLLM version must support `ignore_eos` and streamed usage. Supply `VLLM_API_KEY` via environment if required.
3. Run the observer using your explicit kube context. Its `state.json` is the gateway's input. E0 ETA is a held-out training P90, in seconds. Raw observations contain cluster object metadata: keep results private.

```sh
.venv/bin/python -m crossscale.cli observe \
  --context YOUR_CONTEXT --namespace crossscale --deployment vllm \
  --selector app=vllm --duration 600 --interval 1 --eta 60 --out results/e0-01
# Separately trigger your planned scale-out after observation starts.
.venv/bin/python -m crossscale.cli e0-summary results/e0-01/observations.jsonl
```

4. Run the gateway on the load-generator host with access to the vLLM Service. One process owns all admission state. No multi-worker deployment. Make `/metrics` reachable by Prometheus with job label `crossscale-gateway`. All baselines use this same proxy; only admission policy changes. For B0/B1/B4 configure fixed replicas; B2 uses `deploy/queue-keda.yaml`; B3/B5/ready-only/B6 use `deploy/slo-keda.yaml`. Install exactly one scaler per Deployment. Before a live run verify baseline replica/scaler configuration; `--baseline` on the load runner labels the run, it does not change the cluster.

```sh
.venv/bin/python -m crossscale.cli gateway --baseline B6 \
  --state results/e0-01/state.json --url http://VLLM_SERVICE:8000
.venv/bin/python -m crossscale.cli live --baseline B6 \
  --url http://127.0.0.1:8080 --model YOUR_MODEL --tokens tokens.json \
  --out results/live-b6-17
```

Use a fresh observer directory per run and keep it alive through the drain window. Missing/stale state fails with HTTP 503. The experimental gateway uses static weighted concurrency quotas and deadline-limited ETA deferral; it does not yet predict KV pressure or borrow idle quotas. Slow scaling is supplied by KEDA/HPA, never by a second writer to Deployment replicas.

5. Repeat with fixed seed and randomized baseline order. Do not compare smoke rates as if they were calibrated. After measuring sustainable one-GPU RPS, generate a configuration:

```sh
.venv/bin/python -m crossscale.cli calibrate --replica-rps 1.5 --out configs/calibrated.json
```

The RPS above is an **example**, not a measurement. Record real calibration provenance. Pass `--config configs/calibrated.json` to both runner and gateway.

## Artifacts and limitations

`requests.jsonl` contains all offered requests including failures; `summary.json` reports weighted/per-tenant goodput, conditional latency tails, failures and Jain index. `timeseries.jsonl` contains synthetic controller state; live capacity timeseries are in the observer output. `manifest.json` labels simulation/live and hashes the request trace.

E0 summary uses polling-observed desired/ready transitions; raw Pod/Node/NodeClaim timestamps support further stage analysis. Full cold/warm repetition automation, actual GPU billing integration, live E4 readiness gating, phase-conditioned ETA training, production trace replay and cost-frontier sweeps are not implemented. E7 simulation has scale-out only. Do not interpret ready-time GPU-hours as AWS cost.

## Profiling and paired analysis

Run warmup first, verify exactly one ready replica and no scaler, then sweep the measured tenant mix directly against vLLM (without admission):

```sh
.venv/bin/python -m crossscale.cli profile --url http://VLLM_SERVICE:8000 \
  --model YOUR_MODEL --tokens tokens.json --rates 0.25 0.5 1 1.5 2 3 \
  --seeds 17 18 19 --duration 180 --target 0.95 --out results/profile
python3 -m crossscale.cli compare results/simulation/E2/default --left B6 --right ready-only
```

`profile.json` selects the highest consecutively passing tested RPS at which every tenant meets the goodput target in every seed. Rates are examples; extend the sweep as needed. `compare` bootstraps paired **run-level** WG differences, rejects mixed live/simulation data and duplicate pairs. Compare only one lag/error/hardware condition at a time.
# crossscale-vllm

## Continuous integration

[GitHub Actions](https://github.com/taixingbi/crossscale-vllm/actions/workflows/ci.yml) runs on pushes, pull requests, and manual dispatch. It tests Python 3.11–3.14 (including the HTTP integration tests), smoke-tests the installed CLI, checks formatting and validates both Terraform roots using the committed provider locks, and lints/renders the GPU Helm chart. CI does not require AWS credentials or deploy infrastructure.

Export supporting serving/GPU/capacity series after a run:

```sh
.venv/bin/python -m crossscale.cli telemetry --url http://PROMETHEUS:9090 \
  --start START_UNIX_SECONDS --end END_UNIX_SECONDS --step 5 --out results/metrics-run17
```

Defaults scope queries to namespace `crossscale`; use `--queries queries.json` to provide your installed version's actual metric names and labels. Empty series are explicitly listed, never converted to zeros. DCGM GPU metrics require a separate exporter. E0 summary includes per-Pod stage timestamps linked through Node/providerID plus completed/censored gap statistics.
