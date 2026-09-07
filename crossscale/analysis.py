"""Run-level paired uncertainty, without treating requests as independent runs."""
import json
from pathlib import Path
import random
from .core import quantile


def compare(paths, left, right):
    pairs = {}
    modes = set()
    for path in paths:
        for file in Path(path).rglob('manifest.json'):
            m = json.loads(file.read_text())
            if m.get('baseline') not in (left, right):
                continue
            s = json.loads(file.with_name('summary.json').read_text())
            modes.add(m['mode'])
            key = (m['seed'], m['trace_sha256'])
            pair = pairs.setdefault(key, {})
            if m['baseline'] in pair:
                raise ValueError('duplicate baseline/seed/trace: compare one experimental condition at a time')
            pair[m['baseline']] = s['weighted_slo_goodput']
    if len(modes) > 1:
        raise ValueError('cannot combine simulation and live runs')
    ds = [p[left]-p[right] for p in pairs.values() if left in p and right in p and p[left] is not None and p[right] is not None]
    if not ds:
        raise ValueError('no complete comparable pairs')
    rng = random.Random(0)
    boots = [sum(rng.choices(ds, k=len(ds)))/len(ds) for _ in range(10000)] if len(ds) >= 2 else []
    return dict(left=left, right=right, pairs=len(ds), unmatched_or_missing=len(pairs)-len(ds), mean_wg_difference=sum(ds)/len(ds),
                paired_bootstrap_95=[quantile(boots, .025), quantile(boots, .975)], mode=next(iter(modes)),
                warning='at least 5 independent paired runs recommended; ensure identical hardware/condition and randomize execution order')
