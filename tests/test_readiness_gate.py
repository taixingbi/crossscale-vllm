import copy
from unittest import TestCase
from crossscale.readiness_gate import (
    CONDITION, OWNER_LABEL, condition_patch, release_schedule, desired_release,
)


class ReadinessGate(TestCase):
    def pod(self):
        return dict(metadata=dict(name='test', uid='u0', resourceVersion='123',
                                  labels={OWNER_LABEL: 'validation'}),
                    spec=dict(readinessGates=[dict(conditionType=CONDITION)]),
                    status=dict(conditions=[dict(type='ContainersReady', status='False')]))

    def test_schedule_never_releases_pending_early(self):
        pods = [dict(metadata=dict(uid=f'u{i}')) for i in range(4)]
        for lag in (0, 15, 30, 60, 90, 120):
            schedule = release_schedule(pods, ['u0', 'u1'], 1000 + lag)
            self.assertTrue(desired_release(schedule, 'u0', 999))
            self.assertFalse(desired_release(schedule, 'u2', 1000 + lag - .001))
            self.assertTrue(desired_release(schedule, 'u2', 1000 + lag))
            with self.assertRaises(ValueError):
                desired_release(schedule, 'replacement', 9999)

    def test_preserves_health_and_optimistic_concurrency(self):
        pod = self.pod()
        before = copy.deepcopy(pod)
        patch = condition_patch(pod, 'validation', True, 1000)
        self.assertEqual(pod, before)
        self.assertEqual(patch['metadata'], dict(uid='u0', resourceVersion='123'))
        self.assertEqual(patch['status']['conditions'][0],
                         dict(type='ContainersReady', status='False'))
        pod['status'] = patch['status']
        self.assertIsNone(condition_patch(pod, 'validation', True, 2000))
        self.assertEqual(condition_patch(pod, 'validation', False, 2000)
                         ['status']['conditions'][-1]['status'], 'False')

    def test_refuses_unowned_or_ungated_pods(self):
        with self.assertRaises(ValueError):
            condition_patch(self.pod(), 'other-run', True, 1000)
        pod = self.pod()
        pod['spec']['readinessGates'] = []
        with self.assertRaises(ValueError):
            condition_patch(pod, 'validation', True, 1000)
        pod = self.pod()
        pod['metadata']['deletionTimestamp'] = 'now'
        with self.assertRaises(ValueError):
            condition_patch(pod, 'validation', True, 1000)
