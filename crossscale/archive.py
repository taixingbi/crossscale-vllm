"""Checkpoint closed experiment artifacts to a dedicated private S3 prefix."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from .episodes import save


def eligible(path, root):
    if not path.is_file() or path.is_symlink():
        return False
    relative = path.relative_to(root)
    if '__pycache__' in relative.parts or path.suffix in ('.tmp', '.lock', '.pyc'):
        return False
    if path.name == 'archive-status.json' or path.name.startswith('archive.log'):
        return False
    if path.name == 'observations.jsonl.gz':
        return any((path.parent / name).exists() for name in ('summary.json', 'complete.json', 'observer-error.json'))
    return True


def main():
    import boto3
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--bucket', required=True)
    p.add_argument('--prefix', required=True)
    args = p.parse_args()
    root = Path(args.root)
    s3 = boto3.client('s3', region_name='us-east-1')
    uploaded = {}
    while True:
        try:
            progress = {'unix_s': time.time(), 'e0': {}, 'workers': {}}
            for condition in ('cached-on-existing-node', 'cold-new-node', 'prebaked-image-new-node'):
                summaries = [json.loads(p.read_text()) for p in (root/'e0'/condition).glob('episode-*/summary.json')]
                progress['e0'][condition] = {'recorded': len(summaries), 'planned': 30,
                                             'errors': sum(s.get('error') is not None for s in summaries)}
            log = root/'e0'/'events.jsonl'
            if log.exists():
                for line in reversed(log.read_text().splitlines()):
                    try:
                        progress['last_event'] = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            for name in ('cached', 'study', 'archive'):
                pidfile = root/(name+'.pid')
                if pidfile.exists():
                    pid = pidfile.read_text().strip()
                    stat = Path('/proc')/pid/'stat'
                    progress['workers'][name] = {'pid': pid, 'state': stat.read_text().rsplit(')', 1)[1].split()[0] if stat.exists() else 'exited'}
            save(root/'progress.json', progress)
            count = 0
            for path in sorted(root.rglob('*')):
                if not eligible(path, root):
                    continue
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                if uploaded.get(str(path)) == signature:
                    continue
                # Atomic status-file replacement can change the pathname between
                # upload_file's size check and open. Upload an immutable snapshot.
                with tempfile.TemporaryFile() as snapshot:
                    with path.open('rb') as source:
                        shutil.copyfileobj(source, snapshot)
                    snapshot.seek(0)
                    s3.upload_fileobj(snapshot, args.bucket, args.prefix.rstrip('/') + '/' + str(path.relative_to(root)))
                # If an active log changes during upload, upload it again next pass.
                uploaded[str(path)] = signature
                count += 1
            save(root/'archive-status.json', {'unix_s': time.time(), 'uploaded_this_pass': count, 'tracked_files': len(uploaded), 'error': None})
        except Exception as exc:
            save(root/'archive-status.json', {'unix_s': time.time(), 'error': repr(exc)})
            print(json.dumps({'error': repr(exc)}), flush=True)
        time.sleep(60)


if __name__ == '__main__':
    main()
