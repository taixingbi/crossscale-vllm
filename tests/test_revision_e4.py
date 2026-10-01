import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crossscale import revision_e4 as e4


class NoisyNeighbor(TestCase):
    def test_only_c_rate_changes_and_traces_are_paired(self):
        base = json.loads(Path('configs/revision-20260930.json').read_text())
        frozen = e4.plan(base, .025)
        self.assertEqual(len(frozen['eval_order']), 15)
        self.assertEqual(len({tuple(x) for x in frozen['eval_order']}), 15)
        for seed in frozen['eval_seeds']:
            config, rows, counts = e4.run_config(base, seed, .025, .8)
            self.assertTrue(all(counts.values()))
            rates = [p['rates'] for p in config['phases']]
            for tenant in ('A', 'B'):
                self.assertEqual(len({r[tenant] for r in rates}), 1)
            self.assertEqual(rates[1]['C'], 4 * rates[0]['C'])
            self.assertEqual(rates[0], rates[2])
            self.assertEqual(rows, e4.run_config(base, seed, .025, 1.2)[1])
            self.assertEqual(config['tenants'], base['tenants'])
            self.assertEqual(config['admission_policy_revision'], 'revision-20260912')

    def test_active_suite_and_unfinished_e3_block_launch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / 'suite.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    e4.execute(root, {})
            with self.assertRaisesRegex(RuntimeError, 'complete and restore'):
                e4.execute(root, {})
            self.assertFalse((root / e4.DEST).exists())

    def test_invalid_predecessor_is_not_accepted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, baselines in ((e4.comparison.DEST, ('B3', 'B5', 'B6')),
                                        (e4.EXTENSION_DEST, ('B2', 'B4'))):
                dest = root / relative
                dest.mkdir(parents=True)
                (dest / 'restored.json').write_text('{}')
                records = [dict(seed=s, baseline=b, dispatch_valid=True)
                           for s in (821, 822, 824, 826, 828) for b in baselines]
                (dest / 'complete.json').write_text(json.dumps(dict(results=records)))
            e4.require_completed_e3(root)
            records[0]['dispatch_valid'] = False
            (dest / 'complete.json').write_text(json.dumps(dict(results=records)))
            with self.assertRaisesRegex(RuntimeError, 'dispatch-invalid'):
                e4.require_completed_e3(root)
