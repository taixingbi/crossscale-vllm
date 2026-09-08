import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('readiness', Path(__file__).resolve().parents[1] / 'scripts/wait-model-ready.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReadinessTests(unittest.TestCase):
    def test_pending_download_can_continue(self):
        self.assertFalse(mod.inspect({'status': {'initContainerStatuses': [
            {'name': 'download-model', 'state': {'running': {}}, 'restartCount': 0}]}})[0])

    def test_repeated_oom_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'OOMKilled'):
            mod.inspect({'status': {'containerStatuses': [{'name': 'vllm', 'restartCount': 2,
                'state': {'waiting': {'reason': 'CrashLoopBackOff'}},
                'lastState': {'terminated': {'reason': 'OOMKilled', 'exitCode': 137}}}]}})

    def test_ready(self):
        self.assertTrue(mod.inspect({'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}})[0])
