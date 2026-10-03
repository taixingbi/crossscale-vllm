import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from crossscale.revision_e7_continuation import plan, variant_map, require_predecessor
from crossscale.revision_e7 import DEST

class Continuation(TestCase):
    def test_only_unattempted_cells_and_live_supported_policy(self):
        base=json.loads(Path('configs/revision-20260930.json').read_text())
        p=plan(base)
        self.assertEqual(p,json.loads(Path('configs/revision-20261003-e7-continuation-plan.json').read_text()))
        self.assertEqual(len(p['eval_order']),23)
        self.assertNotIn([872,'B3'],p['eval_order'])
        self.assertNotIn([874,'Oracle'],p['eval_order'])
        self.assertEqual(variant_map()['Oracle'],('B6','oracle'))

    def test_exact_failure_restore_and_no_measurement_guard(self):
        with TemporaryDirectory() as tmp:
            d=Path(tmp)/DEST
            good=d/'eval/seed-872/B3';good.mkdir(parents=True)
            bad=d/'eval/seed-874/Oracle';bad.mkdir(parents=True)
            (d/'error.json').write_text(json.dumps(dict(error="RuntimeError('Gateway startup failed')")))
            (good/'complete.json').write_text(json.dumps(dict(seed=872,variant='B3',dispatch_valid=True)))
            (bad/'gateway.log').write_text('oracle ETA is simulation-only')
            with self.assertRaises(RuntimeError): require_predecessor(tmp)
            (d/'restored.json').write_text('{}')
            require_predecessor(tmp)
            (bad/'run').mkdir()
            with self.assertRaises(RuntimeError): require_predecessor(tmp)
