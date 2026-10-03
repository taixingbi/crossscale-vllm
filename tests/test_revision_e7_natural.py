import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from crossscale.revision_e7_natural import plan, execute, require_controlled, CONTROLLED_DEST, DEST, VARIANTS
from crossscale.revision_e5 import run_config, verify_frozen_trace

class NaturalE7(TestCase):
    def setUp(self):
        self.base=json.loads(Path('configs/revision-20260930.json').read_text())
        self.source=json.loads(Path('configs/revision-20261001-e5-plan.json').read_text())

    def test_paired_frozen_traces_and_no_false_natural_oracle(self):
        p=plan(self.base,self.source)
        self.assertEqual(p,json.loads(Path('configs/revision-20261003-e7-natural-plan.json').read_text()))
        self.assertEqual(len({tuple(x) for x in p['eval_order']}),20)
        self.assertEqual(set(p['baselines']),{'B3','B5','no-tenant','B6'})
        for e in p['traces']:
            rows=json.loads(Path(f"configs/revision-20261001-e5-traces/seed-{e['seed']}.json").read_text())
            self.assertEqual(verify_frozen_trace(rows,run_config(self.base,e['seed'],.025,.8)[1],e['sha256']),rows)

    def test_controlled_completion_restore_and_uniqueness(self):
        seeds=self.source['eval_seeds']
        with TemporaryDirectory() as tmp:
            d=Path(tmp)/CONTROLLED_DEST; d.mkdir(parents=True)
            rows=[dict(seed=s,variant=v[0],dispatch_valid=True) for s in seeds for v in VARIANTS]
            (d/'complete.json').write_text(json.dumps(dict(results=rows)))
            with self.assertRaises(RuntimeError): require_controlled(tmp,seeds)
            (d/'restored.json').write_text('{}')
            require_controlled(tmp,seeds)
            rows[-1]=rows[0]
            (d/'complete.json').write_text(json.dumps(dict(results=rows)))
            with self.assertRaises(RuntimeError): require_controlled(tmp,seeds)

    def test_active_suite_blocks_before_reads_or_mutation(self):
        with TemporaryDirectory() as tmp:
            with (Path(tmp)/'suite.lock').open('a') as f:
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): execute(tmp,{})
            self.assertFalse((Path(tmp)/DEST).exists())
