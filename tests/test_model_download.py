"""Exercise the init-container downloader with a fake AWS CLI."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModelDownloadTests(unittest.TestCase):
    def run_download(self, wrong_size=False, cache=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = root / 'aws'
            cli.write_text('''#!/bin/sh
set -eu
test "$1" = s3api && test "$2" = get-object
previous=
for arg in "$@"; do
  if [ "$previous" = --version-id ]; then test "$arg" = pinned-version; fi
  case "$arg" in *.partial) target=$arg;; esac
  previous=$arg
done
printf x > "$target"
printf x >> "$CALL_LOG"
''')
            cli.chmod(0o700)
            names = ['config.json', 'tokenizer.json', 'tokenizer_config.json',
                     'model.safetensors.index.json'] + [
                         f'model-{n:05d}-of-00004.safetensors' for n in range(1, 5)]
            snapshot = root / 'snapshot.tsv'
            snapshot.write_text(''.join(
                f'{name}\tpinned-version\t{2 if wrong_size else 1}\n' for name in names))
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       MODEL_DIR=str(root / 'model'), SNAPSHOT_FILE=str(snapshot),
                       MODEL_BUCKET='test-bucket', MODEL_PREFIX='inference/test',
                       CALL_LOG=str(root / 'calls'), MODEL_CACHE_ENABLED='1' if cache else '0')
            result = subprocess.run(['sh', str(ROOT / 'deploy/download-model.sh')],
                                    env=env, capture_output=True, text=True)
            if wrong_size:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Size mismatch', result.stderr)
                self.assertFalse((root / 'model/config.json').exists())
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(all((root / 'model' / name).read_bytes() == b'x' for name in names))
                if cache:
                    second = subprocess.run(['sh', str(ROOT / 'deploy/download-model.sh')], env=env, capture_output=True, text=True)
                    self.assertEqual(second.returncode, 0, second.stderr)
                    self.assertEqual(len((root / 'calls').read_bytes()), len(names))
                    (root / 'model' / names[0]).write_bytes(b'broken')
                    repaired = subprocess.run(['sh', str(ROOT / 'deploy/download-model.sh')], env=env, capture_output=True, text=True)
                    self.assertEqual(repaired.returncode, 0, repaired.stderr)
                    self.assertEqual(len((root / 'calls').read_bytes()), len(names) + 1)
                    self.assertEqual((root / 'model' / names[0]).read_bytes(), b'x')

    def test_downloads_pinned_versions(self):
        self.run_download()

    def test_rejects_truncated_object(self):
        self.run_download(wrong_size=True)

    def test_reuses_pinned_cache_and_repairs_wrong_size(self):
        self.run_download(cache=True)
