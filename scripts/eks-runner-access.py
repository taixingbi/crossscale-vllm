"""Temporarily allow one CI runner IPv4; restore the original EKS allowlist."""
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def aws(*args):
    return json.loads(subprocess.check_output(['aws', 'eks', *args, '--region', 'us-east-1', '--output', 'json']))


def set_cidrs(cidrs):
    update = aws('update-cluster-config', '--name', 'crossscale', '--resources-vpc-config',
                 json.dumps({'publicAccessCidrs': cidrs}))['update']['id']
    for _ in range(90):
        result = aws('describe-update', '--name', 'crossscale', '--update-id', update)['update']
        if result['status'] == 'Successful':
            return
        if result['status'] in ('Failed', 'Cancelled'):
            raise RuntimeError('EKS access update failed; inspect the update in AWS')
        time.sleep(10)
    raise TimeoutError('EKS access update did not complete')


def main():
    saved = Path(os.environ['RUNNER_TEMP']) / 'original-eks-cidrs.json'
    if sys.argv[1] == 'open':
        ip = str(ipaddress.IPv4Address(urllib.request.urlopen('https://checkip.amazonaws.com', timeout=20).read().decode().strip()))
        print('::add-mask::' + ip, flush=True)
        cidrs = aws('describe-cluster', '--name', 'crossscale')['cluster']['resourcesVpcConfig']['publicAccessCidrs']
        for cidr in cidrs:
            print('::add-mask::' + cidr.split('/')[0], flush=True)
        saved.touch(mode=0o600)
        saved.write_text(json.dumps(cidrs))
        set_cidrs(sorted(set(cidrs + [ip + '/32'])))
        print('Temporary runner access ready')
    elif sys.argv[1] == 'close':
        if saved.exists():
            cidrs = json.loads(saved.read_text())
            for cidr in cidrs:
                print('::add-mask::' + cidr.split('/')[0], flush=True)
            set_cidrs(cidrs)
            print('Original EKS allowlist restored')
    else:
        raise ValueError('Expected open or close')


if __name__ == '__main__':
    main()
