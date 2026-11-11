"""Acceptance tests for valid alternatives, not copies of reference solutions."""
import asyncio
from copy import deepcopy
import sys
from pathlib import Path
import unittest
import tempfile
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from bank import ACTIVE_BANK, BANK
from runtime import Grader, Runner, Result, check_value, compare


def resource_checks(tid, obj, resource='pod'):
    checks=[c for c in BANK[tid]['checks'] if c['kind']=='resource' and c['resource']==resource]
    return [compare(check_value(obj,c,checks),c['expected'],c['op']) for c in checks]


class GraderContracts(unittest.TestCase):
    def test_every_active_question_has_a_scoped_negative_case(self):
        from validation_cases import invalidate_answer
        async def run(root):
            runner=Runner('/private/grader-config',root)
            runner.k=AsyncMock(return_value=Result(0,'',''))
            for tid,task in ACTIVE_BANK.items():
                for name in ('overlays/prod','app-source'):
                    runner.map_path(task['workspace']+'/'+name).mkdir(parents=True,exist_ok=True)
                runner.k.reset_mock()
                await invalidate_answer(runner,task)
                for call in runner.k.await_args_list:
                    self.assertEqual(call.kwargs['ns'],task['namespace'])
                    self.assertNotIn('config',call.args)
        with tempfile.TemporaryDirectory() as temp: asyncio.run(run(temp))
    def test_s16_accepts_student_container_names_and_equivalent_quantities(self):
        for name in ('resource-pod','nginx','student-app'):
            for cpu,memory in [('1','2Gi'),('1000m','2048Mi')]:
                with self.subTest(name=name,cpu=cpu,memory=memory):
                    pod=deepcopy(BANK['s16']['final'][0])
                    app=pod['spec']['containers'][0]
                    app['name']=name
                    app['resources']['limits']={'cpu':cpu,'memory':memory}
                    app['resources']['requests']={'cpu':'200m','memory':'256Mi'}
                    self.assertTrue(all(resource_checks('s16',pod)))

    def test_s16_ignores_sidecar_order_but_never_combines_containers(self):
        pod=deepcopy(BANK['s16']['final'][0])
        app=pod['spec']['containers'][0]
        other={'name':'sidecar','image':'busybox:1.37.0'}
        for items in ([other,app],[app,other]):
            pod['spec']['containers']=items
            self.assertTrue(all(resource_checks('s16',pod)))
        other['resources']=app.pop('resources')
        self.assertFalse(all(resource_checks('s16',pod)))

    def test_s16_rejects_each_wrong_field_and_missing_container(self):
        for area,key,value in [('limits','cpu','500m'),('limits','memory','1Gi'),
                               ('requests','cpu','99m'),('requests','memory','127Mi')]:
            with self.subTest(area=area,key=key):
                pod=deepcopy(BANK['s16']['final'][0])
                pod['spec']['containers'][0]['resources'][area][key]=value
                self.assertFalse(all(resource_checks('s16',pod)))
        pod=deepcopy(BANK['s16']['final'][0])
        pod['spec']['containers'][0]['image']='busybox:latest'
        self.assertFalse(all(resource_checks('s16',pod)))
        pod['spec']['containers']=[]
        self.assertFalse(any(resource_checks('s16',pod)))

    def test_explicit_container_names_remain_required(self):
        pod=deepcopy(BANK['d01']['final'][0])
        pod['spec']['containers'][0]['name']='catalog'
        self.assertFalse(all(resource_checks('d01',pod)))

    def test_s16_real_evaluator_uses_the_unnamed_container_group(self):
        async def run():
            pod=deepcopy(BANK['s16']['final'][0])
            pod['spec']['containers'][0]['name']='resource-pod'
            grader=Grader(Runner(),BANK['s16'])
            grader.get=AsyncMock(return_value=pod)
            for c in BANK['s16']['checks']:
                if c['kind']=='resource' and c['resource']=='pod':
                    self.assertTrue((await grader.evaluate(c))[0])
        asyncio.run(run())

    def test_individual_checks_choose_the_same_container_as_full_grading(self):
        async def run():
            task=BANK['s16']; pod=deepcopy(task['final'][0])
            app=pod['spec']['containers'][0]
            sidecar={'name':'other','image':'busybox:1.37.0','resources':app.pop('resources')}
            pod['spec']['containers'].append(sidecar)
            image_check=next(c for c in task['checks'] if c.get('path')==['image'])
            grader=Grader(Runner(),{**task,'checks':[image_check],'selection_checks':task['checks']})
            grader.get=AsyncMock(return_value=pod)
            self.assertFalse((await grader.evaluate(image_check))[0])
        asyncio.run(run())

    def test_cronjob_accepts_equivalent_echo_commands(self):
        variants=[
            (['/bin/sh','-c'],['echo Backup completed']),
            (['sh','-c','echo Backup completed'],[]),
            (['echo','Backup','completed'],[]),
            (['/bin/echo'],['Backup completed']),
            (['sh','-c'],['echo "Backup completed"']),
            (['sh','-c'],['echo Backup completed;\n']),
        ]
        for command,args in variants:
            with self.subTest(command=command,args=args):
                cron=deepcopy(BANK['s02']['final'][0])
                c=cron['spec']['jobTemplate']['spec']['template']['spec']['containers'][0]
                c.update(command=command,args=args)
                self.assertTrue(all(resource_checks('s02',cron,'cronjob')))

    def test_cronjob_rejects_wrong_output_sleep_and_compound_scripts(self):
        for command in (['sleep','300'],['echo','Wrong'],['sh','-c','echo Backup completed; sleep 300'],
                        ['sh','-c','echo Backup completed > /tmp/log'],['sh','-c','echo $(false)']):
            cron=deepcopy(BANK['s02']['final'][0])
            c=cron['spec']['jobTemplate']['spec']['template']['spec']['containers'][0]
            c.update(command=command,args=[])
            self.assertFalse(all(resource_checks('s02',cron,'cronjob')))

    def test_secret_refs_allow_other_environment_variables(self):
        dep=next(x for x in BANK['s01']['final'] if x['kind']=='Deployment')
        dep=deepcopy(dep)
        env=dep['spec']['template']['spec']['containers'][0]['env']
        env.append({'name':'OTHER','value':'keep-me'})
        self.assertTrue(all(resource_checks('s01',dep,'deployment')))
        env.append({'name':'DB_USER','value':'override'})
        self.assertFalse(all(resource_checks('s01',dep,'deployment')))
        env.pop()
        env[0]={'name':'DB_USER','value':'admin'}
        self.assertFalse(all(resource_checks('s01',dep,'deployment')))

    def test_capability_requirement_is_presence_not_an_exclusive_list(self):
        dep=deepcopy(BANK['s11']['final'][0])
        caps=dep['spec']['template']['spec']['containers'][0]['securityContext']['capabilities']['add']
        caps.append('NET_BIND_SERVICE')
        self.assertTrue(all(resource_checks('s11',dep,'deployment')))
        caps.remove('NET_ADMIN')
        self.assertFalse(all(resource_checks('s11',dep,'deployment')))

    def test_active_container_name_constraints_are_stated_or_seeded(self):
        # Prevent another hidden reference-only container name from entering any
        # active task. Existing workloads, supplied manifests and charts count.
        def names(value):
            if isinstance(value,dict):
                for key,items in value.items():
                    if key in ('containers','initContainers') and isinstance(items,list):
                        for c in items:
                            if isinstance(c,dict) and 'name' in c: yield c['name']
                    yield from names(items)
            elif isinstance(value,list):
                for item in value: yield from names(item)
        for tid,task in ACTIVE_BANK.items():
            stated=' '.join(task['requirements'])+' '.join(task['files'].values())
            provided=set(names(task['seeds']))
            for c in task['checks']:
                required=set(names(c.get('expected')))
                path=c.get('path',[])
                if isinstance(path,list):
                    for i,part in enumerate(path):
                        if part in ('containers','initContainers') and i+1<len(path) and isinstance(path[i+1],dict):
                            required.add(path[i+1].get('name',''))
                # c11 is generated by the supplied operator, not a student Pod.
                if tid=='c11': continue
                for name in required:
                    with self.subTest(task=tid,container=name):
                        self.assertTrue(not name or name in provided or name in stated,
                                        f'{tid}: unstated container name {name}')

    def test_network_policy_accepts_split_dns_rules_and_equivalent_selectors(self):
        c=next(c for c in BANK['n10']['checks'] if c.get('op')=='network_policy')
        policy=deepcopy(c['expected'])
        dns=policy['egress'].pop()
        policy['egress'] += [{**dns,'ports':[port]} for port in dns['ports']]
        policy['podSelector']={'matchExpressions':[{'key':'role','operator':'In','values':['client']}]}
        self.assertTrue(compare(policy,c['expected'],c['op']))
        policy['egress'].append({})
        self.assertFalse(compare(policy,c['expected'],c['op']))

    def test_network_policy_rejects_or_in_place_of_and(self):
        c=next(c for c in BANK['n09']['checks'] if c.get('op')=='network_policy')
        policy=deepcopy(c['expected'])
        peer=policy['ingress'][0]['from'][0]
        policy['ingress'][0]['from']=[{'podSelector':peer['podSelector']},{'namespaceSelector':peer['namespaceSelector']}]
        self.assertFalse(compare(policy,c['expected'],c['op']))

    def test_canary_http_check_tests_every_ready_backend(self):
        async def run():
            task=BANK['s06']; c=next(c for c in task['checks'] if c['kind']=='http_endpoints')
            runner=Runner(); grader=Grader(runner,task)
            grader.get=AsyncMock(return_value={'kind':'Pod','status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}})
            import json
            endpoints=[{'addresses':['10.1.0.'+str(i)],'conditions':{'ready':True}} for i in range(1,11)]
            runner.k=AsyncMock(return_value=Result(0,json.dumps({'items':[{'endpoints':endpoints}]}),''))
            grader.pod_exec=AsyncMock(return_value=Result(0,'',''))
            self.assertTrue((await grader.evaluate(c))[0])
            self.assertEqual(grader.pod_exec.await_count,10)
            grader.pod_exec=AsyncMock(side_effect=[Result(0,'','')]*9+[Result(1,'','connection refused')])
            self.assertFalse((await grader.evaluate(c))[0])
        asyncio.run(run())

    def test_empty_endpoint_slices_fail_cleanly(self):
        async def run():
            import json
            for tid,kind in (('n01','endpoints'),('s06','http_endpoints')):
                task=BANK[tid]; c=next(c for c in task['checks'] if c['kind']==kind)
                runner=Runner(); grader=Grader(runner,task)
                grader.get=AsyncMock(return_value={'kind':'Pod','status':{'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}})
                for endpoints in (None,[]):
                    runner.k=AsyncMock(return_value=Result(0,json.dumps({'items':[{'endpoints':endpoints}]}),''))
                    self.assertFalse((await grader.evaluate(c))[0])
        asyncio.run(run())


if __name__=='__main__': unittest.main()
