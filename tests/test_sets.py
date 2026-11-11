import asyncio
from collections import Counter
from copy import deepcopy
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
if not (Path(__file__).resolve().parents[1] / 'app').exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bank import BANK, ACTIVE_BANK, SETS, set_tasks
from manager import Manager
from runtime import Runner, Grader, Result
from tutor import study_guide


class QuestionSetTests(unittest.TestCase):
    def test_two_separate_sets_keep_original_ids(self):
        self.assertEqual(len(BANK), 66)
        self.assertEqual(Counter(t['set_id'] for t in BANK.values()), {'core': 50, 'focused': 16})
        self.assertEqual(SETS['core']['mock_tasks'], 20)
        self.assertEqual(SETS['focused']['mock_tasks'], 16)
        self.assertEqual({t['id'] for t in BANK.values() if t['set_id'] == 'focused'}, {f's{i:02}' for i in range(1, 17)})

    def test_visible_core_is_twenty_balanced_questions(self):
        self.assertEqual(len(ACTIVE_BANK),36)
        self.assertEqual(len(set_tasks('core')),20)
        self.assertEqual(Counter(t['domain'] for t in set_tasks('core')),{'design':4,'deployment':4,'observability':3,'configuration':5,'networking':4})
        with tempfile.TemporaryDirectory() as temp:
            snapshot=Manager(Runner(workspace=temp),Path(temp)/'state').snapshot()
        self.assertEqual(len(snapshot['tasks']),36)
        self.assertEqual(snapshot['meta']['questions'],36)
        self.assertNotIn('d10',[t['id'] for t in snapshot['tasks']])

    def test_new_tasks_have_independent_namespaces_and_guides(self):
        for i in range(1, 17):
            task = BANK[f's{i:02}']
            self.assertEqual(task['namespace'], f'ckad-s{i:02}')
            self.assertEqual(task['source_question'], i)
            self.assertGreaterEqual(len(task['checks']), 3)
            guide = study_guide(task)
            self.assertEqual(len(guide['steps']), 3)
            self.assertGreater(sum(map(len, guide['steps'])), 250)
            if 'kubectl ' in guide['verification']:
                self.assertIn('-n ' + task['namespace'], guide['verification'])
            self.assertNotIn('kubectl config ', guide['verification'])
            self.assertTrue(any('aravind4799/CKAD-Practice-Questions' in doc['url'] for doc in task['docs']))

    def test_focused_questions_use_upstream_resource_names_and_constraints(self):
        expected = {
            's01': {'api-server', 'db-credentials'},
            's02': {'backup-job'},
            's03': {'log-collector', 'log-sa', 'log-role', 'log-rb'},
            's04': {'metrics-pod', 'monitor-sa', 'wrong-sa', 'admin-sa', 'metrics-reader', 'full-access', 'view-only', 'monitor-binding', 'admin-binding'},
            's05': {'my-app:1.0', 'my-app.tar'},
            's06': {'web-app', 'web-app-canary', 'web-service'},
            's07': {'frontend', 'backend', 'database', 'deny-all', 'allow-frontend-to-backend', 'allow-backend-to-db'},
            's08': {'broken-app', 'broken-deploy.yaml'},
            's09': {'app-v1', 'nginx:1.20', 'nginx:1.25'},
            's10': {'api-deploy'},
            's11': {'secure-app'},
            's12': {'web-app', 'web-svc'},
            's13': {'api-server', 'api-nodeport'},
            's14': {'web-deploy', 'web-svc', 'web-ingress', 'web.example.com'},
            's15': {'api-ingress', 'api-svc', 'fix-ingress.yaml'},
            's16': {'resource-pod', 'nginx:latest'},
        }
        for tid, tokens in expected.items():
            with self.subTest(task=tid):
                task = BANK[tid]
                text = ' '.join([task['title'], *task['requirements'], task['solution'], *task['files']])
                for token in tokens: self.assertIn(token, text)
        self.assertEqual({c['name'] for c in BANK['s02']['checks'] if c.get('resource') == 'job'}, set())
        self.assertNotIn('nodePort', next(x for x in BANK['s13']['final'] if x['kind'] == 'Service')['spec']['ports'][0])
        self.assertEqual(next(c for c in BANK['s15']['checks'] if c.get('op') == 'one_of')['expected'], ['Prefix', 'Exact', 'ImplementationSpecific'])
        self.assertEqual(BANK['s15']['checks'][0]['allowed_path_types'], ['Prefix', 'Exact', 'ImplementationSpecific'])
        self.assertEqual({c['op'] for c in BANK['s16']['checks'] if c.get('resource') == 'pod' and c.get('op') == 'at_least_quantity'}, {'at_least_quantity'})

    def test_mock_selection_is_scoped_and_repeatable(self):
        for seed in ('one', 'two', 'three'):
            core = Manager.choose_exam(seed)
            focused = Manager.choose_exam(seed, 'focused')
            self.assertEqual(len(core), 20)
            self.assertTrue(all(BANK[tid]['set_id'] == 'core' for tid in core))
            self.assertEqual(len(focused), 16)
            self.assertTrue(all(BANK[tid]['set_id'] == 'focused' for tid in focused))
            self.assertEqual(focused, Manager.choose_exam(seed, 'focused'))
        with self.assertRaises(ValueError): Manager.choose_exam('x', 'unknown')

    def test_selftest_refuses_an_old_server_before_posting(self):
        import selftest
        state={'environment':{'ready':True},'csrf':'fixture','tasks':[]}
        with patch.object(sys,'argv',['selftest.py','--set','focused','--yes']), patch('selftest.urllib.request.urlopen',return_value=io.StringIO(json.dumps(state))) as request, patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(selftest.main(),2)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0].get_method(),'GET')

    def test_rbac_client_is_valid_python_and_preserves_tls_verification(self):
        from bank_focused import API_READER
        compile(API_READER,'api-reader','exec')
        self.assertIn('ssl.create_default_context',API_READER)
        self.assertNotIn('_create_unverified_context',API_READER)
        self.assertNotIn('print(request',API_READER)

    def test_sixteen_question_score_is_normalized(self):
        results = {f's{i:02}': {'earned': 4, 'possible': 4} for i in range(1, 17)}
        self.assertEqual(Manager.exam_score(results, points=6.25), 100)
        results['s01']['earned'] = 0
        self.assertEqual(Manager.exam_score(results, points=6.25), 93.8)


class QuestionSetManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Manager(Runner(workspace=self.temp.name), Path(self.temp.name) / 'state')
        self.manager.environment['ready'] = True

    async def asyncTearDown(self):
        if self.manager.job and not self.manager.job.done():
            self.manager.job.cancel()
            try: await self.manager.job
            except asyncio.CancelledError: pass
        self.temp.cleanup()

    async def test_mock_preparation_does_not_clear_other_set(self):
        manager = self.manager
        manager.state['practice']['d01'] = {'prepared': True, 'notes': 'Keep me', 'step_checks': {'0': {'status': 'pass'}}}
        with patch.object(manager.ops, 'clean_all', new_callable=AsyncMock) as cleanup, patch.object(manager.ops, 'setup', new_callable=AsyncMock):
            manager.start_exam('fixture', 'focused')
            await manager.job
        self.assertEqual(manager.operation['state'], 'done')
        cleaned = cleanup.call_args.args[0]
        self.assertEqual(len(cleaned), 16)
        self.assertTrue(all(t['set_id'] == 'focused' for t in cleaned))
        self.assertTrue(manager.state['practice']['d01']['prepared'])
        self.assertEqual(manager.state['practice']['d01']['notes'], 'Keep me')
        self.assertTrue(manager.state['practice']['d01']['step_checks'])
        exam = manager.state['exam']
        self.assertEqual(exam['set_id'], 'focused')
        self.assertEqual(exam['task_points'], 6.25)
        self.assertEqual(sum(exam['domain_weights'].values()), 100)
        self.assertEqual(exam['duration_seconds'], 7200)

    async def test_second_set_submission_can_score_full_credit(self):
        manager = self.manager
        ids = Manager.choose_exam('full', 'focused')
        manager.state['exam'] = {'id': 'fixture', 'state': 'running', 'deadline': 9999999999, 'tasks': ids, 'results': {}, 'set_id': 'focused', 'task_points': 6.25}
        async def grade(grader):
            return {'earned': 1, 'possible': 1, 'complete': True, 'has_errors': False}
        with patch.object(Grader, 'grade', grade):
            manager.submit_exam()
            await manager.job
        self.assertEqual(manager.state['exam']['score'], 100)
        self.assertEqual(sum(manager.state['exam']['domain_scores'].values()), 100)

    async def test_scoped_selftest_does_not_clear_core(self):
        manager = self.manager
        manager.state['practice']['d01'] = {'prepared': True}
        with patch.object(manager.ops, 'clean_all', new_callable=AsyncMock) as cleanup, patch.object(manager.ops, 'setup', new_callable=AsyncMock, side_effect=ValueError('Stop before executing solutions')), patch.object(manager.ops, 'delete', new_callable=AsyncMock):
            manager.start_selftest(['s01'], 'focused')
            await manager.job
        self.assertTrue(manager.state['practice']['d01']['prepared'])
        self.assertTrue(all(t['set_id'] == 'focused' for t in cleanup.call_args.args[0]))
        with self.assertRaises(ValueError): manager.start_selftest(['d01'], 'focused')


class CleanupScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_focused_cleanup_preserves_core_files_and_images(self):
        from bank import set_tasks
        from labops import LabOperations
        with tempfile.TemporaryDirectory() as temp:
            core=Path(temp)/'d01'
            core.mkdir()
            (core/'keep.txt').write_text('Keep original work')
            runner=Runner(workspace=temp)
            runner.k=AsyncMock(return_value=Result(0,'',''))
            runner.run=AsyncMock(return_value=Result(0,'',''))
            ops=LabOperations(runner)
            with patch.object(ops,'assert_lab',new_callable=AsyncMock):
                await ops.clean_all(set_tasks('focused'))
            self.assertTrue((core/'keep.txt').exists())
            deleted=runner.k.call_args.args
            self.assertIn('ckad-s01',deleted)
            self.assertNotIn('ckad-d01',deleted)
            runner.run.assert_awaited_once_with(['docker','image','rm','-f','my-app:1.0'])


class RolloutHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_extra_policy_is_detected_by_inventory(self):
        task=BANK['s07']
        criterion=next(c for c in task['checks'] if c['kind']=='inventory')
        items=[{'metadata':{'name':name}} for name in criterion['names']]
        runner=Runner()
        runner.k=AsyncMock(return_value=Result(0,json.dumps({'items':items}),''))
        grader=Grader(runner,task)
        self.assertTrue((await grader.evaluate(criterion))[0])
        items.append({'metadata':{'name':'allow-everything'}})
        runner.k.return_value=Result(0,json.dumps({'items':items}),'')
        self.assertFalse((await grader.evaluate(criterion))[0])

    async def test_any_allocated_nodeport_can_be_graded(self):
        task = BANK['s13']
        criterion = next(c for c in task['checks'] if c['kind'] == 'http_nodeport')
        runner = Runner()
        runner.k = AsyncMock()
        runner.run = AsyncMock(return_value=Result(0, 'API READY', ''))
        for port in (30080, 30130):
            with self.subTest(port=port):
                service = {'kind': 'Service', 'spec': {'type': 'NodePort', 'ports': [{'port': 80, 'protocol': 'TCP', 'nodePort': port}]}}
                runner.k.return_value = Result(0, json.dumps(service), '')
                self.assertTrue((await Grader(runner, task).evaluate(criterion))[0])
                self.assertIn(f'http://cluster:{port}', runner.run.await_args.args[0])
        runner.k.return_value = Result(0, json.dumps({'kind': 'Service', 'spec': {'type': 'ClusterIP', 'ports': [{'port': 80, 'protocol': 'TCP'}]}}), '')
        self.assertFalse((await Grader(runner, task).evaluate(criterion))[0])

    async def test_all_supported_ingress_path_types_are_accepted_in_answer_file_and_live_object(self):
        import yaml
        task = BANK['s15']
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 's15' / 'fix-ingress.yaml'
            path.parent.mkdir()
            runner = Runner(workspace=temp)
            grader = Grader(runner, task)
            file_check = next(c for c in task['checks'] if c['kind'] == 'yaml_file')
            live_check = next(c for c in task['checks'] if c.get('op') == 'one_of')
            for kind in ('Prefix', 'Exact', 'ImplementationSpecific', 'InvalidType'):
                with self.subTest(path_type=kind):
                    doc = deepcopy(task['final'][0])
                    doc['spec']['rules'][0]['http']['paths'][0]['pathType'] = kind
                    path.write_text(yaml.safe_dump(doc))
                    runner.k = AsyncMock(return_value=Result(0, json.dumps(doc), ''))
                    expected = kind != 'InvalidType'
                    self.assertEqual((await grader.evaluate(file_check))[0], expected)
                    self.assertEqual((await Grader(runner, task).evaluate(live_check))[0], expected)

    async def test_update_then_rollback_requires_owned_revision_history(self):
        task = BANK['s09']
        criterion = next(c for c in task['checks'] if c['kind'] == 'rollout_history')
        deployment = {'metadata': {'uid': 'workload-uid', 'annotations': {'deployment.kubernetes.io/revision': '3'}}}
        replicasets = [{'metadata': {'ownerReferences': [{'uid': 'workload-uid', 'controller': True}]}, 'spec': {'template': {'spec': {'containers': [{'name': criterion['container'], 'image': image}]}}}} for image in criterion['images']]
        runner = Runner()
        grader = Grader(runner, task)
        grader.get = AsyncMock(return_value=deployment)
        runner.k = AsyncMock(return_value=Result(0, json.dumps({'items': replicasets}), ''))
        self.assertTrue((await grader.evaluate(criterion))[0])
        deployment['metadata']['annotations']['deployment.kubernetes.io/revision'] = '1'
        self.assertFalse((await grader.evaluate(criterion))[0])
        deployment['metadata']['annotations']['deployment.kubernetes.io/revision'] = '3'
        replicasets[1]['metadata']['ownerReferences'][0]['uid'] = 'unrelated'
        runner.k.return_value = Result(0, json.dumps({'items': replicasets}), '')
        self.assertFalse((await grader.evaluate(criterion))[0])
