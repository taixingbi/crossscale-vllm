import json
from pathlib import Path
import tempfile
import unittest

from crossscale.revision_amendment import (
    AMENDED_B_TTFT_S,
    amended_config,
    requalify_mixed,
)
from crossscale.revision_mixed import plan


class AmendmentTests(unittest.TestCase):
    def test_amended_config_only_changes_b_ttft(self):
        base = json.loads(Path('configs/default.json').read_text())
        config = amended_config(base)
        self.assertEqual(config['tenants']['B']['ttft_s'], AMENDED_B_TTFT_S)
        self.assertEqual(config['tenants']['A']['ttft_s'], 0.5)
        self.assertEqual(config['tenants']['C']['ttft_s'], 5)
        self.assertEqual(base['tenants']['B']['ttft_s'], 1.5)
        with self.assertRaises(ValueError):
            amended_config(config)

    def test_requalify_uses_existing_traces_and_skips_observer_failure(self):
        base = json.loads(Path('configs/default.json').read_text())
        frozen = plan(base, [.01, .025])
        ledger = dict(qualified_capacity={'1': None, '2': None}, runs=[])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for spec in frozen['runs']:
                failed = spec['replicas'] == 2 and spec['rps'] == .01 and spec['seed'] == 703
                entry = dict(name=spec['name'], outcome='failed_observer' if failed else 'completed',
                             path='mixed/' + spec['name'])
                ledger['runs'].append(entry)
                folder = root / entry['path'] / 'run'
                folder.mkdir(parents=True)
                if failed:
                    continue
                ttft = 2.8 if spec['seed'] == 704 and spec['rps'] == .01 else 0.2
                rows = []
                for tenant, n in spec['offered_by_tenant'].items():
                    for i in range(n):
                        rows.append(dict(
                            id=i, tenant=tenant, offered_s=i, input_tokens=256, output_tokens=8,
                            status='completed', dispatch_lag_s=0.001, ttft_s=ttft if tenant == 'B' else 0.1,
                            tpot_s=0.01, actual_output_tokens=8))
                (folder / 'requests.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            config = amended_config(base)
            result = requalify_mixed(root, config, frozen, ledger)
            self.assertEqual(result['qualified_capacity']['1'], 0.025)
            self.assertIsNone(result['qualified_capacity']['2'])
            skipped = [r for r in result['runs'] if r['outcome'] == 'failed_observer']
            self.assertEqual(len(skipped), 1)
            self.assertFalse(skipped[0]['passed'])
            seed704 = [r for r in result['runs'] if r['seed'] == 704 and r['replicas'] == 1][0]
            self.assertTrue(seed704['passed'])
            self.assertEqual(seed704['tenants']['B'], 1.0)
