"""Offline paired comparisons with explicit missing/invalid evidence accounting.

Call separately for each metric/cohort and frozen experimental condition.
This helper neither runs experiments nor chooses a practical effect threshold.
"""
import math
import random

from .core import quantile


def paired_comparison(records, left, right, seeds, practical_effect, *,
                      bootstrap_seed=20260919, resamples=10000):
    seeds = list(seeds)
    if left == right or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError('Distinct baselines and unique declared seeds required')
    if not math.isfinite(practical_effect) or practical_effect < 0:
        raise ValueError('Predeclared nonnegative practical effect required')
    if not isinstance(resamples, int) or resamples < 100:
        raise ValueError('At least 100 bootstrap resamples required')
    indexed = {}
    for record in records:
        if record['baseline'] not in (left, right):
            continue
        key = (record['seed'], record['baseline'])
        if record['seed'] not in seeds or key in indexed:
            raise ValueError('Unexpected seed or duplicate baseline/seed')
        indexed[key] = record
    conditions = {r['condition_sha256'] for r in indexed.values()}
    modes = {r['mode'] for r in indexed.values()}
    if len(conditions) > 1 or len(modes) > 1:
        raise ValueError('Cannot pool different conditions or live/simulation modes')
    pairs, excluded = [], []
    for seed in seeds:
        a, b = indexed.get((seed, left)), indexed.get((seed, right))
        reason = None
        if a is None or b is None:
            reason = 'missing-run'
        elif a['trace_sha256'] != b['trace_sha256']:
            raise ValueError('Paired traces differ')
        elif a.get('dispatch_valid') is not True or b.get('dispatch_valid') is not True:
            reason = 'invalid-dispatch'
        elif a.get('censored') is not False or b.get('censored') is not False:
            reason = 'censored-or-unknown'
        elif any(r.get('value') is None or not math.isfinite(r['value']) for r in (a, b)):
            reason = 'missing-or-nonfinite-metric'
        if reason:
            excluded.append(dict(seed=seed, reason=reason))
        else:
            pairs.append(dict(seed=seed, difference=a['value']-b['value']))
    differences = [p['difference'] for p in pairs]
    mean = sum(differences)/len(differences) if differences else None
    rng = random.Random(bootstrap_seed)
    boots = [sum(rng.choices(differences, k=len(differences)))/len(differences)
             for _ in range(resamples)] if len(differences) >= 5 else []
    interval = [quantile(boots, .025), quantile(boots, .975)] if boots else None
    complete = not excluded and len(pairs) >= 5
    supported = (mean >= practical_effect and interval[0] > 0) if complete else None
    return dict(left=left, right=right, declared_seeds=seeds, pairs=pairs,
                excluded=excluded, mean_difference=mean, paired_bootstrap_95=interval,
                practical_effect=practical_effect, practical_benefit_supported=supported,
                status='complete' if complete else 'inconclusive-incomplete-pairs',
                bootstrap_seed=bootstrap_seed, resamples=resamples,
                mode=next(iter(modes), None),
                warning='Run-level bootstrap; incomplete-pair estimates are descriptive only. '
                        'Ordering alone does not establish causal attribution.')
