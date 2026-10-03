import fcntl
import json
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
from crossscale.revision_e8 import *

class E8(TestCase):
    def test_plan_traces_and_six_phases(self):
        base=json.loads(Path('configs/revision-20260930.json').read_text())
        p=plan(base);self.assertEqual(p,json.loads(PLAN.read_text()))
        self.assertEqual(len({tuple(x) for x in p['eval_order']}),20)
        for s in SEEDS:
            c,generated,counts=run_config(base,s,.025,.8)
            self.assertEqual([p['start_s'] for p in c['phases']],[0,600,1200,1800,2400,3000])
            self.assertEqual(c['phases'][3]['rates']['C'],4*c['phases'][0]['rates']['C'])
            self.assertTrue(all(counts.values()))
            rows=json.loads((TRACE_DIR/f'seed-{s}.json').read_text())
            e=next(e for e in p['traces'] if e['seed']==s)
            verify_frozen_trace(rows,generated,e['sha256'])

    def test_cost_observer_counts_allocated_idle_gpu_without_granting_slots(self):
        ec2=Mock();ec2.describe_instances.return_value={'Reservations':[{'Instances':[
            dict(InstanceId=i,InstanceType='g5.xlarge',LaunchTime=datetime(2026,1,1,tzinfo=timezone.utc),State={'Name':'running'}) for i in ('i-a','i-b')]}]}
        control=SimpleNamespace(remember_claims=Mock(),ec2=ec2)
        obs=dict(observed_unix_s=100,deployment={'spec':{'replicas':2}},pods=[],nodeclaims=[{'status':{'providerID':i}} for i in ('i-a','i-b')])
        state=LifecycleState(SimpleNamespace(control=control),900)
        out=state(obs)
        self.assertEqual(out['ready'],0)
        self.assertEqual(len(obs['ec2_lifecycle']['instances']),2)
        state(obs);self.assertEqual(ec2.describe_instances.call_count,1)
        self.assertEqual(out['pending_eta_unix_s'],[])

    def test_scaler_down_policy_only_on_owned_object(self):
        obj=object.__new__(LongStudy);obj.k=Mock()
        obj.k.get.return_value={'metadata':{'labels':{'crossscale-experiment':'full-20260908'}}}
        with patch.object(Study,'install_scaler'):
            obj.install_scaler('B6',.8)
        payload=obj.k.patch.call_args.args[2]
        self.assertEqual(payload['spec']['advanced']['horizontalPodAutoscalerConfig']['behavior']['scaleDown'],DOWN)
        obj.k.get.return_value={'metadata':{'labels':{}}}
        with patch.object(Study,'install_scaler'),self.assertRaises(RuntimeError): obj.install_scaler('B6')

    def test_exclusive_lock_blocks_before_any_mutation(self):
        with TemporaryDirectory() as tmp:
            with (Path(tmp)/'suite.lock').open('a') as f:
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): execute(tmp,{})
            self.assertFalse((Path(tmp)/DEST).exists())
