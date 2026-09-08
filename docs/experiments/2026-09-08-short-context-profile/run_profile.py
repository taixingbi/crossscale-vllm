import asyncio
import json
import time
import urllib.request
from pathlib import Path

from crossscale import profile

ROOT = Path(__file__).resolve().parent
URL = 'http://vllm:8000'
MODEL = 'meta-llama/Llama-3.1-8B-Instruct'
plan = json.loads((ROOT / 'plan.json').read_text())
config = json.loads((ROOT / 'config.json').read_text())
original_run = profile.run

def get(path):
    with urllib.request.urlopen(URL + path, timeout=15) as response:
        return response.read()

async def recorded_run(c, baseline, out, url, model, tokens):
    label = Path(out).name
    print(json.dumps({'event': 'start', 'episode': label, 'unix_s': time.time()}), flush=True)
    (ROOT / (label + '-metrics-before.txt')).write_bytes(get('/metrics'))
    result = await original_run(c, baseline, out, url, model, tokens)
    (ROOT / (label + '-metrics-after.txt')).write_bytes(get('/metrics'))
    rows = [json.loads(line) for line in (Path(out) / 'requests.jsonl').read_text().splitlines()]
    lag = max((r.get('dispatch_lag_s', 0) for r in rows), default=0)
    progress = {'event': 'complete', 'episode': label, 'unix_s': time.time(),
                'weighted_goodput': result['weighted_slo_goodput'],
                'tenants': {t: {k: v[k] for k in ['offered', 'completed', 'goodput', 'errors', 'timeout']} for t, v in result['tenants'].items()},
                'max_dispatch_lag_s': lag, 'dispatch_valid': lag <= plan['max_dispatch_lag_s']}
    with (ROOT / 'progress.jsonl').open('a') as f:
        f.write(json.dumps(progress) + '\n')
    print(json.dumps(progress), flush=True)
    await asyncio.sleep(5)
    return result

async def main():
    get('/health')
    models = json.loads(get('/v1/models'))['data']
    assert any(m['id'] == MODEL and m['max_model_len'] == 4096 for m in models)
    tokens = json.loads((ROOT / 'tokens.json').read_text())
    for n, output in [(128, 64), (512, 128), (1024, 256)]:
        request = urllib.request.Request(URL + '/v1/completions', data=json.dumps({
            'model': MODEL, 'prompt': tokens[:n], 'max_tokens': output,
            'ignore_eos': True, 'temperature': 0}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            usage = json.load(response)['usage']
            assert usage['completion_tokens'] == output
            print(json.dumps({'event': 'warmup', 'usage': usage}), flush=True)
    profile.run = recorded_run
    report = await profile.sweep(config, ROOT / 'sweep', URL, MODEL, ROOT / 'tokens.json',
                                 plan['rates'], plan['seeds'], plan['duration_s'], plan['target_per_tenant'])
    progress = [json.loads(line) for line in (ROOT / 'progress.jsonl').read_text().splitlines()]
    report['all_dispatch_valid'] = all(r['dispatch_valid'] for r in progress)
    report['scope'] = plan['scope']
    report['dispatch_validated_sustainable_rps'] = report['sustainable_rps'] if report['all_dispatch_valid'] else None
    (ROOT / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'event': 'finished', 'sustainable_rps': report['dispatch_validated_sustainable_rps']}), flush=True)

if __name__ == '__main__':
    asyncio.run(main())
