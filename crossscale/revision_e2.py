"""E2 comparison launcher. Capacity-normalized E2 cannot start without mixed qualification."""
import argparse
import json
from pathlib import Path


def prefill_slo_infeasibility(rows, ttft_s=1.5):
    """Serial long-prompt TTFT versus the frozen B SLO.

    rows are completed diagnostic requests with input_tokens and ttft_s.
    """
    usable = [r for r in rows if r.get('ttft_s') and r.get('input_tokens')]
    if not usable:
        raise ValueError('Expected serial diagnostic TTFT evidence')
    rates = [r['input_tokens'] / r['ttft_s'] for r in usable]
    mean_rate = sum(rates) / len(rates)
    longest = max(r['input_tokens'] for r in usable)
    coverable = mean_rate * ttft_s
    misses = [r for r in usable if r['ttft_s'] > ttft_s]
    return dict(
        samples=len(usable),
        measured_prefill_tokens_s=mean_rate,
        slo_ttft_s=ttft_s,
        longest_prompt_tokens=longest,
        tokens_coverable_in_slo=coverable,
        longest_prompt_required_tokens_s=longest / ttft_s,
        ttft_misses=len(misses),
        infeasible=longest > coverable or bool(misses),
    )


def batch_increase_cannot_meet_slo(rows, batch_tokens=8192, ttft_s=1.5):
    """A larger max-num-batched-tokens cannot cut the measured prefill-token work.

    TTFT includes the full prompt prefill. Increasing the batch window only
    reduces the number of engine steps, not the tokens that must be processed.
    """
    floor = prefill_slo_infeasibility(rows, ttft_s=ttft_s)
    misses = [r for r in rows if r.get('ttft_s') and r['ttft_s'] > ttft_s]
    already_one_chunk = sum(r['input_tokens'] <= batch_tokens for r in misses)
    full_prompt_s = floor['longest_prompt_tokens'] / floor['measured_prefill_tokens_s']
    if not misses:
        reason = 'no SLO misses to justify a larger batch window'
    else:
        reason = (
            f'{already_one_chunk}/{len(misses)} SLO misses already fit in one {batch_tokens}-token '
            f'window; the longest prompt still needs {full_prompt_s:.2f}s of prefill at the '
            f'measured {floor["measured_prefill_tokens_s"]:.0f} tok/s, above the {ttft_s}s SLO.'
        )
    return dict(
        **floor,
        current_batch_tokens=batch_tokens,
        misses_already_one_chunk=already_one_chunk,
        longest_prompt_prefill_s=full_prompt_s,
        justified=False,
        reason=reason,
    )


def diagnostic_b_tails(root, relative='revision-20260912/e2-serving-recovery-20260927/batch8192-eager/complete.json'):
    path = Path(root) / relative
    rows = json.loads(path.read_text())['results']
    return [r['request'] for r in rows if r['case'].startswith('B-source') and r['repetition'] == 0]


def require_qualified_two_gpu_capacity(root):
    ledger = json.loads((Path(root) / 'revision-20260912/e1-mixed-terminal/terminal-ledger.json').read_text())
    capacity = ledger.get('qualified_capacity', {}).get('2')
    if capacity is not None:
        return capacity
    reason = ledger.get('capacity_reason', 'mixed capacity unqualified')
    try:
        analysis = batch_increase_cannot_meet_slo(diagnostic_b_tails(root))
        reason += (
            f"; serial B-tail prefill {analysis['measured_prefill_tokens_s']:.0f} tok/s covers "
            f"{analysis['tokens_coverable_in_slo']:.0f} tokens in {analysis['slo_ttft_s']}s SLO, "
            f"but the selected prompts reach {analysis['longest_prompt_tokens']} tokens. "
            + analysis['reason']
        )
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
        reason += '; serial B-tail prefill evidence is required before another serving hypothesis'
    raise RuntimeError(
        reason
        + ' Do not substitute isolated rates, sparse historical qualifications, shortened prompts, or relaxed SLOs.'
    )


def execute(root):
    import fcntl
    from .episodes import save

    root = Path(root)
    with (root / 'suite.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_qualified_two_gpu_capacity(root)
        dest = root / 'revision-20260912/e2-b2-b3'
        dest.mkdir(exist_ok=False)
        save(dest / 'error.json', dict(error='E2 live controller is not implemented; capacity gate passed'))
        raise RuntimeError('E2 live controller is not implemented')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/tmp/experiments'))
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        execute(args.root)
    else:
        print(json.dumps(prefill_slo_infeasibility(diagnostic_b_tails(args.root)), indent=2))


if __name__ == '__main__':
    main()
