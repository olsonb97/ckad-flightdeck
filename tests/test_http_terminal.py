"""Real local HTTP + WebSocket + Bash PTY tests; no Kubernetes is mocked as a product feature."""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
if not (Path(__file__).resolve().parents[1]/'app').exists():sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestClient,TestServer
from aiohttp import WSMsgType,WSServerHandshakeError
from server import create_app

class HTTPAndPTYTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.app=create_app(workspace=str(self.root/'workspace'),state_dir=str(self.root/'state'),start_cluster=False)
        self.client=TestClient(TestServer(self.app));await self.client.start_server()
        response=await self.client.get('/api/bootstrap');self.data=await response.json();self.csrf=self.data['csrf'];self.origin=str(self.client.make_url('/')).rstrip('/')
    async def asyncTearDown(self):await self.client.close();await asyncio.sleep(.15);self.tmp.cleanup()
    async def post(self,path,data=None,headers=None):return await self.client.post(path,json=data or {},headers=headers or {'X-CSRF-Token':self.csrf})
    async def ws(self,name='main',token=None,task=None):return await self.client.ws_connect('/ws/'+name+'?token='+(token or self.csrf)+('&task='+task if task else ''),headers={'Origin':self.origin})
    async def wait_file(self,name,expected=None):
        path=self.root/'workspace'/name
        for _ in range(80):
            if path.exists() and (expected is None or path.read_text()==expected):return path
            await asyncio.sleep(.05)
        shell=next(iter(self.app['terminals'].sessions.values()))
        self.fail(f'Real shell did not produce expected file: {name}; log: {bytes(shell.buffer)[-1500:]!r}')
    async def test_homepage_and_assets(self):
        for path in ('/','/static/app.js','/static/style.css','/static/vendor/terminal.js','/static/vendor/terminal.css'):
            response=await self.client.get(path);self.assertEqual(response.status,200);self.assertGreater(len(await response.read()),500)
    async def test_health_is_separate_from_cluster_readiness(self):
        response=await self.client.get('/healthz');self.assertEqual(await response.json(),{'app':'ok','cluster_ready':False})
    async def test_no_simulated_cluster_in_development_mode(self):self.assertFalse(self.data['environment']['ready']);self.assertEqual(self.data['environment']['phase'],'unavailable')
    async def test_missing_csrf_is_rejected(self):
        response=await self.client.post('/api/task/d01/notes',json={'notes':'test'});self.assertEqual(response.status,403)
    async def test_invalid_csrf_is_rejected(self):
        response=await self.post('/api/task/d01/notes',headers={'X-CSRF-Token':'wrong'});self.assertEqual(response.status,403)
    async def test_cross_origin_is_rejected(self):
        response=await self.post('/api/task/d01/notes',headers={'X-CSRF-Token':self.csrf,'Origin':'https://malicious.example'});self.assertEqual(response.status,403)
    async def test_nonlocal_host_is_rejected(self):
        response=await self.client.get('/api/bootstrap',headers={'Host':'malicious.example'});self.assertEqual(response.status,403)
    async def test_notes_write_and_read(self):
        response=await self.post('/api/task/d01/notes',{'notes':'A saved note','flagged':True});self.assertEqual(response.status,200)
        response=await self.client.get('/api/state');t=(await response.json())['tasks'][0];self.assertEqual(t['progress']['notes'],'A saved note');self.assertTrue(t['progress']['flagged'])
    async def test_unknown_task_rejected(self):
        response=await self.post('/api/task/not-a-task/prepare');self.assertEqual(response.status,400)
    async def test_prepare_requires_live_cluster(self):
        response=await self.post('/api/task/d01/prepare');self.assertEqual(response.status,409)
    async def test_unsafe_action_requires_confirmation(self):
        response=await self.post('/api/clean');self.assertEqual(response.status,400)
    async def test_solution_returns_worked_commands(self):
        response=await self.post('/api/task/d01/solution');self.assertEqual(response.status,200);self.assertIn('kubectl -n ckad-d01 apply',(await response.json())['solution'])
    async def test_active_mock_hides_solution(self):
        self.app['manager'].state['exam']={'state':'running','deadline':time.time()+60,'tasks':['d01']}
        response=await self.post('/api/task/d01/solution');self.assertEqual(response.status,409)
    async def test_export_is_not_available_during_mock(self):
        self.app['manager'].state['exam']={'state':'running','deadline':time.time()+60,'tasks':['d01']}
        response=await self.client.get('/api/export');self.assertEqual(response.status,409)
    async def test_json_array_is_rejected(self):
        response=await self.client.post('/api/task/d01/notes',json=[],headers={'X-CSRF-Token':self.csrf});self.assertEqual(response.status,400)
    async def test_bad_json_is_handled(self):
        response=await self.client.post('/api/task/d01/notes',data='{bad',headers={'X-CSRF-Token':self.csrf,'Content-Type':'application/json'});self.assertEqual(response.status,400)
    async def test_security_headers_present(self):
        response=await self.client.get('/');self.assertEqual(response.headers['X-Frame-Options'],'DENY');self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
    async def test_ws_requires_valid_token(self):
        with self.assertRaises(WSServerHandshakeError) as caught:await self.ws(token='wrong')
        self.assertEqual(caught.exception.status,403)
    async def test_ws_requires_origin(self):
        with self.assertRaises(WSServerHandshakeError) as caught:await self.client.ws_connect('/ws/main?token='+self.csrf)
        self.assertEqual(caught.exception.status,403)
    async def test_ws_is_locked_at_expiry(self):
        self.app['manager'].state['exam']={'state':'running','deadline':time.time()-1,'tasks':['d01']}
        with self.assertRaises(WSServerHandshakeError) as caught:await self.ws()
        self.assertEqual(caught.exception.status,423)
    async def test_actual_bash_writes_file(self):
        ws=await self.ws();await ws.send_json({'type':'input','data':"printf 'real-pty\\n' > bash-result.txt\r"})
        await self.wait_file('bash-result.txt','real-pty\n');await ws.close()
    async def test_websocket_reconnection_preserves_shell_state(self):
        ws=await self.ws();await ws.send_json({'type':'input','data':"export PERSIST_TEST=works; printf ready > first.txt\r"});await self.wait_file('first.txt');await ws.close()
        pid=self.app['terminals'].sessions['main'].pid
        ws=await self.ws();await ws.send_json({'type':'input','data':'printf %s "$PERSIST_TEST" > second.txt\r'});await self.wait_file('second.txt','works');self.assertEqual(pid,self.app['terminals'].sessions['main'].pid);await ws.close()
    async def test_ctrl_c_interrupts_foreground_command(self):
        ws=await self.ws();await ws.send_json({'type':'input','data':'sleep 60\r'});await asyncio.sleep(.15);await ws.send_json({'type':'input','data':'\x03'});await asyncio.sleep(.1)
        await ws.send_json({'type':'input','data':'printf interrupted > ctrl-c.txt\r'});await self.wait_file('ctrl-c.txt','interrupted');await ws.close()
    async def test_real_vim_editing_in_pty(self):
        if not shutil.which('vim'):self.skipTest('vim is not installed on this test host')
        ws=await self.ws();await ws.send_json({'type':'resize','cols':110,'rows':32});await ws.send_json({'type':'input','data':'vim -u NONE -n -i NONE editor.yaml\r'});await asyncio.sleep(.35)
        await ws.send_json({'type':'input','data':'iapiVersion: v1\nkind: Pod\x1b:wq\r'});await self.wait_file('editor.yaml','apiVersion: v1\nkind: Pod\n');await ws.close()
    async def test_terminal_tabs_are_independent_shells(self):
        first=await self.ws();second=await self.ws('scratch');self.assertNotEqual(self.app['terminals'].sessions['main'].pid,self.app['terminals'].sessions['scratch'].pid);await first.close();await second.close()
    async def test_question_shells_have_isolated_namespace_and_directory(self):
        import yaml
        source=self.root/'grader.yaml'
        source.write_text(yaml.safe_dump({'apiVersion':'v1','kind':'Config','current-context':'ckad-lab','contexts':[{'name':'ckad-lab','context':{'cluster':'ckad-lab','user':'test','namespace':'ckad-s02'}}],'clusters':[],'users':[]}))
        self.app['terminals'].kubeconfig=str(source)
        manager=self.app['manager'];manager.environment['ready']=True
        paths=[]
        for tid in ('s01','s02'):
            (self.root/'workspace'/tid).mkdir()
            manager.state['practice'][tid]={'prepared':True}
            ws=await self.ws(task=tid)
            await ws.send_json({'type':'input','data':'printf %s "$KUBECONFIG" > config-path.txt; pwd > location.txt\r'})
            path=await self.wait_file(tid+'/config-path.txt')
            cfg=Path(path.read_text());paths.append(cfg)
            value=yaml.safe_load(cfg.read_text())
            self.assertEqual(value['contexts'][0]['context']['namespace'],'ckad-'+tid)
            await self.wait_file(tid+'/location.txt',str((self.root/'workspace'/tid).resolve())+'\n')
            await ws.close()
        self.assertNotEqual(paths[0],paths[1])
        first=self.app['terminals'].sessions['s01-main']
        ws=await self.ws(task='s01')
        self.assertEqual(self.app['terminals'].sessions['s01-main'].pid,first.pid)
        self.assertEqual(yaml.safe_load(source.read_text())['contexts'][0]['context']['namespace'],'ckad-s02')
        await ws.close()

    async def test_question_shell_cannot_open_before_fixtures_are_prepared(self):
        self.app['manager'].environment['ready']=True
        with self.assertRaises(WSServerHandshakeError) as caught: await self.ws(task='s01')
        self.assertEqual(caught.exception.status,423)
        with self.assertRaises(WSServerHandshakeError) as caught: await self.ws(task='missing')
        self.assertEqual(caught.exception.status,404)

    async def test_unknown_terminal_name_is_rejected(self):
        with self.assertRaises(WSServerHandshakeError) as caught:await self.ws('other')
        self.assertEqual(caught.exception.status,404)
    async def test_malformed_ws_message_does_not_crash_shell(self):
        ws=await self.ws();await ws.send_str('[]');await ws.send_str('invalid json');await ws.send_json({'type':'input','data':'printf survived > safe.txt\r'});await self.wait_file('safe.txt','survived');await ws.close()

if __name__=='__main__':unittest.main()
