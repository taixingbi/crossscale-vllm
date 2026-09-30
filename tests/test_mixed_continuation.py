import json
from pathlib import Path
import tempfile
import unittest
from crossscale.revision_mixed_live import remaining_after_observer_failure

class ContinuationTests(unittest.TestCase):
    def test_only_unstarted_and_restored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            frozen = {'runs': [{'name': str(i)} for i in range(30)]}
            for name, data in [('frozen-plan.json', frozen), ('error.json', {}), ('restored.json', {})]:
                (p/name).write_text(json.dumps(data))
            for i in range(28):
                q = p/str(i); q.mkdir()
                if i < 27:
                    (q/'complete.json').write_text(json.dumps({'name': str(i)}))
                else:
                    (q/'observer-error.json').write_text('{}')
                    (q/'run').mkdir(); (q/'run'/'requests.jsonl').touch()
            self.assertEqual([r['name'] for r in remaining_after_observer_failure(p, frozen)], ['28', '29'])
            (p/'28').mkdir()
            with self.assertRaises(ValueError): remaining_after_observer_failure(p, frozen)
            (p/'28').rmdir(); (p/'restored.json').unlink()
            with self.assertRaises(ValueError): remaining_after_observer_failure(p, frozen)
