"""Allow deletion only of the reviewed CrossScale state snapshot."""
import json
from pathlib import Path
import sys

plan = json.loads(Path(sys.argv[1]).read_text())
expected = json.loads(Path('infra/cluster/destroy-scope.json').read_text())
count = 0
for change in plan.get('resource_changes', []):
    if change.get('mode') != 'managed':
        continue
    address = change['address']
    delta = change['change']
    if address not in expected or (delta.get('before') or {}).get('id') != expected[address]:
        raise SystemExit('Unreviewed resource: ' + address)
    if delta['actions'] not in (['delete'], ['no-op']):
        raise SystemExit('Unexpected action: ' + address)
    count += delta['actions'] == ['delete']
print(f'Validated destruction of {count} reviewed CrossScale resources.')
