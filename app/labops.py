"""Repeatable, bounded task setup and teardown in the dedicated lab cluster."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import shutil
import yaml
from bank import BANK
from runtime import Runner,InfrastructureError

LABEL='ckad.flightdeck/task'
RESET_IMAGES={'d09':['ckad-site:1.0'],'d10':['ckad-tools:release'],'s05':['my-app:1.0']}

class LabOperations:
    def __init__(self,runner): self.runner=runner
    async def assert_lab(self):
        r=await self.runner.k('get','configmap','ckad-flightdeck','-n','kube-system','-o','json')
        if r.code: raise InfrastructureError('Dedicated lab safety marker missing. Refusing setup or deletion.')
        data=json.loads(r.out).get('data',{})
        if data.get('purpose')!='disposable-ckad-practice':
            raise InfrastructureError('Cluster is not marked as the disposable CKAD lab.')
    def namespaces(self,task):
        return [task['namespace']]+[n['name'] for n in task.get('extra_namespaces',[])]
    async def delete(self,task,files=True):
        await self.assert_lab()
        names=self.namespaces(task)
        if any(not n.startswith('ckad-'+task['id']) for n in names): raise RuntimeError('Unsafe task namespace')
        r=await self.runner.k('delete','namespace',*names,'--ignore-not-found=true','--wait=true','--timeout=90s',timeout=100)
        if r.code: raise InfrastructureError('Task namespace deletion did not finish. Inspect finalizers/events: '+r.err[:350])
        for image in RESET_IMAGES.get(task['id'],[]):
            result=await self.runner.run(['docker','image','rm','-f',image])
            if result.code and 'No such image' not in result.err and 'No such object' not in result.err:
                raise InfrastructureError('Could not reset the isolated builder image: '+result.err[:200])
        if files:
            path=self.runner.map_path(task['workspace'])
            if path==self.runner.workspace: raise RuntimeError('Refusing to delete the entire workspace')
            if path.exists(): shutil.rmtree(path)
    async def clean_all(self,tasks=None):
        await self.assert_lab()
        tasks=list(BANK.values()) if tasks is None else list(tasks)
        if not tasks or any(task['id'] not in BANK for task in tasks): raise ValueError('Invalid cleanup scope.')
        names=[]
        for task in tasks: names+=self.namespaces(task)
        r=await self.runner.k('delete','namespace',*names,'--ignore-not-found=true','--wait=true','--timeout=120s',timeout=135)
        if r.code: raise InfrastructureError('Could not remove all task namespaces. No finalizers were force-removed. '+r.err[:300])
        for image in [image for task in tasks for image in RESET_IMAGES.get(task['id'],[])]:
            result=await self.runner.run(['docker','image','rm','-f',image])
            if result.code and 'No such image' not in result.err and 'No such object' not in result.err:
                raise InfrastructureError('Builder reset failed: '+result.err[:200])
        for task in tasks:
            path=self.runner.map_path(task['workspace'])
            if path.exists(): shutil.rmtree(path)
    async def setup(self,task,reset=True):
        await self.assert_lab()
        if reset: await self.delete(task)
        path=self.runner.map_path(task['workspace']); path.mkdir(parents=True,exist_ok=True)
        (path/'TASK.txt').write_text(task['title']+'\n\nNamespace: '+task['namespace']+'\n\n'+'\n'.join(f'{i+1}. {x}' for i,x in enumerate(task['requirements']))+'\n')
        for filename,content in task['files'].items():
            target=(path/filename).resolve()
            if path not in target.parents: raise RuntimeError('Unsafe starter file path')
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists(): target.write_text(content)
        namespaces=[{'name':task['namespace'],'labels':{}}]+task.get('extra_namespaces',[])
        for item in namespaces:
            doc={'apiVersion':'v1','kind':'Namespace','metadata':{'name':item['name'],'labels':{LABEL:task['id'],'ckad.flightdeck/managed':'true',**item.get('labels',{})}}}
            r=await self.runner.k('apply','-f','-',stdin=json.dumps(doc))
            if r.code: raise InfrastructureError(r.err[:500])
        if task['seeds']:
            r=await self.runner.k('apply','-f','-',stdin=yaml.safe_dump_all(task['seeds']),timeout=45)
            if r.code: raise InfrastructureError('Fixture setup failed: '+r.err[:600])
        for operation in task['setup']:
            r=await self.runner.run(operation['command'],timeout=operation.get('timeout',45),cwd=str(path))
            if r.code: raise InfrastructureError('Fixture command failed: '+r.err[:600])
        await self.wait_fixtures(task)
        return True

    async def wait_fixtures(self,task):
        """Only wait for fixtures that are intended to be healthy at the start."""
        async def wait(item):
            kind=item['kind']; name=item['metadata']['name']; ns=item['metadata'].get('namespace',task['namespace'])
            if kind=='Pod':
                r=await self.runner.k('wait','--for=condition=Ready','pod/'+name,'--timeout=180s',ns=ns,timeout=190)
            elif kind=='Deployment' and task['id'] not in ('p03','o04','o05','o08'):
                r=await self.runner.run(['kubectl','-n',ns,'rollout','status','deployment/'+name,'--timeout=180s'],timeout=190)
            else: return
            if r.code: raise InfrastructureError('Healthy starter fixture did not become ready: '+name+'. '+r.err[:300])
        await asyncio.gather(*(wait(item) for item in task['seeds']))
        if task['id']=='o06':
            for _ in range(60):
                r=await self.runner.k('top','pods','-l','metrics-task=true','--no-headers',ns=task['namespace'])
                if r.code==0 and 'cpu-worker' in r.out and 'idle' in r.out: return
                await asyncio.sleep(2)
            raise InfrastructureError('Metrics-server has not produced metrics for the two starter Pods.')
