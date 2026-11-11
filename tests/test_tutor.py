import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
if not (Path(__file__).resolve().parents[1] / 'app').exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient, TestServer
from bank import BANK
from server import create_app


class LocalStudyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = create_app(workspace=str(self.root / 'workspace'), state_dir=str(self.root / 'data'), start_cluster=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        response = await self.client.get('/api/bootstrap')
        self.csrf = (await response.json())['csrf']

    async def asyncTearDown(self):
        await self.client.close()
        await asyncio.sleep(.01)
        self.tmp.cleanup()

    async def post(self, path, data=None):
        return await self.client.post(path, json=data or {}, headers={'X-CSRF-Token': self.csrf})

    async def test_opening_unprepared_question_does_not_reset_it(self):
        manager=self.app['manager'];manager.environment['ready']=True
        with patch.object(manager.ops,'setup',new_callable=AsyncMock) as setup:
            response=await self.post('/api/task/s01/prepare')
            self.assertEqual(response.status,200)
            await manager.job
        setup.assert_awaited_once_with(BANK['s01'],reset=False)
        self.assertTrue(manager.state['practice']['s01']['prepared'])

    async def test_prepared_flag_is_checked_against_live_namespace(self):
        from runtime import Result
        manager=self.app['manager'];manager.environment['ready']=True
        manager.state['practice']['s01']={'prepared':True}
        manager.runner.map_path(BANK['s01']['workspace']).mkdir()
        with patch.object(manager.runner,'k',new_callable=AsyncMock,return_value=Result(0,'','')), patch.object(manager.ops,'setup',new_callable=AsyncMock) as setup:
            response=await self.post('/api/task/s01/prepare')
            await manager.job
        self.assertEqual(response.status,200)
        setup.assert_awaited_once_with(BANK['s01'],reset=False)

    async def test_reopening_prepared_question_keeps_its_work(self):
        from runtime import Result
        manager=self.app['manager'];manager.environment['ready']=True
        manager.state['practice']['s01']={'prepared':True,'notes':'Keep'}
        manager.runner.map_path(BANK['s01']['workspace']).mkdir()
        with patch.object(manager.runner,'k',new_callable=AsyncMock,return_value=Result(0,'namespace/ckad-s01\n','')), patch.object(manager.ops,'setup',new_callable=AsyncMock) as setup:
            response=await self.post('/api/task/s01/prepare')
            self.assertTrue((await response.json())['already_prepared'])
        setup.assert_not_awaited()
        self.assertEqual(manager.state['practice']['s01']['notes'],'Keep')

    async def test_provider_routes_are_removed(self):
        self.assertNotIn('tutor', self.app)
        for kind in ('settings', 'preview', 'ask', 'models', 'test', 'cancel'):
            with self.subTest(kind=kind):
                response = await self.post('/api/tutor/' + kind)
                self.assertEqual(response.status, 404)
        response = await self.client.get('/api/tutor/settings')
        self.assertEqual(response.status, 404)

    async def test_all_solutions_have_detailed_local_walkthroughs(self):
        with patch('aiohttp.ClientSession._request', side_effect=AssertionError('Unexpected outbound HTTP')):
            for tid, task in BANK.items():
                with self.subTest(task=tid):
                    result = self.app['manager'].reveal(tid, 'solution')
                    self.assertEqual(result['solution'], task['solution'])
                    guide = result['guide']
                    self.assertEqual(len(guide['steps']), 3)
                    self.assertGreater(sum(len(step) for step in guide['steps']), 250)
                    self.assertTrue(guide['pitfall'])
                    self.assertTrue(guide['expected'])
                    self.assertEqual(guide['checklist'], [c['label'] for c in task['checks']])
                    self.assertNotIn('kubectl config ', guide['verification'])
                    self.assertNotIn('cd /workspace/', guide['verification'])
                    if 'kubectl ' in guide['verification']:
                        self.assertIn('-n ' + task['namespace'], guide['verification'])
                    syntax = subprocess.run(['bash', '-n'], input=guide['verification'], text=True, capture_output=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    json.dumps(result)

    async def test_solution_endpoint_needs_no_cluster_or_key(self):
        response = await self.post('/api/task/d01/solution')
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertIn('catalog', result['guide']['verification'])
        self.assertTrue(self.app['manager'].state['practice']['d01']['solution_seen'])
        self.assertFalse((self.root / 'data' / 'tutor-settings.json').exists())
        self.assertFalse((self.root / 'data' / 'tutor-key.txt').exists())

    async def test_answers_are_not_in_bootstrap_or_hints(self):
        response = await self.client.get('/api/bootstrap')
        for task in (await response.json())['tasks']:
            self.assertNotIn('solution', task)
            self.assertNotIn('guide', task)
            self.assertNotIn('explanation', task)
        response = await self.post('/api/task/d01/hint')
        self.assertEqual(set(await response.json()), {'hints'})

    async def test_walkthrough_is_blocked_throughout_active_mock(self):
        for state in ('preparing', 'running', 'grading', 'expired'):
            with self.subTest(state=state):
                self.app['manager'].state['exam'] = {'state': state, 'deadline': time.time() + 600, 'tasks': ['d01']}
                response = await self.post('/api/task/d01/solution')
                self.assertEqual(response.status, 409)

    async def test_reveal_requires_csrf(self):
        response = await self.client.post('/api/task/d01/solution', json={})
        self.assertEqual(response.status, 403)

    async def test_old_provider_settings_do_not_affect_app(self):
        self.assertFalse(any('tutor' in str(route.resource) for route in self.app.router.routes()))
        response = await self.client.get('/static/enhancements.js')
        content = await response.text()
        self.assertNotIn('/api/tutor/', content)
        self.assertNotIn('api_key', content)

    async def test_step_check_evaluates_only_selected_criterion(self):
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True}
        with patch('runtime.Grader.evaluate', new_callable=AsyncMock, return_value=(False, 'Pod catalog is missing.')) as evaluate:
            response = await self.post('/api/task/d01/check', {'criterion': 1})
            self.assertEqual(response.status, 200)
            await manager.job
        evaluate.assert_awaited_once_with(BANK['d01']['checks'][1])
        result = manager.state['practice']['d01']['step_checks']['1']
        self.assertEqual(result['status'], 'fail')
        self.assertIn('concept', result['feedback'])
        self.assertIn('catalog', result['feedback']['command'])
        self.assertIn('next', result['feedback'])
        self.assertNotIn('last_grade', manager.state['practice']['d01'])
        self.assertEqual(manager.operation['kind'], 'check_step')

    async def test_full_practice_check_includes_learning_feedback(self):
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True}
        with patch('runtime.Grader.evaluate', new_callable=AsyncMock, return_value=(True, 'Required state found.')):
            response = await self.post('/api/task/d01/grade')
            self.assertEqual(response.status, 200)
            await manager.job
        self.assertTrue(manager.state['practice']['d01']['last_grade']['complete'])
        for result in manager.state['practice']['d01']['step_checks'].values():
            self.assertEqual(result['status'], 'pass')
            self.assertTrue(result['feedback']['concept'])

    async def test_step_check_validation_and_prerequisites(self):
        manager = self.app['manager']
        response = await self.post('/api/task/d01/check', {'criterion': 0})
        self.assertEqual(response.status, 409)
        manager.environment['ready'] = True
        response = await self.post('/api/task/d01/check', {'criterion': 0})
        self.assertEqual(response.status, 409)
        manager.state['practice']['d01'] = {'prepared': True}
        for value in (None, True, -1, 999, '0', 1.5, []):
            response = await self.post('/api/task/d01/check', {'criterion': value})
            self.assertEqual(response.status, 400)
        manager.operation = {'state': 'running', 'kind': 'grade'}
        response = await self.post('/api/task/d01/check', {'criterion': 0})
        self.assertEqual(response.status, 409)

    async def test_active_mock_hides_step_feedback_and_blocks_checks(self):
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True, 'step_checks': {'0': {'status': 'pass'}}}
        for state in ('preparing', 'running', 'grading', 'expired'):
            manager.state['exam'] = {'state': state, 'deadline': time.time() + 600, 'tasks': ['d01']}
            response = await self.post('/api/task/d01/check', {'criterion': 0})
            self.assertEqual(response.status, 409)
            response = await self.client.get('/api/state')
            data = await response.json()
            self.assertNotIn('step_checks', data['tasks'][0]['progress'])
            self.assertNotIn('practice_checks', data['tasks'][0])

    async def test_mock_state_excludes_all_saved_study_aids(self):
        manager = self.app['manager']
        manager.state['practice']['d01'] = {'prepared': True, 'flagged': True, 'notes': 'Saved answer', 'hints_seen': 2, 'solution_seen': True, 'last_grade': {'complete': True}, 'step_checks': {'0': {'detail': 'Previous answer'}}}
        manager.state['history'] = [{'results': {'d01': 'Old report'}}]
        manager.selftest = {'results': [{'detail': 'Validation answer'}]}
        manager.operation = {'state': 'done', 'kind': 'grade', 'result': {'detail': 'Previous answer'}}
        for phase in ('preparing', 'running', 'grading', 'expired'):
            manager.state['exam'] = {'state': phase, 'deadline': time.time() + 600, 'tasks': ['d01'], 'results': {'d01': 'Hidden result'}}
            for endpoint in ('/api/bootstrap', '/api/state'):
                with self.subTest(phase=phase, endpoint=endpoint):
                    response = await self.client.get(endpoint)
                    data = await response.json()
                    task = data['tasks'][0]
                    self.assertEqual(task['progress'], {'prepared': True, 'flagged': True})
                    self.assertNotIn('docs', task)
                    self.assertNotIn('practice_checks', task)
                    self.assertNotIn('results', data['exam'])
                    self.assertNotIn('result', data['operation'])
                    self.assertIsNone(data['selftest'])
                    self.assertEqual(data['history'], [])
        self.assertEqual(manager.state['practice']['d01']['notes'], 'Saved answer')
        manager.state['exam'] = None
        response = await self.client.get('/api/state')
        data = await response.json()
        self.assertEqual(data['tasks'][0]['progress']['notes'], 'Saved answer')
        self.assertTrue(data['tasks'][0]['docs'])
        self.assertTrue(data['selftest'])

    async def test_mock_blocks_study_actions_but_allows_review_flags(self):
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True, 'notes': 'Keep this note'}
        for phase in ('preparing', 'running', 'grading', 'expired'):
            manager.state['exam'] = {'state': phase, 'deadline': time.time() + 600, 'tasks': ['d01']}
            for action, body in [('hint', {}), ('solution', {}), ('grade', {}), ('check', {'criterion': 0}), ('prepare', {}), ('reset', {}), ('notes', {'notes': 'Overwrite'})]:
                with self.subTest(phase=phase, action=action):
                    response = await self.post('/api/task/d01/' + action, body)
                    self.assertEqual(response.status, 409)
            for action in ('selftest', 'clean', 'retry'):
                response = await self.post('/api/' + action, {'confirm': True})
                self.assertEqual(response.status, 409)
            response = await self.client.get('/api/export')
            self.assertEqual(response.status, 409)
            response = await self.post('/api/task/d01/notes', {'flagged': True})
            self.assertEqual(response.status, 200)
            self.assertTrue(manager.state['practice']['d01']['flagged'])
            self.assertEqual(manager.state['practice']['d01']['notes'], 'Keep this note')

    async def test_reset_discards_stale_step_checks_even_if_setup_fails(self):
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True, 'step_checks': {'0': {'status': 'pass'}}}
        with patch.object(manager.ops, 'setup', new_callable=AsyncMock, side_effect=ValueError('Fixture failure')):
            await self.post('/api/task/d01/reset')
            await manager.job
        self.assertNotIn('step_checks', manager.state['practice']['d01'])
        self.assertFalse(manager.state['practice']['d01']['prepared'])

    async def test_feedback_distinguishes_infrastructure_errors(self):
        from runtime import InfrastructureError
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True}
        with patch('runtime.Grader.evaluate', new_callable=AsyncMock, side_effect=InfrastructureError('Cluster unavailable')):
            await self.post('/api/task/d01/check', {'criterion': 0})
            await manager.job
        result = manager.state['practice']['d01']['step_checks']['0']
        self.assertEqual(result['status'], 'error')
        self.assertIn('not evidence', result['feedback']['next'])

    async def test_every_checkpoint_has_safe_structured_learning_feedback(self):
        from tutor import learning_feedback
        for task in BANK.values():
            for check in task['checks']:
                with self.subTest(task=task['id'], criterion=check['label']):
                    for status in ('pass', 'fail', 'error'):
                        feedback = learning_feedback(task, check, status)
                        self.assertTrue(feedback['concept'])
                        self.assertTrue(feedback['next'])
                        self.assertTrue(feedback['command'])
                        self.assertNotIn('set-context', feedback['command'])
                        self.assertNotIn('use-context', feedback['command'])
                    syntax = subprocess.run(['bash', '-n'], input=feedback['command'], text=True, capture_output=True)
                    self.assertEqual(syntax.returncode, 0, syntax.stderr)
                    if check.get('resource') == 'secret':
                        self.assertNotIn('-o yaml', feedback['command'])

    async def test_step_feedback_survives_restart(self):
        from manager import Manager
        manager = self.app['manager']
        manager.environment['ready'] = True
        manager.state['practice']['d01'] = {'prepared': True}
        with patch('runtime.Grader.evaluate', new_callable=AsyncMock, return_value=(True, 'Required state found.')):
            await self.post('/api/task/d01/check', {'criterion': 0})
            await manager.job
        reloaded = Manager(manager.runner, manager.directory)
        self.assertEqual(reloaded.state['practice']['d01']['step_checks'], manager.state['practice']['d01']['step_checks'])
        self.assertNotIn('last_grade', reloaded.state['practice']['d01'])

    async def test_student_kubeconfig_is_ready_and_preserves_namespace(self):
        import yaml
        from bootstrap import configure
        from runtime import Runner
        source = self.root / 'cluster.yaml'
        source.write_text(yaml.safe_dump({'clusters': [{'cluster': {'server': 'https://cluster:6443'}}], 'users': [{'user': {}}]}))
        runner = Runner(str(self.root / 'grader-config'), str(self.root / 'workspace'))
        await configure(runner, source)
        user = runner.workspace / '.kube/config'
        config = yaml.safe_load(user.read_text())
        self.assertEqual(config['current-context'], 'ckad-lab')
        self.assertEqual(yaml.safe_load(Path(runner.kubeconfig).read_text())['current-context'], 'ckad-lab')
        config['current-context'] = 'ckad-lab'
        config['contexts'][0]['context']['namespace'] = 'ckad-n09'
        user.write_text(yaml.safe_dump(config))
        await configure(runner, source)
        restored = yaml.safe_load(user.read_text())
        self.assertEqual(restored['current-context'], 'ckad-lab')
        self.assertEqual(restored['contexts'][0]['context']['namespace'], 'ckad-n09')

    async def test_selftest_uses_private_config_and_namespaced_negative_checks(self):
        from types import SimpleNamespace
        manager = self.app['manager']
        manager.environment['ready'] = True
        for tid in ('d01', 'n08', 'n10'):
            with self.subTest(task=tid), patch('manager.Runner') as candidate, patch('manager.Grader') as grader, patch.object(manager.ops, 'clean_all', new_callable=AsyncMock), patch.object(manager.ops, 'setup', new_callable=AsyncMock), patch.object(manager.ops, 'delete', new_callable=AsyncMock), patch('manager.asyncio.sleep', new_callable=AsyncMock):
                candidate.return_value.run = AsyncMock(return_value=SimpleNamespace(code=0, err=''))
                candidate.return_value.k = AsyncMock(return_value=SimpleNamespace(code=0, err=''))
                variants=[] if tid=='d01' else [{'complete':True}]
                grader.return_value.grade = AsyncMock(side_effect=[{'percent': 0, 'complete': False}, {'complete': True}, *variants, {'complete': False, 'has_errors': False}])
                manager.start_selftest([tid], 'core')
                await manager.job
                self.assertEqual(manager.selftest['passed'], 1)
                candidate.assert_called_once_with(manager.runner.kubeconfig, str(manager.runner.workspace))
                scripts = [call.args[0][-1] for call in candidate.return_value.run.await_args_list]
                self.assertEqual(len(scripts), 1)
                self.assertGreaterEqual(candidate.return_value.k.await_count,1)
                for call in candidate.return_value.k.await_args_list:
                    self.assertEqual(call.kwargs['ns'],f'ckad-{tid}')
                self.assertNotIn('kubectl config ', ''.join(scripts))

    async def test_existing_empty_context_is_initialized_and_custom_context_is_preserved(self):
        import yaml
        from bootstrap import configure
        from runtime import Runner
        source = self.root / 'cluster.yaml'
        source.write_text(yaml.safe_dump({'clusters': [{'cluster': {'server': 'https://cluster:6443'}}], 'users': [{'user': {}}]}))
        runner = Runner(str(self.root / 'grader-config'), str(self.root / 'workspace'))
        await configure(runner, source)
        user = runner.workspace / '.kube/config'
        config = yaml.safe_load(user.read_text())
        config['current-context'] = ''
        user.write_text(yaml.safe_dump(config))
        await configure(runner, source)
        config = yaml.safe_load(user.read_text())
        self.assertEqual(config['current-context'], 'ckad-lab')
        custom = {'name': 'my-practice', 'context': {'cluster': 'ckad-lab', 'user': 'ckad-admin', 'namespace': 'ckad-s02'}}
        config['contexts'] = [custom]
        config['current-context'] = 'my-practice'
        user.write_text(yaml.safe_dump(config))
        await configure(runner, source)
        restored = yaml.safe_load(user.read_text())
        self.assertEqual(restored['current-context'], 'my-practice')
        self.assertIn(custom, restored['contexts'])
        private = yaml.safe_load(Path(runner.kubeconfig).read_text())
        self.assertEqual(private['current-context'], 'ckad-lab')
        self.assertNotIn(custom, private['contexts'])

    def test_namespace_commands_preserve_documents_and_explicit_targets(self):
        from bank_helpers import namespace_script
        script = "cat > manifest.yaml <<'YAML'\nkubectl get pods\nYAML\nkubectl exec client -- sh -c 'test -n value'\nIP=$(kubectl get pod server -o jsonpath='{.status.podIP}')\nkubectl get pods -n other\nhelm list --namespace=other\nkubectl kustomize /workspace/p09/overlays/prod\n"
        expected = "cat > manifest.yaml <<'YAML'\nkubectl get pods\nYAML\nkubectl -n practice exec client -- sh -c 'test -n value'\nIP=$(kubectl -n practice get pod server -o jsonpath='{.status.podIP}')\nkubectl get pods -n other\nhelm list --namespace=other\nkubectl kustomize /workspace/p09/overlays/prod\n"
        self.assertEqual(namespace_script(script, 'practice'), expected)
        self.assertEqual(namespace_script(expected, 'practice'), expected)

    def test_all_commands_work_from_unrelated_directory_with_explicit_namespaces(self):
        import os
        from tutor import study_guide
        binary = self.root / 'bin'
        binary.mkdir()
        log = self.root / 'commands.jsonl'
        stub = f'#!{sys.executable}\nimport json, os, sys\nwith open(os.environ["COMMAND_LOG"], "a") as log: log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")\nprint("ERROR fixture")\n'
        for name in ('kubectl', 'helm', 'docker', 'curl', 'tar'):
            path = binary / name
            path.write_text(stub)
            path.chmod(0o755)
        env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'COMMAND_LOG': str(log)}
        for tid, task in BANK.items():
            with self.subTest(task=tid):
                workspace = self.root / tid
                workspace.mkdir()
                for name, content in task['files'].items():
                    path = workspace / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
                log.write_text('')
                script = task['solution'] + '\n' + study_guide(task)['verification']
                script = script.replace(task['workspace'], str(workspace))
                result = subprocess.run(['bash', '-e'], input=script, text=True, capture_output=True, cwd=self.root, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                allowed = {task['namespace'], 'default', *(item['name'] for item in task['extra_namespaces'])}
                for line in log.read_text().splitlines():
                    command = json.loads(line)
                    if command[0] not in ('kubectl', 'helm') or command[1] == 'kustomize': continue
                    self.assertNotIn('config', command)
                    self.assertIn('-n', command, command)
                    self.assertIn(command[command.index('-n') + 1], allowed, command)


if __name__ == '__main__':
    unittest.main()
