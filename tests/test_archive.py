import tempfile
from pathlib import Path
import unittest

from crossscale.archive import eligible


class Checkpoint(unittest.TestCase):
    def test_observer_is_uploaded_only_after_closure_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            raw = root / 'observations.jsonl.gz'
            raw.write_bytes(b'partial')
            self.assertFalse(eligible(raw, root))
            (root/'summary.json').write_text('{}')
            self.assertTrue(eligible(raw, root))
            temporary = root/'state.json.tmp'
            temporary.write_text('{}')
            self.assertFalse(eligible(temporary, root))
