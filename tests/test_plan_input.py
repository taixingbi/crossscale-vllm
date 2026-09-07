import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

HELPER = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/plan-input.py'))


class PlanInput(unittest.TestCase):
    def test_private_address_redacted_without_breaking_json(self):
        source = json.dumps({'admin_cidrs': ['198.51.100.7/32'], 'ip': '198.51.100.7'})
        result = HELPER['redact'](source, '198.51.100.7/32')
        self.assertNotIn('198.51.100.7', result)
        self.assertEqual(json.loads(result)['admin_cidrs'], ['REDACTED_ADMIN_CIDR'])

    def test_accept_one_ipv4_address(self):
        with patch.dict('os.environ', {'EKS_ADMIN_CIDR': '198.51.100.7/32'}):
            self.assertEqual(HELPER['admin_cidr'](), '198.51.100.7/32')

    def test_reject_broad_or_malformed_input(self):
        for value in ['0.0.0.0/0', '198.51.100.0/24', '::1/128', 'bad\n::warning::bad']:
            with self.subTest(value=value), patch.dict('os.environ', {'EKS_ADMIN_CIDR': value}):
                with self.assertRaises(ValueError):
                    HELPER['admin_cidr']()
