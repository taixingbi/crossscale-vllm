# Protocol amendment — 2026-09-30

This amendment is for the full-workload CrossScale suite after mixed E1
finished unqualified under the original tenant-B TTFT SLO. It does not erase
that result. Original 1.5s evidence, serving-recovery negatives, and run 28
remain archived.

## What is infeasible

On the original g5.xlarge A10G, serial 8192-eager B-tails prefill at about
3895 tok/s. The original 1.5s B TTFT SLO covers about 5842 tokens. Mixed
seed-704 B prompts reach 10131 tokens (need ~2.60s of prefill). Observed max
B TTFT on those mixed traces is 2.818s. Batch/compile trials did not remove
that prefill work. Isolated B still qualified at 0.05 RPS under 1.5s; the
failure is mixed long-prompt service time versus the original SLO, not a
missing replica.

## Frozen change

Keep the model, GPU, precision, 32768 context, 4096 mixed serving batch, token
corpus, 4:2:1 mix, seeds 701–705, consecutive-rate rule, 95% per-tenant
goodput, 50ms dispatch limit, and maximum four GPUs.

Change only tenant B TTFT from **1.5s to 3.0s**. Frozen config:
`configs/revision-20260930.json`, condition name
`revision-20260930-b-ttft-3s`. 3.0s is a round ceiling above the measured
2.818s mixed max and the 2.60s prefill-floor estimate. It is not the smallest
threshold that happens to qualify (2.0s already would). Do not shorten
prompts, change GPUs, or substitute isolated/.005 RPS for mixed capacity.

A and C SLOs are unchanged (0.5s and 5s).

## Requalification, not a rerun

Recompute goodput on the existing isolated and mixed `requests.jsonl` traces
with the amended SLO. Do not rerun seed 704 or observer-failed run 28.
`python -m crossscale.revision_amendment --freeze` writes exclusive ledgers
under `revision-20260930/`. Original
`e1-mixed-terminal/terminal-ledger.json` stays null at 1.5s.

Frozen bytes:

- `configs/revision-20260930.json` SHA256 `722b60dbbff7891e005071931e51cff4a075ece972611b674b5a6c80879adf2d`
- `revision-20260930/requalified-mixed-ledger.json` SHA256 `ce5a0d4cc2f3f3af0ef18656cb8eca71e9862b83306d8a9f055998c77cb0ab7f`
- `revision-20260930/requalified-isolated-capacities.json` SHA256 `eb771c9e7d608954f5110bdb7ca248c83860ab6dc0f9ba3aa1f610b27438ad4a`

Under 3.0s, the existing mixed traces qualify **0.025 RPS on both 1 and 2
GPUs**. Mixed 0.05 still fails tenant A on some seeds. Isolated capacities
become A 0.2, B 0.1, C 0.01; isolated B is not mixed capacity and is not
summed for E2.

## E2 offered load

Two-GPU mixed capacity for the amended condition is 0.025 RPS. E2 uses
**0.65× = 0.01625** RPS before t=60s and **1.65× = 0.04125** RPS afterward,
split 4:2:1. KEDA/HPA must still actually request 2→4. The live B2/B3
controller remains unimplemented; this amendment only supplies the missing
capacity input. Do not launch historical `study.py` numbering.

E3–E8 stay unimplemented until each phase is frozen on this SLO revision.
They may use the same amended SLOs; they still need live controllers.

## Reporting

Report original 1.5s mixed as unqualified. Report 3.0s mixed 0.025 as a
separately named condition. Do not pool the two SLOs as one capacity.
