"""Bring up a genuine K3s-backed lab and verify critical runtime capabilities."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import time
import yaml
from bank_helpers import obj,pod,sleeper,http_container,container,NGINX,NGINX_NEW,BUSYBOX
from runtime import InfrastructureError,is_ready,Grader

CRD={
 'apiVersion':'apiextensions.k8s.io/v1','kind':'CustomResourceDefinition',
 'metadata':{'name':'widgets.practice.ckad.local','labels':{'ckad.flightdeck/managed':'true'}},
 'spec':{'group':'practice.ckad.local','scope':'Namespaced','names':{'plural':'widgets','singular':'widget','kind':'Widget','shortNames':['wdg']},
 'versions':[{'name':'v1','served':True,'storage':True,'schema':{'openAPIV3Schema':{'type':'object','required':['spec'],'properties':{
   'spec':{'type':'object','required':['image','replicas'],'properties':{
     'image':{'type':'string','minLength':1,'description':'Container image for the generated web Deployment.'},
     'replicas':{'type':'integer','minimum':1,'maximum':5,'description':'Desired replicas (1 through 5).'}
   }}
 }}}}]}}

class StartupBlocked(InfrastructureError): pass


async def startup_k(runner,*args,retry_timeout=45,**kwargs):
    """Retry temporary API failures during startup, including OpenAPI warmup."""
    deadline=time.monotonic()+retry_timeout
    request_timeout=kwargs.pop('timeout',30)
    transient=('the server is currently unable to handle the request','serviceunavailable',
        'service unavailable','connection refused','connection reset by peer','tls handshake timeout',
        'i/o timeout','context deadline exceeded','unexpected eof')
    last=None
    while time.monotonic()<deadline:
        remaining=max(.001,deadline-time.monotonic())
        try:
            async with asyncio.timeout(remaining):
                last=await runner.k(*args,timeout=min(request_timeout,remaining),**kwargs)
        except TimeoutError as exc:
            raise InfrastructureError('Kubernetes startup request timed out during '+str(args[0])+'.') from exc
        if not last.code or not any(message in (last.err+'\n'+last.out).lower() for message in transient):
            return last
        await asyncio.sleep(min(2,max(0,deadline-time.monotonic())))
    if last is not None: return last
    raise InfrastructureError('Kubernetes startup request had no time to complete.')


async def base_ready(manager,*,stale_grace_elapsed=False):
    runner=manager.runner; checks={}; manager.environment['checks']=checks
    def pending(reasons):
        manager.environment.update(message='Waiting for '+'; '.join(reasons)+'.',blockers=reasons)
        return False
    r=await runner.k('get','nodes','-o','json')
    checks['kubernetes_api']=r.code==0
    if r.code:
        if any(reason in r.err.lower() for reason in ('unauthorized','forbidden','x509:')):
            raise StartupBlocked('Kubernetes rejected the lab kubeconfig. Check cluster startup and recheck the environment.')
        return pending(['the Kubernetes API; check docker compose logs cluster'])
    nodes={node['metadata']['name']:node for node in json.loads(r.out)['items']}
    blockers=[]; stalled=[]
    for name,service in (('ckad-control','cluster'),('ckad-worker','worker')):
        node=nodes.get(name)
        condition=next((c for c in (node or {}).get('status',{}).get('conditions',[]) if c.get('type')=='Ready'),{})
        checks['node_'+name]=condition.get('status')=='True'
        if not node: blockers.append(name+' to register')
        elif not checks['node_'+name]:
            stale=condition.get('status')=='Unknown' and condition.get('reason')=='NodeStatusUnknown'
            blockers.append(name+(' (not reporting)' if stale else ' ('+condition.get('reason','not Ready')+')'))
            if stale: stalled.append((name,service))
    if blockers:
        pending(blockers)
        if stalled and stale_grace_elapsed:
            name,service=stalled[0]
            raise StartupBlocked(f'{name} is not reporting node status. Check docker compose logs {service}. '
                'If the log says "Node password rejected", the node identity and its registration disagree. '
                'Repair that registration, preserve /etc/rancher/node in its Docker volume, then retry startup. Do not delete the lab data volumes.')
        return False
    r=await runner.k('get','deployments','-n','kube-system','-o','json')
    if r.code: return pending(['system controllers; check docker compose logs cluster'])
    deployments={d['metadata']['name']:d for d in json.loads(r.out)['items']}
    for name in ('coredns','traefik','metrics-server','local-path-provisioner'):
        checks['controller_'+name]=is_ready(deployments.get(name))
        if not checks['controller_'+name]: blockers.append(name)
    if blockers:
        r=await runner.k('get','pods','-n','kube-system','-o','json')
        if not r.code:
            for pod in json.loads(r.out)['items']:
                statuses=pod.get('status',{}).get('initContainerStatuses',[])+pod.get('status',{}).get('containerStatuses',[])
                reasons={s.get('state',{}).get('waiting',{}).get('reason') for s in statuses}
                reasons.discard(None)
                if reasons: blockers.append(pod['metadata']['name']+': '+', '.join(sorted(reasons)))
        return pending(blockers)
    r=await runner.k('get','storageclass','local-path','-o','json')
    checks['storage_class']=r.code==0
    if r.code: return pending(['storage class local-path'])
    r=await runner.run(['docker','info','--format','{{.ServerVersion}}'],timeout=20)
    checks['image_builder']=r.code==0
    if r.code: return pending(['the image builder; check docker compose logs builder'])
    manager.environment['blockers']=[]
    return True


async def configure(runner,source):
    source=Path(source)
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        try:
            data=yaml.safe_load(source.read_text())
            if not isinstance(data,dict) or not data.get('clusters') or not data.get('users'): raise ValueError('Incomplete kubeconfig')
            cluster=data['clusters'][0]['cluster']; cluster['server']='https://cluster:6443'
            config={'apiVersion':'v1','kind':'Config','clusters':[{'name':'ckad-lab','cluster':cluster}],
                'users':[{'name':'ckad-admin','user':data['users'][0]['user']}],
                'contexts':[{'name':'ckad-lab','context':{'cluster':'ckad-lab','user':'ckad-admin','namespace':'default'}}],'current-context':'ckad-lab'}
            private=Path(runner.kubeconfig); private.parent.mkdir(parents=True,exist_ok=True)
            private.write_text(yaml.safe_dump(config)); private.chmod(0o600)
            user=runner.workspace/'.kube/config'; user.parent.mkdir(parents=True,exist_ok=True)
            if user.exists():
                try:
                    old=yaml.safe_load(user.read_text())
                    namespace=next((x['context'].get('namespace','default') for x in old['contexts'] if x['name']=='ckad-lab'),'default')
                    config['contexts'][0]['context']['namespace']=namespace
                    for key in ('clusters','users','contexts'):
                        managed=config[key][0]['name']
                        config[key].extend(x for x in old.get(key,[]) if x['name']!=managed)
                    selected=old.get('current-context')
                    if selected and any(x['name']==selected for x in config['contexts']): config['current-context']=selected
                except (KeyError,ValueError,StopIteration,TypeError,yaml.YAMLError): pass
            user.write_text(yaml.safe_dump(config)); user.chmod(0o600)
            return
        except (FileNotFoundError,KeyError,ValueError,TypeError,yaml.YAMLError):
            await asyncio.sleep(2)
    raise InfrastructureError('K3s has not written a usable kubeconfig. Check docker compose logs cluster.')

async def wait_until(predicate,description,timeout=300):
    deadline=time.monotonic()+timeout; last=''
    while time.monotonic()<deadline:
        try:
            async with asyncio.timeout(max(0,deadline-time.monotonic())):
                if await predicate(): return
        except StartupBlocked: raise
        except InfrastructureError as exc: last=str(exc)
        except TimeoutError: break
        await asyncio.sleep(min(2,max(0,deadline-time.monotonic())))
    raise InfrastructureError(description+(' '+last if last else ''))

async def bootstrap(manager):
    runner=manager.runner
    manager.environment.update(started_at=time.time(),checks={},blockers=[])
    def stage(message):
        manager.environment.update(ready=False,phase='starting',message=message,error=None,blockers=[])
    try:
        stage('Waiting for the dedicated Kubernetes kubeconfig…')
        await configure(runner,os.environ.get('K3S_CONFIG','/kube/k3s.yaml'))
        stage('Waiting for both Kubernetes nodes and bundled controllers…')
        node_wait_started=time.monotonic()
        await wait_until(lambda: base_ready(manager,stale_grace_elapsed=time.monotonic()-node_wait_started>=30),
            'Cluster startup timed out. Check the blocked components and docker compose logs cluster worker builder.',timeout=180)
        r=await startup_k(runner,'version','-o','json')
        if r.code: raise InfrastructureError('Cannot read the server version.')
        version=json.loads(r.out).get('serverVersion',{}).get('gitVersion','unknown')
        if not version.startswith('v1.35.'):
            raise InfrastructureError(f'This bank targets Kubernetes 1.35; the detected server is {version}. Align K3S_IMAGE and KUBECTL_VERSION before studying.')
        manager.environment['version']=version
        marker=obj('ConfigMap','ckad-flightdeck',data={'purpose':'disposable-ckad-practice','bank':'2026-09-14','version':'1'})
        marker['metadata']['namespace']='kube-system'
        r=await startup_k(runner,'apply','-f','-',stdin=yaml.safe_dump_all([marker,CRD]),timeout=45)
        if r.code: raise InfrastructureError('Could not register the lab marker and training CRD: '+r.err[:400])
        r=await runner.k('wait','--for=condition=Established','crd/widgets.practice.ckad.local','--timeout=90s',timeout=100)
        if r.code: raise InfrastructureError('The training CRD did not become established.')
        stage('Warming the question images on both nodes and checking real cross-node networking…')
        ns='ckad-health'
        r=await startup_k(runner,'delete','namespace',ns,'--ignore-not-found=true','--wait=true','--timeout=90s',timeout=100,retry_timeout=100)
        if r.code: raise InfrastructureError('Could not clear the previous startup probes: '+r.err[:400])
        target=pod('backend',[http_container('HEALTH OK')],labels={'app':'backend'},nodeSelector={'kubernetes.io/hostname':'ckad-control'})
        source=sleeper('client'); source['spec']['nodeSelector']={'kubernetes.io/hostname':'ckad-worker'}
        warm=obj('DaemonSet','image-warmup',{'selector':{'matchLabels':{'app':'image-warmup'}},'template':{'metadata':{'labels':{'app':'image-warmup'}},'spec':{
            'initContainers':[container('nginx-old',NGINX,['sh','-c','true']),container('nginx-new',NGINX_NEW,['sh','-c','true'])],
            'containers':[container('cache',BUSYBOX,['sh','-c','sleep 86400'])]}}},api='apps/v1')
        objects=[obj('Namespace',ns,labels={'ckad.flightdeck/managed':'true'}),target,source,warm]
        for item in objects[1:]: item['metadata']['namespace']=ns
        r=await startup_k(runner,'apply','-f','-',stdin=yaml.safe_dump_all(objects),timeout=45)
        if r.code: raise InfrastructureError('Runtime smoke-test fixtures could not be created: '+r.err[:400])
        async def smoke_ready():
            blockers=[]
            for resource,name in [('pod','backend'),('pod','client'),('daemonset','image-warmup')]:
                r=await runner.k('get',resource,name,'-o','json',ns=ns)
                value=json.loads(r.out) if not r.code else None
                healthy=is_ready(value)
                manager.environment['checks']['probe_'+name]=healthy
                if not healthy:
                    status=(value or {}).get('status',{})
                    containers=status.get('initContainerStatuses',[])+status.get('containerStatuses',[])
                    reasons={c.get('state',{}).get('waiting',{}).get('reason') for c in containers}
                    reasons.discard(None)
                    blockers.append(name+': '+(', '.join(sorted(reasons)) or status.get('phase','not Ready')))
            manager.environment['blockers']=blockers
            if blockers: manager.environment['message']='Waiting for health probes: '+'; '.join(blockers)+'.'
            return not blockers
        await wait_until(smoke_ready,'The image warmup or cross-node probe Pods did not become Ready. Inspect image pull events.',timeout=360)
        test_task={'namespace':ns,'id':'health','checks':[]}
        criterion={'kind':'traffic','source':'client','target':'backend','allowed':True,'port':8080}
        ok,detail=await Grader(runner,test_task).evaluate(criterion)
        if not ok: raise InfrastructureError('Cross-node baseline connectivity failed: '+detail)
        r=await runner.k('exec','client','--','nslookup','kubernetes.default.svc.cluster.local',ns=ns,timeout=20)
        if r.code: raise InfrastructureError('CoreDNS is running but the client Pod cannot resolve the Kubernetes Service: '+r.err[:250])
        stage('Waiting for K3s NetworkPolicy enforcement to start; API acceptance alone is not enough…')
        policy=obj('NetworkPolicy','deny-health',{'podSelector':{'matchLabels':{'app':'backend'}},'policyTypes':['Ingress'],'ingress':[]},api='networking.k8s.io/v1')
        policy['metadata']['namespace']=ns
        r=await startup_k(runner,'apply','-f','-',stdin=json.dumps(policy),ns=ns)
        if r.code: raise InfrastructureError('Cannot create NetworkPolicy smoke test: '+r.err[:300])
        async def blocked():
            c={**criterion,'allowed':False}
            result,_=await Grader(runner,test_task).evaluate(c)
            return result
        await wait_until(blocked,'NetworkPolicy controller did not begin enforcing the test policy. Check docker compose logs cluster; NetworkPolicy questions are not safe to grade.',timeout=300)
        # Check restoring allowed traffic too, so a generally broken network cannot pass.
        r=await startup_k(runner,'delete','networkpolicy','deny-health',ns=ns)
        if r.code: raise InfrastructureError('Could not remove the startup test policy: '+r.err[:300])
        async def open_again():
            result,_=await Grader(runner,test_task).evaluate(criterion)
            return result
        await wait_until(open_again,'Connectivity did not recover after removal of the test policy.',timeout=45)
        stage('Preparing the isolated image builder…')
        for image in (BUSYBOX,NGINX):
            existing=await runner.run(['docker','image','inspect',image,'--format','{{.Id}}'])
            if not existing.code: continue
            stage('Downloading builder image '+image+'…')
            r=await runner.run(['docker','pull',image],timeout=180)
            if r.code: raise InfrastructureError('The isolated builder could not pull '+image+'. Check docker compose logs builder and registry connectivity.')
        r=await startup_k(runner,'delete','namespace',ns,'--wait=false',timeout=25)
        if r.code: raise InfrastructureError('Could not remove the startup probes: '+r.err[:300])
        manager.environment.update(ready=True,phase='ready',message='Two-node Kubernetes lab ready. Cross-node allow/block/recovery checks passed.',
            checks={'nodes':True,'dns':True,'ingress_controller':True,'metrics_server':True,'storage':True,'network_policy_enforced':True,'image_builder':True},error=None,checked_at=time.time())
    except asyncio.CancelledError: raise
    except Exception as exc:
        blockers=manager.environment.get('blockers',[])
        detail=str(exc)
        if blockers and not isinstance(exc,StartupBlocked): detail+=' Blocked by: '+'; '.join(blockers)+'.'
        manager.environment.update(ready=False,phase='error',message='Startup stopped. Resolve the reported issue, then retry.',error=detail)

async def widget_controller(manager):
    """A deliberately minimal, real operator for the supplied Widget API."""
    from bank import BANK
    valid_ns={t['namespace'] for t in BANK.values()}
    runner=manager.runner
    while True:
        try:
            if manager.environment.get('ready'):
                r=await runner.k('get','widgets.practice.ckad.local','--all-namespaces','-o','json')
                if r.code==0:
                    for widget in json.loads(r.out).get('items',[]):
                        m=widget['metadata']; ns=m['namespace']
                        if ns not in valid_ns or m.get('deletionTimestamp'): continue
                        name='widget-'+m['name']; spec=widget['spec']
                        desired={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':ns,
                           'labels':{'ckad.flightdeck/operator':'widget'},'ownerReferences':[{'apiVersion':widget['apiVersion'],'kind':'Widget','name':m['name'],'uid':m['uid'],'controller':True,'blockOwnerDeletion':True}]},
                           'spec':{'replicas':spec['replicas'],'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':{'app':name}},'spec':{'containers':[container('web',spec['image'])]}}}}
                        await runner.k('apply','--server-side','--field-manager=ckad-widget-operator','--force-conflicts','-f','-',stdin=json.dumps(desired),ns=ns)
        except asyncio.CancelledError: raise
        except Exception:
            # A transient API error must not terminate reconciliation permanently.
            import logging
            logging.exception('Widget reconciliation iteration failed')
        await asyncio.sleep(3)
