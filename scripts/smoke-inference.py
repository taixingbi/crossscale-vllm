"""Verify the local port-forward serves the selected model and metrics."""
import json
import time
import urllib.request

BASE = 'http://127.0.0.1:18000'
MODEL = 'meta-llama/Llama-3.1-8B-Instruct'
for attempt in range(30):
    try:
        with urllib.request.urlopen(BASE + '/health', timeout=5) as response:
            assert response.status == 200
        break
    except OSError:
        if attempt == 29:
            raise
        time.sleep(2)
with urllib.request.urlopen(BASE + '/v1/models', timeout=10) as response:
    assert MODEL in [m['id'] for m in json.load(response)['data']]
request = urllib.request.Request(BASE + '/v1/chat/completions', data=json.dumps({
    'model': MODEL, 'messages': [{'role': 'user', 'content': 'Reply with one short greeting.'}],
    'max_tokens': 32, 'temperature': 0,
}).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=180) as response:
    result = json.load(response)
    assert result['choices'][0]['message']['content'].strip()
    print('Inference passed:', result['choices'][0]['message']['content'])
with urllib.request.urlopen(BASE + '/metrics', timeout=10) as response:
    assert 'vllm:' in response.read().decode()
print('Model identity, inference, and vLLM metrics verified')
