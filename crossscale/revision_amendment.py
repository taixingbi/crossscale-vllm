"""Offline SLO requalification after the 2026-09-30 protocol amendment.

Recompute goodput on existing isolated and mixed traces. Never rerun a seed,
never overwrite original 1.5s ledgers, and never invent mixed capacity from
isolated rates.
"""
import argparse
import json
from pathlib import Path

from .core import summarize
from .revision_e1 import capacity as isolated_capacity
from .revision_e1 import qualifies as isolated_qualifies
from .revision_mixed import capacity as mixed_capacity
from .revision_mixed import qualifies as mixed_qualifies

REVISION = 'revision-20260930-b-ttft-3s'
AMENDED_B_TTFT_S = 3.0
ORIGINAL_B_TTFT_S = 1.5


def amended_config(base):
    config = json.loads(json.dumps(base))
    if config['tenants']['B']['ttft_s'] != ORIGINAL_B_TTFT_S:
        raise ValueError('Amendment starts from the original 1.5s B TTFT SLO')
    config['tenants']['B']['ttft_s'] = AMENDED_B_TTFT_S
    config['slo_revision'] = REVISION
    return config


def _rows(root, relative):
    path = Path(root) / relative / 'run/requests.jsonl'
    if not path.exists():
        return None
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def requalify_mixed(root, config, frozen, ledger):
    records = []
    for spec, entry in zip(frozen['runs'], ledger['runs']):
        if spec['name'] != entry['name']:
            raise ValueError('Terminal ledger does not match the frozen mixed plan')
        row = dict(name=spec['name'], replicas=spec['replicas'], rps=spec['rps'],
                   seed=spec['seed'], outcome=entry['outcome'], path=entry['path'])
        rows = _rows(root, entry['path']) if entry['outcome'] == 'completed' else None
        if rows is None:
            row.update(dispatch_valid=False, passed=False, tenants=None)
        else:
            summary = summarize(rows, dict(config, duration_s=spec['config']['duration_s']))
            valid, passing = mixed_qualifies(summary, rows)
            row.update(dispatch_valid=valid, passed=passing,
                       tenants={t: summary['tenants'][t]['goodput'] for t in ('A', 'B', 'C')})
        records.append(row)
    return dict(
        slo_revision=REVISION,
        b_ttft_s=AMENDED_B_TTFT_S,
        original_b_ttft_s=ORIGINAL_B_TTFT_S,
        original_qualified_capacity=ledger.get('qualified_capacity'),
        qualified_capacity={
            '1': mixed_capacity(records, frozen, 1),
            '2': mixed_capacity(records, frozen, 2),
        },
        e2_offered_total_rps=(
            None if mixed_capacity(records, frozen, 2) is None else
            {'0.65x': mixed_capacity(records, frozen, 2) * 0.65,
             '1.65x': mixed_capacity(records, frozen, 2) * 1.65}
        ),
        skipped='Observer-failed run 28 is not rerun; it cannot qualify a rate that needs every seed.',
        runs=records,
    )


def requalify_isolated(root, config, complete):
    records = []
    for entry in complete['results']:
        rows = _rows(root, 'revision-20260912/e1-isolated/' + entry['name'])
        if rows is None:
            raise FileNotFoundError(entry['name'])
        summary = summarize(rows, dict(config, duration_s=entry.get('summary', {}).get('elapsed_s') or 600))
        valid, passing = isolated_qualifies(summary, rows, entry['tenant'])
        records.append(dict(tenant=entry['tenant'], rps=entry['rps'], seed=entry['seed'],
                            dispatch_valid=valid, passed=passing))
    return dict(
        slo_revision=REVISION,
        original_capacities=complete.get('capacities'),
        capacities={t: isolated_capacity(records, t) for t in ('A', 'B', 'C')},
        note='Isolated capacities are not mixed capacity and are not summed for E2.',
    )


def freeze(root, base, mixed_plan, mixed_ledger, isolated_complete):
    root = Path(root)
    dest = root / 'revision-20260930'
    dest.mkdir(exist_ok=True)
    config = amended_config(base)
    mixed = requalify_mixed(root, config, mixed_plan, mixed_ledger)
    isolated = requalify_isolated(root, config, isolated_complete)
    mixed_path = dest / 'requalified-mixed-ledger.json'
    isolated_path = dest / 'requalified-isolated-capacities.json'
    for path, payload in ((mixed_path, mixed), (isolated_path, isolated)):
        if path.exists():
            raise FileExistsError(path)
        path.write_text(json.dumps(payload, indent=2) + '\n')
    return mixed, isolated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--plan', type=Path, default=Path('configs/revision-20260912/e1-mixed-plan.json'))
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    base = json.loads(args.config.read_text())
    frozen = json.loads(args.plan.read_text())
    ledger = json.loads((args.root / 'revision-20260912/e1-mixed-terminal/terminal-ledger.json').read_text())
    isolated = json.loads((args.root / 'revision-20260912/e1-isolated/complete.json').read_text())
    if args.freeze:
        mixed, iso = freeze(args.root, base, frozen, ledger, isolated)
    else:
        config = amended_config(base)
        mixed = requalify_mixed(args.root, config, frozen, ledger)
        iso = requalify_isolated(args.root, config, isolated)
    print(json.dumps({'mixed': mixed['qualified_capacity'], 'isolated': iso['capacities'],
                      'e2_offered_total_rps': mixed['e2_offered_total_rps']}, indent=2))


if __name__ == '__main__':
    main()
