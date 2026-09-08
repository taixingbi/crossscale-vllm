"""Copy completed profiling artifacts locally without interrupting the runner."""
import io
import json
import subprocess
import zipfile
from pathlib import Path

cmd = ['kubectl', '--kubeconfig', '/tmp/crossscale-continuation-kubeconfig', '-n', 'crossscale']
source = '''import io, sys, zipfile
from pathlib import Path
root = Path('/tmp/profile')
b = io.BytesIO()
with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in root.rglob('*'):
        if f.is_file() and 'crossscale' not in f.parts and '__pycache__' not in f.parts:
            z.write(f, str(f.relative_to(root)))
sys.stdout.buffer.write(b.getvalue())
'''
data = subprocess.check_output(cmd + ['exec', 'crossscale-profile-20260908', '--', 'python', '-c', source], timeout=30)
root = Path(__file__).resolve().parent
with zipfile.ZipFile(io.BytesIO(data)) as z:
    z.extractall(root)
progress = root / 'progress.jsonl'
rows = [json.loads(line) for line in progress.read_text().splitlines()] if progress.exists() else []
print(json.dumps({'completed_runs': len(rows), 'total_runs': 18, 'latest': rows[-1] if rows else None, 'finished': (root / 'report.json').exists()}))
print((root / 'runner.log').read_text().splitlines()[-1])
