"""Run inside the experiment pod, from /tmp/experiments, after uploading code."""
import json
from pathlib import Path
import time
import urllib.request
from crossscale.episodes import Episodes


root = Path('/tmp/experiments')
for attempt in range(120):
    try:
        with urllib.request.urlopen('http://vllm:8000/health', timeout=5):
            break
    except OSError:
        if attempt == 119:
            raise
        if attempt % 3 == 0:
            print(json.dumps({'event': 'preflight-waiting-ready', 'unix_s': time.time()}), flush=True)
        time.sleep(10)
with urllib.request.urlopen('http://vllm:8000/v1/models', timeout=10) as response:
    models = json.load(response)['data']
assert any(m['id'] == 'meta-llama/Llama-3.1-8B-Instruct' and m['max_model_len'] == 32768 for m in models)
tokens = json.loads((root / 'tokens.json').read_text())
request = urllib.request.Request('http://vllm:8000/v1/completions', data=json.dumps({
    'model': 'meta-llama/Llama-3.1-8B-Instruct', 'prompt': tokens[:16384],
    'max_tokens': 128, 'ignore_eos': True, 'temperature': 0}).encode(), headers={'Content-Type': 'application/json'})
start = time.time()
with urllib.request.urlopen(request, timeout=180) as response:
    result = json.load(response)
assert result['usage']['prompt_tokens'] == 16384
assert result['usage']['completion_tokens'] == 128
proof = {'usage': result['usage'], 'elapsed_s': time.time() - start, 'models': models}
(root / 'long-prompt-preflight.json').write_text(json.dumps(proof, indent=2))
print(json.dumps({'event': 'long-prompt-preflight-passed', **proof}), flush=True)
Episodes(root / 'e0').condition('cached-on-existing-node', 'crossscale-gpu')
