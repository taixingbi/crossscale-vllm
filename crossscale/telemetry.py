"""Export raw Prometheus range queries with explicit run boundaries."""
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

QUERIES = {
    'waiting': 'sum(vllm:num_requests_waiting{namespace="crossscale"})',
    'running': 'sum(vllm:num_requests_running{namespace="crossscale"})',
    'kv_cache': 'vllm:kv_cache_usage_perc{namespace="crossscale"}',
    'gpu_utilization': 'DCGM_FI_DEV_GPU_UTIL{namespace="crossscale"}',
    'desired': 'kube_deployment_spec_replicas{namespace="crossscale",deployment="vllm"}',
    'ready': 'kube_deployment_status_replicas_available{namespace="crossscale",deployment="vllm"}',
    'slo_saturation': 'crossscale_slo_saturation{job="crossscale-gateway"}'
}


def collect(url, start, end, step, out, queries=None):
    if not start < end or step <= 0:
        raise ValueError('end must follow start and step must be positive')
    p = Path(out)
    p.mkdir(parents=True, exist_ok=False)
    missing = []
    for name, query in (queries or QUERIES).items():
        params = urlencode(dict(query=query, start=start, end=end, step=step))
        with urlopen(url.rstrip('/')+'/api/v1/query_range?'+params, timeout=30) as response:
            data = json.load(response)
        if data.get('status') != 'success':
            raise ValueError(f'Prometheus failed: {name}')
        if not data['data']['result']:
            missing.append(name)
        # Persist names under our own sequence to avoid query-file path traversal.
        file = p/f'query-{len(list(p.glob("query-*.json"))):02d}.json'
        file.write_text(json.dumps(dict(name=name, query=query, response=data)))
    (p/'manifest.json').write_text(json.dumps(dict(start=start, end=end, step=step, missing_series=missing)))
    return dict(missing_series=missing, out=str(p))
