"""Persistent, real Linux PTY sessions for xterm.js. vim, Ctrl-C and job control work."""
from __future__ import annotations
import asyncio
from collections import deque
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import signal
import struct
import termios
import yaml
from aiohttp import web, WSMsgType

class TerminalLocked(web.HTTPClientError):
    status_code=423

class Shell:
    def __init__(self,name,workspace,rcfile,*,cwd=None,kubeconfig=None):
        self.name=name; self.loop=asyncio.get_running_loop(); self.clients=set(); self.buffer=bytearray(); self.dead=False
        pid,fd=pty.fork()
        if pid==0:
            try:
                os.chdir(cwd or workspace)
                env={**os.environ,'HOME':str(workspace),'TERM':'xterm-256color','COLORTERM':'truecolor',
                     'KUBECONFIG':str(kubeconfig or Path(workspace)/'.kube/config'),'HISTFILE':str(Path(workspace)/f'.history-{name}')}
                os.execvpe('/bin/bash',['bash','--noprofile','--rcfile',str(rcfile),'-i'],env)
            except BaseException as exc:
                os.write(2,(f'Could not start shell: {exc}\n').encode()); os._exit(1)
        self.pid=pid; self.fd=fd
        os.set_blocking(fd,False)
        self.loop.add_reader(fd,self.readable)
        self.resize(100,30)
    def emit(self,data):
        self.buffer.extend(data)
        if len(self.buffer)>200_000: del self.buffer[:-200_000]
        for queue in list(self.clients):
            try: queue.put_nowait(data)
            except asyncio.QueueFull:
                # Disconnect a slow consumer instead of accumulating unbounded output.
                self.clients.discard(queue)
                while not queue.empty(): queue.get_nowait()
                queue.put_nowait(None)
    def readable(self):
        if self.dead: return
        try:
            data=os.read(self.fd,65536)
            if data: self.emit(data)
            else: self.stop()
        except BlockingIOError: pass
        except OSError: self.stop()
    def resize(self,cols,rows):
        if self.dead: return
        cols=max(10,min(int(cols),400)); rows=max(4,min(int(rows),200))
        fcntl.ioctl(self.fd,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))
    async def write(self,data):
        if self.dead: return
        pending=memoryview(data)
        while pending and not self.dead:
            try:
                count=os.write(self.fd,pending); pending=pending[count:]
            except BlockingIOError: await asyncio.sleep(.01)
            except OSError: self.stop(); break
    def stop(self):
        if self.dead: return
        self.dead=True
        self.loop.remove_reader(self.fd)
        try:
            fg=os.tcgetpgrp(self.fd)
            if fg>0: os.killpg(fg,signal.SIGHUP)
        except (OSError,ProcessLookupError): pass
        try: os.killpg(self.pid,signal.SIGHUP)
        except (OSError,ProcessLookupError): pass
        try: os.close(self.fd)
        except OSError: pass
        self.emit(b'\r\n\x1b[0m[Terminal session ended. Open a new shell to continue.]\r\n')
        for queue in list(self.clients):
            try: queue.put_nowait(None)
            except asyncio.QueueFull: pass
        self.loop.create_task(self.reap())
    async def reap(self):
        for _ in range(20):
            try:
                pid,_=os.waitpid(self.pid,os.WNOHANG)
                if pid: return
            except ChildProcessError: return
            await asyncio.sleep(.1)
        try: os.killpg(self.pid,signal.SIGKILL)
        except (OSError,ProcessLookupError): pass
        try: os.waitpid(self.pid,os.WNOHANG)
        except ChildProcessError: pass

class Terminals:
    def __init__(self,workspace,rcfile,locked,kubeconfig=None):
        self.workspace=workspace; self.rcfile=rcfile; self.locked=locked; self.sessions={}
        self.kubeconfig=kubeconfig or str(Path(workspace)/'.kube/config')
    def stop_all(self):
        for shell in list(self.sessions.values()): shell.stop()
    async def websocket(self,request,task=None):
        name=request.match_info['name']
        if name not in ('main','scratch'): raise web.HTTPNotFound()
        if self.locked(): raise TerminalLocked(text='Terminal input is suspended while the exam is submitted or the lab is reset.')
        key=f'{task["id"]}-{name}' if task else name
        shell=self.sessions.get(key)
        if not shell or shell.dead:
            cwd=None; kubeconfig=None
            if task:
                cwd=Path(self.workspace)/task['id']
                kubeconfig=Path(self.workspace)/'.kube'/f'{task["id"]}.yaml'
                if not any(k.startswith(task['id']+'-') and not value.dead for k,value in self.sessions.items()):
                    config=yaml.safe_load(Path(self.kubeconfig).read_text())
                    config['current-context']='ckad-lab'
                    context=next(x for x in config['contexts'] if x['name']=='ckad-lab')
                    context['context']['namespace']=task['namespace']
                    kubeconfig.parent.mkdir(parents=True,exist_ok=True)
                    kubeconfig.touch(mode=0o600,exist_ok=True); kubeconfig.chmod(0o600)
                    kubeconfig.write_text(yaml.safe_dump(config))
            shell=Shell(key,self.workspace,self.rcfile,cwd=cwd,kubeconfig=kubeconfig); self.sessions[key]=shell
        ws=web.WebSocketResponse(heartbeat=25,max_msg_size=65536)
        await ws.prepare(request)
        queue=asyncio.Queue(maxsize=128)
        # No await between buffer capture and subscribing: no output gap on reconnect.
        backlog=bytes(shell.buffer); shell.clients.add(queue)
        await ws.send_bytes(b'\x1b[0m'+backlog)
        async def sender():
            while True:
                data=await queue.get()
                if data is None:
                    await ws.close(); return
                await ws.send_bytes(data)
        send_task=asyncio.create_task(sender())
        try:
            async for msg in ws:
                if msg.type==WSMsgType.TEXT:
                    try: data=json.loads(msg.data)
                    except json.JSONDecodeError: continue
                    if not isinstance(data,dict): continue
                    if data.get('type')=='resize':
                        try: shell.resize(data.get('cols',100),data.get('rows',30))
                        except (TypeError,ValueError,OSError): pass
                    elif data.get('type')=='input' and isinstance(data.get('data'),str) and not self.locked():
                        await shell.write(data['data'].encode())
                elif msg.type==WSMsgType.BINARY and not self.locked(): await shell.write(msg.data)
                elif msg.type in (WSMsgType.ERROR,WSMsgType.CLOSE): break
        finally:
            shell.clients.discard(queue); send_task.cancel()
            await asyncio.gather(send_task,return_exceptions=True)
        return ws
