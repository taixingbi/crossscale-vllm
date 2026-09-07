"""Exercise the role wrapper with a fake AWS CLI; no AWS account is contacted."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/with-aws-role.sh'


class AssumeRole(unittest.TestCase):
    def run_wrapper(self, target, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            aws = Path(directory) / 'aws'
            aws.write_text('''#!/bin/bash
[ "$AWS_PROFILE" = source ] || exit 90
printf '%s\\n' "$@" > "$CALL_LOG"
[ "$FAIL_STS" = 0 ] || exit 42
printf 'test-key\\ttest-secret\\ttest-token\\n'
''')
            aws.chmod(0o755)
            log = Path(directory) / 'args'
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'],
                       AWS_PROFILE='source', AWS_DEFAULT_PROFILE='source',
                       CALL_LOG=str(log), FAIL_STS='1' if fail else '0')
            command = ['bash', '-c', '''
[ "$AWS_ACCESS_KEY_ID" = test-key ] || exit 91
[ "$AWS_SECRET_ACCESS_KEY" = test-secret ] || exit 92
[ "$AWS_SESSION_TOKEN" = test-token ] || exit 93
[ -z "${AWS_PROFILE:-}" ] || exit 94
[ -z "${AWS_DEFAULT_PROFILE:-}" ] || exit 95
printf '%s' "$1"
''', 'child', 'argument with spaces']
            result = subprocess.run([str(SCRIPT), target, *command], env=env,
                                    capture_output=True, text=True)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_member_account_and_shared_credentials(self):
        result, args = self.run_wrapper('123456789012')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'argument with spaces')
        self.assertIn('arn:aws:iam::123456789012:role/OrganizationAccountAccessRole', args)
        self.assertNotIn('test-secret', result.stdout + result.stderr)

    def test_explicit_role(self):
        arn = 'arn:aws:iam::123456789012:role/team/crossscale'
        result, args = self.run_wrapper(arn)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(arn, args)

    def test_failed_assumption_does_not_run_command(self):
        result, _ = self.run_wrapper('123456789012', fail=True)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(result.stdout, '')

    def test_invalid_target_does_not_call_aws(self):
        result, args = self.run_wrapper('not-an-account')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(args, [])
