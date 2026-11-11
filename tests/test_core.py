"""Offline tests: these do NOT claim a running Kubernetes cluster."""
import asyncio
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
# Also runnable from the built image, where modules are already in /app.
if not (Path(__file__).resolve().parents[1]/'app').exists(): sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bank import BANK,DOMAINS,set_tasks
from runtime import Runner,Result,Grader,InfrastructureError,quantity,select,compare,subset,equal,is_ready
from manager import Manager,BusyError
from bootstrap import CRD

KINDS={'inventory','rollout_history','rbac_rules','resource','ready','job_complete','exec','logs','file','yaml_file','render','endpoints','http','http_endpoints','http_external','http_nodeport','traffic','auth','admission_denied','helm','metrics_file','image','image_base','image_same','image_file','image_archive'}

class BankTests(unittest.TestCase):
    def test_bank_count_and_domain_coverage(self):
        self.assertEqual(len(BANK),66)
        self.assertEqual(len(set_tasks('core')),20)
        self.assertEqual(Counter(t['domain'] for t in set_tasks('core')),{'design':4,'deployment':4,'observability':3,'configuration':5,'networking':4})
        self.assertEqual(sum(d['weight'] for d in DOMAINS.values()),100)
    def test_all_criterion_kinds_have_an_implementation(self):
        self.assertEqual({c['kind'] for t in BANK.values() for c in t['checks']},KINDS)
    def test_namespaces_are_unique_and_disposable(self):
        names=[name for t in BANK.values() for name in [t['namespace']]+[x['name'] for x in t['extra_namespaces']]]
        self.assertEqual(len(names),len(set(names)))
        self.assertTrue(all(re.fullmatch(r'ckad-[a-z0-9-]+',n) for n in names))
    def test_crd_schema_is_structural(self):
        spec=CRD['spec'];self.assertEqual(spec['scope'],'Namespaced')
        schema=spec['versions'][0]['schema']['openAPIV3Schema']
        self.assertEqual(schema['type'],'object');self.assertEqual(schema['properties']['spec']['required'],['image','replicas'])
    def test_compose_persists_each_node_identity_separately(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        if not (root/'compose.yaml').exists(): self.skipTest('Compose source is outside the image')
        compose=yaml.safe_load((root/'compose.yaml').read_text())
        identities=[]
        for service in ('cluster','worker'):
            mounts=[v for v in compose['services'][service]['volumes'] if isinstance(v,str) and v.endswith(':/etc/rancher/node')]
            self.assertEqual(len(mounts),1,service)
            identity=mounts[0].split(':')[0]
            self.assertIn(identity,compose['volumes'])
            identities.append(identity)
        self.assertEqual(len(set(identities)),2)

    def test_compose_has_no_host_socket_or_kubeconfig(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        if not (root/'compose.yaml').exists(): self.skipTest('Compose source is outside the image')
        compose=yaml.safe_load((root/'compose.yaml').read_text())
        self.assertEqual(set(compose['services']),{'cluster','worker','builder','app'})
        ports=[p for s in compose['services'].values() for p in s.get('ports',[])]
        self.assertEqual(len(ports),1);self.assertTrue(ports[0].startswith('127.0.0.1:'))
        self.assertNotIn('/var/run/docker.sock:',(root/'compose.yaml').read_text())

def make_task_test(t):
    def test(self):
        import yaml
        self.assertEqual(t['id'],t['workspace'].split('/')[-1]);self.assertEqual(t['namespace'],'ckad-'+t['id'])
        self.assertGreater(len(t['requirements']),1);self.assertGreater(len(t['checks']),1)
        self.assertNotIn('kubectl config ', t['solution'])
        self.assertNotIn('cd /workspace/', t['solution'])
        self.assertTrue(t['docs']);self.assertTrue(t['explanation']);self.assertTrue(t['hints'])
        syntax=subprocess.run(['bash','-n'],input=t['solution'],text=True,capture_output=True)
        self.assertEqual(syntax.returncode,0,syntax.stderr)
        for f in t['files']:
            self.assertFalse(Path(f).is_absolute());self.assertNotIn('..',Path(f).parts)
        for doc in t['seeds']+t['final']:
            self.assertEqual(yaml.safe_load(yaml.safe_dump(doc)),doc)
            self.assertIn('apiVersion',doc);self.assertIn('kind',doc);self.assertIn('name',doc['metadata'])
            if doc['kind'] in ('Deployment','DaemonSet','StatefulSet'):
                self.assertEqual(doc['apiVersion'],'apps/v1')
                labels=doc['spec']['template']['metadata']['labels']
                self.assertTrue(subset(labels,doc['spec']['selector']['matchLabels']))
            if doc['kind']=='Ingress':self.assertEqual(doc['apiVersion'],'networking.k8s.io/v1')
            if doc['kind'] in ('Job','CronJob'):self.assertEqual(doc['apiVersion'],'batch/v1')
        for c in t['checks']:
            self.assertIn(c['kind'],KINDS);self.assertTrue(c['label'])
    return test
for tid,t in BANK.items():setattr(BankTests,'test_task_'+tid,make_task_test(t))

class ComparisonTests(unittest.TestCase):
    def test_cpu_decimal_equivalence(self):self.assertEqual(quantity('100m'),quantity('0.1'))
    def test_cpu_integer_equivalence(self):self.assertEqual(quantity('1000m'),quantity('1'))
    def test_memory_binary_equivalence(self):self.assertEqual(quantity('1Gi'),quantity('1024Mi'))
    def test_memory_decimal_is_not_binary(self):self.assertNotEqual(quantity('1G'),quantity('1Gi'))
    def test_nano_cpu(self):self.assertEqual(quantity('100000000n'),Decimal('.1'))
    def test_exponents(self):self.assertEqual(quantity('1e3'),quantity('1k'))
    def test_invalid_quantities(self):
        for x in ('many','1MB','1foo',None,True,'NaN','Infinity'):
            with self.subTest(x=x),self.assertRaises(ValueError):quantity(x)
    def test_command_order_matters(self):self.assertFalse(subset({'command':['echo','hello']},{'command':['hello','echo']}))
    def test_rbac_verb_order_does_not_matter(self):self.assertTrue(subset({'verbs':['watch','get','list']},{'verbs':['get','list','watch']}))
    def test_policy_direction_order_does_not_matter(self):self.assertTrue(equal({'policyTypes':['Egress','Ingress']},{'policyTypes':['Ingress','Egress']}))
    def test_command_argument_values_must_all_match(self):self.assertFalse(subset(['sh','-c','wrong'],['sh','-c','right']))
    def test_named_containers_can_be_reordered(self):self.assertTrue(subset([{'name':'b'},{'name':'a'}],[{'name':'a'},{'name':'b'}]))
    def test_duplicate_expected_objects_do_not_reuse_one_actual(self):self.assertFalse(subset([{'name':'a'},{'name':'b'}],[{'name':'a'},{'name':'a'}]))
    def test_subset_allows_api_defaults(self):self.assertTrue(subset({'name':'http','port':80,'protocol':'TCP'},{'port':80}))
    def test_equality_rejects_extra_policy_peers(self):self.assertFalse(equal({'from':[{'podSelector':{}},{'namespaceSelector':{}}]},{'from':[{'podSelector':{}}]}))
    def test_booleans_are_not_numbers(self):self.assertFalse(equal(True,1));self.assertFalse(equal(1,True))
    def test_select_by_container_name(self):self.assertEqual(select({'c':[{'name':'a','image':'x'},{'name':'b','image':'y'}]},['c',{'name':'b'},'image']),'y')
    def test_select_dotted_nested_name(self):self.assertEqual(select([{'metadata':{'name':'x'},'spec':{'n':1}}],[{'metadata.name':'x'},'spec','n']),1)
    def test_ambiguous_selector_fails(self):self.assertIsNone(select([{'name':'x'},{'name':'x'}],[{'name':'x'}]))
    def test_missing_path_fails(self):self.assertIsNone(select({},['spec','containers',0]))
    def test_quantity_op_handles_invalid_as_unmet(self):self.assertFalse(compare('wrong','1Gi','quantity'))
    def test_source_requests_accept_equivalent_or_larger_quantities(self):
        self.assertTrue(compare('200m','100m','at_least_quantity'))
        self.assertTrue(compare('0.125Gi','128Mi','at_least_quantity'))
        self.assertFalse(compare('64Mi','128Mi','at_least_quantity'))
        self.assertFalse(compare('invalid','128Mi','at_least_quantity'))
    def test_path_type_can_be_one_of_valid_choices(self):
        options=['Prefix','Exact','ImplementationSpecific']
        self.assertTrue(all(compare(value,options,'one_of') for value in options))
        self.assertFalse(compare('InvalidType',options,'one_of'))
    def test_exact_empty_list_is_not_nonempty_list(self):self.assertFalse(subset([{}],[]))
    def test_nonempty_rejects_headless_service(self):self.assertFalse(compare('None',True,'nonempty'))

class ReadinessTests(unittest.TestCase):
    def test_pod_requires_running_and_ready(self):
        p={'kind':'Pod','status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}}
        self.assertTrue(is_ready(p));p['status']['phase']='Failed';self.assertFalse(is_ready(p))
    def test_pending_is_not_ready(self):self.assertFalse(is_ready({'kind':'Pod','status':{'phase':'Pending'}}))
    def test_old_generation_is_not_completed_rollout(self):
        d={'kind':'Deployment','metadata':{'generation':3},'spec':{'replicas':2},'status':{'observedGeneration':2,'replicas':2,'updatedReplicas':2,'availableReplicas':2}}
        self.assertFalse(is_ready(d));d['status']['observedGeneration']=3;self.assertTrue(is_ready(d))
    def test_old_available_replicas_do_not_hide_failed_update(self):
        self.assertFalse(is_ready({'kind':'Deployment','metadata':{'generation':2},'spec':{'replicas':2},'status':{'observedGeneration':2,'replicas':3,'updatedReplicas':1,'availableReplicas':2}}))
    def test_daemonset_needs_updated_nodes(self):
        self.assertFalse(is_ready({'kind':'DaemonSet','metadata':{'generation':2},'status':{'observedGeneration':2,'desiredNumberScheduled':2,'numberReady':2,'updatedNumberScheduled':1}}))
    def test_zero_replicas_cannot_pass_healthy_workload(self):
        self.assertFalse(is_ready({'kind':'Deployment','spec':{'replicas':0},'status':{'observedGeneration':1}}))

class PersistenceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.m=Manager(Runner(workspace=str(self.root/'workspace')),self.root/'state')
    def tearDown(self):self.temp.cleanup()
    def test_exact_weighting_across_many_seeds(self):
        for seed in range(250):
            ids=self.m.choose_exam(str(seed));self.assertEqual(len(ids),20);self.assertEqual(len(set(ids)),20)
            self.assertEqual(Counter(BANK[x]['domain'] for x in ids),{'design':4,'deployment':4,'observability':3,'configuration':5,'networking':4})
    def test_same_seed_repeats_selection(self):self.assertEqual(self.m.choose_exam('abc'),self.m.choose_exam('abc'))
    def test_full_score_is_100(self):self.assertEqual(self.m.exam_score({str(x):{'earned':4,'possible':4} for x in range(20)}),100)
    def test_partial_credit_per_task(self):self.assertEqual(self.m.exam_score({'x':{'earned':2,'possible':4}}),2.5)
    def test_notes_survive_reload(self):
        self.m.save_notes('d01','Remember namespace',True);other=Manager(self.m.runner,self.root/'state');self.assertEqual(other.state['practice']['d01']['notes'],'Remember namespace');self.assertTrue(other.state['practice']['d01']['flagged'])
    def test_notes_are_size_limited(self):self.m.save_notes('d01','x'*13000);self.assertEqual(len(self.m.state['practice']['d01']['notes']),12000)
    def test_running_exam_deadline_survives_reload(self):
        self.m.state['exam']={'state':'running','deadline':1234,'tasks':['d01']};self.m.save();other=Manager(self.m.runner,self.root/'state');self.assertEqual(other.state['exam']['deadline'],1234);self.assertTrue(other.locked())
    def test_restart_during_grading_invalidates_attempt(self):
        self.m.state['exam']={'state':'grading'};self.m.save();other=Manager(self.m.runner,self.root/'state');self.assertEqual(other.state['exam']['state'],'interrupted')
    def test_corrupt_state_is_preserved_and_not_trusted(self):
        self.m.path.write_text('not json');other=Manager(self.m.runner,self.root/'state');self.assertEqual(other.state['practice'],{});self.assertEqual(len(list((self.root/'state').glob('state-unreadable-*'))),1)
    def test_hidden_solutions_are_not_in_state(self):
        t=self.m.snapshot()['tasks'][0];self.assertNotIn('solution',t);self.assertNotIn('checks',t);self.assertNotIn('hints',t)
    def test_exam_hides_old_grades(self):
        self.m.state['practice']['d01']={'last_grade':{'percent':100}};self.m.state['exam']={'state':'running','tasks':['d01'],'deadline':time.time()+30,'results':{'secret':'value'}}
        data=self.m.snapshot();self.assertNotIn('results',data['exam']);self.assertNotIn('last_grade',data['tasks'][0]['progress'])
    def test_exam_blocks_revealing_and_preparing(self):
        self.m.state['exam']={'state':'running','deadline':time.time()+30}
        with self.assertRaises(BusyError):self.m.reveal('d01','solution')
    def test_workspace_path_traversal_blocked(self):
        with self.assertRaises(ValueError):self.m.runner.map_path('/workspace/../../etc/passwd')
    def test_external_paths_are_blocked(self):
        with self.assertRaises(ValueError):self.m.runner.map_path('/etc/passwd')
    def test_symlink_workspace_escape_blocked(self):
        self.m.runner.workspace.mkdir();(self.m.runner.workspace/'escape').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):self.m.runner.map_path('/workspace/escape/outside')

class FixtureRunner(Runner):
    """Explicit test double; NEVER used by the application or live self-test."""
    def __init__(self,workspace,objects=None):super().__init__(workspace=workspace);self.objects=objects or {};self.calls=[];self.fail_api=False;self.exec_results=[]
    async def k(self,*args,ns=None,**kwargs):
        self.calls.append((args,ns,kwargs))
        if self.fail_api:return Result(1,'','Unable to connect to the server: connection refused')
        if args[0]=='get':
            value=self.objects.get((args[1],args[2],ns))
            return Result(0,json.dumps(value),'') if value is not None else Result(1,'','Error from server (NotFound): not found')
        if args[0]=='exec':return self.exec_results.pop(0) if self.exec_results else Result(0,'','')
        return Result(0,'','')

class GraderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):self.temp=tempfile.TemporaryDirectory();self.r=FixtureRunner(self.temp.name);self.task=deepcopy(BANK['d01'])
    async def asyncTearDown(self):self.temp.cleanup()
    async def test_equivalent_rbac_rule_grouping_is_accepted(self):
        t=BANK['c06'];c=next(c for c in t['checks'] if c['kind']=='rbac_rules')
        role={'kind':'Role','rules':[{'apiGroups':[''],'resources':['pods'],'verbs':[verb]} for verb in ('watch','list','get')]+[{'apiGroups':[''],'resources':['pods/log'],'verbs':['get']}]}
        self.r.objects[('role','pod-reader','ckad-c06')]=role
        passed,_=await Grader(self.r,t).evaluate(c);self.assertTrue(passed)
    async def test_excess_rbac_permissions_are_rejected(self):
        t=BANK['c06'];c=next(c for c in t['checks'] if c['kind']=='rbac_rules')
        role={'kind':'Role','rules':deepcopy(c['rules'])+[{'apiGroups':[''],'resources':['secrets'],'verbs':['list']}]}
        self.r.objects[('role','pod-reader','ckad-c06')]=role
        passed,_=await Grader(self.r,t).evaluate(c);self.assertFalse(passed)
    async def test_missing_object_is_fail_not_grader_error(self):
        g=await Grader(self.r,self.task).grade();self.assertFalse(g['has_errors']);self.assertEqual(g['earned'],0)
    async def test_api_down_is_error_not_success(self):
        self.r.fail_api=True;g=await Grader(self.r,self.task).grade();self.assertTrue(g['has_errors']);self.assertEqual(g['earned'],0)
    async def test_known_correct_pod_fields_pass(self):
        p=deepcopy(self.task['final'][0]);p['status']={'phase':'Running','conditions':[{'type':'Ready','status':'True'}]};self.r.objects[('pod','catalog','ckad-d01')]=p
        g=await Grader(self.r,self.task).grade();self.assertTrue(g['complete']);self.assertFalse(g['has_errors'])
    async def test_wrong_pod_label_is_detected(self):
        p=deepcopy(self.task['final'][0]);p['metadata']['labels']['tier']='wrong';p['status']={'phase':'Running','conditions':[{'type':'Ready','status':'True'}]};self.r.objects[('pod','catalog','ckad-d01')]=p
        g=await Grader(self.r,self.task).grade();self.assertFalse(g['complete']);self.assertEqual(g['earned'],3)
    async def test_object_requests_are_cached_per_grade(self):
        await Grader(self.r,self.task).grade();self.assertEqual(len(self.r.calls),1)
    async def test_namespace_is_explicit(self):
        await Grader(self.r,self.task).grade();self.assertEqual(self.r.calls[0][1],'ckad-d01')
    async def test_empty_networkpolicy_api_omission_is_equivalent(self):
        t=BANK['n08'];policy=deepcopy(t['final'][0]);policy['spec'].pop('ingress');self.r.objects[('networkpolicy','default-deny','ckad-n08')]=policy
        passed,_=await Grader(self.r,t).evaluate(t['checks'][0]);self.assertTrue(passed)
    async def test_extra_networkpolicy_egress_is_not_equivalent(self):
        t=BANK['n08'];policy=deepcopy(t['final'][0]);policy['spec']['policyTypes'].append('Egress');self.r.objects[('networkpolicy','default-deny','ckad-n08')]=policy
        passed,_=await Grader(self.r,t).evaluate(t['checks'][0]);self.assertFalse(passed)
    async def test_dead_pods_do_not_count_as_successful_network_isolation(self):
        t=BANK['n08'];c=t['checks'][-1];passed,detail=await Grader(self.r,t).evaluate(c);self.assertFalse(passed);self.assertIn('Ready',detail)
    async def test_dead_server_does_not_count_as_successful_network_isolation(self):
        t=BANK['n08']
        for name in ('outsider','backend'):
            self.r.objects[('pod',name,t['namespace'])]={'kind':'Pod','status':{'phase':'Running','podIP':'10.42.1.4','conditions':[{'type':'Ready','status':'True'}]}}
        self.r.exec_results=[Result(1,'','connection refused')]
        passed,detail=await Grader(self.r,t).evaluate(t['checks'][-1]);self.assertFalse(passed);self.assertIn('locally',detail)
    async def test_true_traffic_block_with_healthy_server_passes(self):
        t=BANK['n08']
        for name in ('outsider','backend'):
            self.r.objects[('pod',name,t['namespace'])]={'kind':'Pod','status':{'phase':'Running','podIP':'10.42.1.4','conditions':[{'type':'Ready','status':'True'}]}}
        self.r.exec_results=[Result(0,'OK',''),Result(0,'BLOCKED','')]
        passed,_=await Grader(self.r,t).evaluate(t['checks'][-1]);self.assertTrue(passed)
    async def test_secret_values_are_not_leaked_in_result(self):
        t=BANK['c03'];g=await Grader(self.r,t).grade();self.assertNotIn('practice-only-42',json.dumps(g))
    async def test_file_answers_are_checked(self):
        Path(self.temp.name,'o03').mkdir();Path(self.temp.name,'o03/errors.txt').write_text('ERROR payment-timeout\nERROR retry-exhausted\n')
        check=next(c for c in BANK['o03']['checks'] if c['kind']=='file')
        passed,_=await Grader(self.r,BANK['o03']).evaluate(check);self.assertTrue(passed)
    async def test_wrong_file_order_is_rejected(self):
        Path(self.temp.name,'o03').mkdir();Path(self.temp.name,'o03/errors.txt').write_text('ERROR retry-exhausted\nERROR payment-timeout\n')
        check=next(c for c in BANK['o03']['checks'] if c['kind']=='file')
        passed,_=await Grader(self.r,BANK['o03']).evaluate(check);self.assertFalse(passed)
    async def test_real_runner_invokes_real_process(self):
        r=await Runner(workspace=self.temp.name).run(['bash','-c','printf "actual-process-output"']);self.assertEqual(r.out,'actual-process-output');self.assertEqual(r.code,0)
    async def test_real_runner_enforces_timeout(self):
        with self.assertRaises(InfrastructureError):await Runner(workspace=self.temp.name).run(['bash','-c','sleep 60'],timeout=.1)
    async def test_unsupported_criterion_is_explicit_error(self):
        self.task['checks']=[{'kind':'missing_implementation','label':'example'}];g=await Grader(self.r,self.task).grade();self.assertTrue(g['has_errors']);self.assertFalse(g['complete'])

class StartupTests(unittest.IsolatedAsyncioTestCase):
    def manager(self,worker_status='True',worker_reason='KubeletReady'):
        nodes=[{'metadata':{'name':name},'status':{'conditions':[{'type':'Ready','status':status,'reason':reason}]}}
               for name,status,reason in [('ckad-control','True','KubeletReady'),('ckad-worker',worker_status,worker_reason)]]
        deployments=[{'kind':'Deployment','metadata':{'name':name,'generation':1},'spec':{'replicas':1},
                      'status':{'observedGeneration':1,'replicas':1,'updatedReplicas':1,'availableReplicas':1}}
                     for name in ('coredns','traefik','metrics-server','local-path-provisioner')]
        async def query(*args,**kwargs):
            if args[:2]==('get','nodes'): return Result(0,json.dumps({'items':nodes}),'')
            if args[:2]==('get','deployments'): return Result(0,json.dumps({'items':deployments}),'')
            if args[:2]==('get','pods'): return Result(0,json.dumps({'items':[]}),'')
            return Result(0,'{}','')
        return SimpleNamespace(environment={'ready':False},runner=SimpleNamespace(k=AsyncMock(side_effect=query),run=AsyncMock(return_value=Result(0,'28.5.2',''))),nodes=nodes,deployments=deployments)

    async def test_startup_identifies_the_blocking_node_immediately(self):
        from bootstrap import base_ready
        manager=self.manager('Unknown','NodeStatusUnknown')
        self.assertFalse(await base_ready(manager))
        self.assertIn('ckad-worker',manager.environment['message'])
        self.assertIn('not reporting',manager.environment['message'])
        self.assertTrue(manager.environment['checks']['node_ckad-control'])
        self.assertFalse(manager.environment['checks']['node_ckad-worker'])
        manager.runner.run.assert_not_called()

    async def test_stale_node_stops_startup_after_grace_period(self):
        from bootstrap import base_ready,StartupBlocked
        manager=self.manager('Unknown','NodeStatusUnknown')
        with self.assertRaises(StartupBlocked) as error:
            await base_ready(manager,stale_grace_elapsed=True)
        self.assertIn('ckad-worker',str(error.exception))
        self.assertIn('docker compose logs worker',str(error.exception))
        self.assertIn('Node password rejected',str(error.exception))
        self.assertFalse(manager.environment['ready'])

    async def test_expected_node_names_are_required(self):
        from bootstrap import base_ready
        manager=self.manager()
        manager.nodes[1]['metadata']['name']='other-worker'
        self.assertFalse(await base_ready(manager))
        self.assertIn('ckad-worker',manager.environment['message'])

    async def test_healthy_base_is_not_prematurely_marked_ready(self):
        from bootstrap import base_ready
        manager=self.manager()
        self.assertTrue(await base_ready(manager))
        self.assertFalse(manager.environment['ready'])
        self.assertEqual(manager.environment['blockers'],[])
        manager.runner.run.assert_awaited_once()

    async def test_controller_failure_names_the_component_and_image_error(self):
        from bootstrap import base_ready
        manager=self.manager()
        manager.deployments[0]['status']['availableReplicas']=0
        query=manager.runner.k.side_effect
        async def with_pod(*args,**kwargs):
            if args[:2]==('get','pods'):
                return Result(0,json.dumps({'items':[{'metadata':{'name':'coredns-test'},'status':{'containerStatuses':[{'state':{'waiting':{'reason':'ImagePullBackOff'}}}]}}]}),'')
            return await query(*args,**kwargs)
        manager.runner.k.side_effect=with_pod
        self.assertFalse(await base_ready(manager))
        self.assertIn('coredns',manager.environment['message'])
        self.assertIn('ImagePullBackOff',manager.environment['message'])

    async def test_api_rejection_is_actionable_without_echoing_credentials(self):
        from bootstrap import base_ready,StartupBlocked
        manager=self.manager()
        manager.runner.k=AsyncMock(return_value=Result(1,'','Unauthorized: private-value-must-not-be-echoed'))
        with self.assertRaises(StartupBlocked) as error: await base_ready(manager)
        self.assertNotIn('private-value',str(error.exception))
        self.assertIn('kubeconfig',str(error.exception))

    async def test_wait_timeout_also_bounds_a_hanging_predicate(self):
        from bootstrap import wait_until
        cancelled=asyncio.Event()
        async def hung():
            try: await asyncio.sleep(10)
            finally: cancelled.set()
        with self.assertRaises(InfrastructureError) as error:
            await asyncio.wait_for(wait_until(hung,'Probe timed out',timeout=.03),timeout=.5)
        self.assertIn('Probe timed out',str(error.exception))
        self.assertTrue(cancelled.is_set())

    async def test_fatal_startup_failure_is_not_retried(self):
        from bootstrap import wait_until,StartupBlocked
        probe=AsyncMock(side_effect=StartupBlocked('Worker needs repair'))
        with self.assertRaises(StartupBlocked): await wait_until(probe,'Timed out',timeout=.03)
        probe.assert_awaited_once()

    async def test_wait_preserves_cancellation(self):
        from bootstrap import wait_until
        probe=AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError): await wait_until(probe,'Timed out',timeout=.03)

    async def test_wait_reports_last_transient_failure(self):
        from bootstrap import wait_until
        probe=AsyncMock(side_effect=InfrastructureError('API unavailable'))
        with self.assertRaises(InfrastructureError) as error: await wait_until(probe,'Timed out',timeout=.03)
        self.assertIn('API unavailable',str(error.exception))


if __name__=='__main__':unittest.main()
