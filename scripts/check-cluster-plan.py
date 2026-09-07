"""Reject destructive or out-of-scope changes before a manual cluster apply."""
import json
from pathlib import Path
import sys

ALLOWED_TYPES = {
    'aws_cloudwatch_log_group', 'aws_eks_access_entry', 'aws_eks_access_policy_association',
    'aws_eks_addon', 'aws_eks_cluster', 'aws_iam_role', 'aws_iam_role_policy_attachment',
    'aws_security_group', 'aws_security_group_rule', 'time_sleep', 'aws_cloudwatch_event_rule',
    'aws_cloudwatch_event_target', 'aws_eks_pod_identity_association', 'aws_iam_policy',
    'aws_sqs_queue', 'aws_sqs_queue_policy', 'aws_default_network_acl', 'aws_default_route_table',
    'aws_default_security_group', 'aws_eip', 'aws_internet_gateway', 'aws_nat_gateway',
    'aws_route', 'aws_route_table', 'aws_route_table_association', 'aws_subnet', 'aws_vpc',
    'aws_eks_node_group', 'aws_launch_template', 'null_resource',
}


def check(plan):
    changes = [r for r in plan['resource_changes'] if r['mode'] == 'managed']
    for resource in changes:
        if 'delete' in resource['change']['actions']:
            raise ValueError('Deletes/replacements need a separate reviewed operation')
        if resource['type'] not in ALLOWED_TYPES:
            raise ValueError('Resource type is outside the reviewed cluster scope')
        after = resource['change'].get('after') or {}
        if after.get('region') not in (None, 'us-east-1'):
            raise ValueError('Region must remain us-east-1')
    clusters = [r['change']['after'] for r in changes if r['type'] == 'aws_eks_cluster']
    groups = [r['change']['after'] for r in changes if r['type'] == 'aws_eks_node_group']
    if len(clusters) != 1 or clusters[0]['name'] != 'crossscale' or clusters[0]['version'] != '1.34':
        raise ValueError('Expected one CrossScale EKS 1.34 cluster')
    if len(groups) != 1 or groups[0]['instance_types'] != ['m5.large']:
        raise ValueError('Expected one m5.large system node group')
    if groups[0]['scaling_config'] != [{'desired_size': 2, 'max_size': 2, 'min_size': 2}]:
        raise ValueError('System node group must stay at two nodes')
    print('Scope verified: one EKS cluster, two CPU system nodes, no GPU instances or deletes.')


if __name__ == '__main__':
    check(json.loads(Path(sys.argv[1]).read_text()))
