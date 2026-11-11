"""Local-only aiohttp application. HTTP is intentionally not a public shell service."""
from __future__ import annotations
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from aiohttp import web
from bank import BANK,BANK_VERSION
from bootstrap import bootstrap, widget_controller
from manager import Manager, BusyError
from runtime import Runner, InfrastructureError
from terminal import Terminals, TerminalLocked

HERE=Path(__file__).resolve().parent
LOCAL_HOSTS={'localhost','127.0.0.1','::1'}

def hostname(authority):
    try: return urlsplit('http://'+authority).hostname
    except ValueError: return None

@web.middleware
async def protection(request,handler):
    if hostname(request.host) not in LOCAL_HOSTS:
        raise web.HTTPForbidden(text='This lab accepts localhost connections only.')
    origin=request.headers.get('Origin')
    if origin:
        try:
            parsed=urlsplit(origin)
            permitted=parsed.scheme=='http' and parsed.netloc.lower()==request.host.lower()
        except ValueError: permitted=False
        if not permitted: raise web.HTTPForbidden(text='Cross-origin access is not allowed.')
    if request.path.startswith('/ws/') and not origin:
        raise web.HTTPForbidden(text='A same-origin browser connection is required.')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),request.app['csrf']):
            raise web.HTTPForbidden(text='Missing or invalid session token. Reload the page.')
        if request.content_type!='application/json': raise web.HTTPUnsupportedMediaType(text='Send application/json.')
    try:
        response=await handler(request)
    except (BusyError,InfrastructureError,ValueError,KeyError) as exc:
        status=409 if isinstance(exc,(BusyError,InfrastructureError)) else 400
        response=web.json_response({'error':str(exc)},status=status)
    if not isinstance(response,web.WebSocketResponse):
        response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'Cache-Control':'no-store'})
    return response

async def state(request):
    data=request.app['manager'].snapshot()
    data['instance']=request.app['instance']
    if request.path=='/api/bootstrap': data['csrf']=request.app['csrf']
    return web.json_response(data)

async def health(request):
    return web.json_response({'app':'ok','cluster_ready':request.app['manager'].environment['ready']})

async def action(request):
    m=request.app['manager']; data=await request.json()
    if not isinstance(data,dict): raise ValueError('Expected a JSON object.')
    kind=request.match_info['action']; tid=request.match_info.get('tid')
    if tid:
        if tid not in BANK: raise ValueError('Unknown task ID.')
        if kind in ('prepare','reset'): result=await m.prepare(tid,reset=kind=='reset')
        elif kind=='grade': result=m.grade(tid)
        elif kind=='check':
            if data.get('criterion') is None: raise ValueError('Choose a valid practice checkpoint.')
            result=m.grade(tid,data['criterion'])
        elif kind in ('hint','solution'): result=m.reveal(tid,kind)
        elif kind=='notes': result=m.save_notes(tid,data.get('notes'),data.get('flagged'))
        else: raise ValueError('Unknown question action.')
    else:
        if kind=='exam-start': result=m.start_exam(data.get('seed'),data.get('set_id','core'))
        elif kind=='exam-submit': result=m.submit_exam()
        elif kind=='exam-leave': result=m.leave_exam(abandon=data.get('abandon') is True)
        elif kind=='clean':
            if data.get('confirm') is not True: raise ValueError('Explicit confirmation is required.')
            result=m.cleanup()
        elif kind=='selftest':
            if data.get('confirm') is not True: raise ValueError('Explicit confirmation is required; this resets the question labs.')
            ids=data.get('ids')
            if ids is not None and (not isinstance(ids,list) or any(not isinstance(x,str) for x in ids)): raise ValueError('ids must be a list of task IDs.')
            result=m.start_selftest(ids,data.get('set_id'))
        elif kind=='retry':
            if m.busy() or m.exam_active(): raise BusyError('Finish the active operation or mock first.')
            old=request.app.get('bootstrap_task')
            if old and not old.done(): raise BusyError('Lab initialization is still running.')
            m.environment.update(ready=False,phase='starting',message='Rechecking the lab…',error=None)
            request.app['bootstrap_task']=asyncio.create_task(bootstrap(m)); result={'ok':True}
        else: raise ValueError('Unknown action.')
    return web.json_response(result)

async def export(request):
    m=request.app['manager']
    if m.exam_active(): raise BusyError('Submit the mock before exporting results.')
    data={'exported_at':m.snapshot()['server_time'],'bank_version':BANK_VERSION,'progress':m.state,'live_selftest':m.selftest}
    return web.Response(text=json.dumps(data,indent=2),content_type='application/json',headers={'Content-Disposition':'attachment; filename="ckad-flightdeck-progress.json"'})

async def ws(request):
    if not secrets.compare_digest(request.query.get('token',''),request.app['csrf']):
        raise web.HTTPForbidden(text='Invalid terminal token. Reload the page.')
    task=None
    if tid:=request.query.get('task'):
        if tid not in BANK: raise web.HTTPNotFound()
        manager=request.app['manager']
        if manager.exam_active() and tid not in manager.state['exam']['tasks']: raise web.HTTPForbidden(text='Question is not part of this mock.')
        if not manager.environment['ready'] or not manager.state['practice'].get(tid,{}).get('prepared'):
            raise TerminalLocked(text='Question is still being prepared.')
        task=BANK[tid]
    return await request.app['terminals'].websocket(request,task)

async def index(request): return web.FileResponse(HERE/'static/index.html')

async def lifecycle(app):
    m=app['manager']
    if app['start_cluster']:
        app['bootstrap_task']=asyncio.create_task(bootstrap(m))
        app['controller_task']=asyncio.create_task(widget_controller(m))
    else:
        m.environment.update(phase='unavailable',message='UI/PTY development mode: no Kubernetes cluster is connected.',error='Start with Docker Compose to use real Kubernetes tasks.')
    app['timer_task']=asyncio.create_task(m.timer_loop())
    yield
    m.closed=True; app['terminals'].stop_all()
    pending=[app.get(k) for k in ('bootstrap_task','controller_task','timer_task')]+[m.job]
    for task in pending:
        if task and not task.done(): task.cancel()
    for task in pending:
        if task:
            with contextlib.suppress(asyncio.CancelledError,Exception): await task

def create_app(*,workspace=None,state_dir=None,start_cluster=True):
    workspace=workspace or os.getenv('WORKSPACE','/workspace')
    Path(workspace).mkdir(parents=True,exist_ok=True)
    runner=Runner(os.getenv('GRADER_KUBECONFIG','/run/lab-kubeconfig'),workspace)
    m=Manager(runner,state_dir or os.getenv('DATA_DIR','/data'))
    app=web.Application(middlewares=[protection],client_max_size=128*1024)
    app['instance']=secrets.token_hex(12)
    app['manager']=m; app['csrf']=secrets.token_urlsafe(32); app['start_cluster']=start_cluster
    app['terminals']=Terminals(str(runner.workspace),str(HERE/'shellrc'),m.locked,runner.kubeconfig); m.terminals=app['terminals']
    app.add_routes([web.get('/',index),web.get('/healthz',health),web.get('/api/bootstrap',state),web.get('/api/state',state),web.get('/api/export',export),
      web.post('/api/task/{tid}/{action}',action),web.post('/api/{action}',action),web.get('/ws/{name}',ws)])
    app.router.add_static('/static/',HERE/'static',show_index=False,follow_symlinks=False)
    app.cleanup_ctx.append(lifecycle)
    return app

if __name__=='__main__':
    web.run_app(create_app(start_cluster=os.getenv('FLIGHTDECK_DEV_NO_CLUSTER')!='1'),host=os.getenv('BIND_HOST','0.0.0.0'),port=int(os.getenv('PORT','8080')),access_log=None)
