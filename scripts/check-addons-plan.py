"""Restrict the smoke-test apply to the expected add-ons and one-GPU pool."""
import json
from pathlib import Path
import sys


def check(plan):
    expected = {
        'helm_release.karpenter', 'helm_release.device_plugin', 'helm_release.keda',
        'helm_release.prometheus', 'helm_release.gpu_pool',
        'aws_iam_role.model_reader', 'aws_iam_role_policy.model_reader',
        'aws_eks_pod_identity_association.model_reader',
    }
    changes = {r['address']: r['change'] for r in plan['resource_changes'] if r['mode'] == 'managed'}
    if set(changes) != expected:
        raise ValueError('Unexpected add-ons resource set')
    if any(c['actions'] not in (['no-op'], ['create'], ['update']) for c in changes.values()):
        raise ValueError('Deletes/replacements require separate review')
    values = json.loads(changes['helm_release.gpu_pool']['after']['values'][0])
    if values != {'clusterName': 'crossscale', 'nodeRole': 'crossscale-gpu',
                  'amiId': 'ami-0c126bbe79be20f0a', 'gpuLimit': 1}:
        raise ValueError('Expected reviewed one-GPU smoke pool')
    association = changes['aws_eks_pod_identity_association.model_reader']['after']
    if any(association[k] != v for k, v in {
        'cluster_name': 'crossscale', 'namespace': 'crossscale',
        'service_account': 'vllm-model-reader'}.items()):
        raise ValueError('Unexpected reader association')
    print('Verified add-ons scope and one-GPU smoke pool')


if __name__ == '__main__':
    check(json.loads(Path(sys.argv[1]).read_text()))
