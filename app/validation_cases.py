"""Deliberately wrong answers used only by the explicitly destructive self-test."""
import json
from copy import deepcopy


async def alternative_answers(runner, task):
    """Apply independently expressed valid answers; yield labels for live grading."""
    tid=task['id']; ns=task['namespace']
    async def apply(kind,name,patch):
        result=await runner.k('patch',kind,name,'--type=merge','-p',json.dumps(patch),ns=ns)
        if result.code: raise RuntimeError('Alternative-answer mutation failed: '+result.err[:300])
    if tid=='s16':
        for name,cpu,memory,request_cpu,request_memory in (
                ('resource-pod','1','2Gi','100m','128Mi'),
                ('student-choice','1000m','2048Mi','200m','256Mi')):
            result=await runner.k('delete','pod','resource-pod','--wait=true','--timeout=60s',ns=ns,timeout=70)
            if result.code: raise RuntimeError(result.err[:300])
            pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':'resource-pod','namespace':ns},
                 'spec':{'containers':[{'name':name,'image':'nginx:latest','resources':{
                     'limits':{'cpu':cpu,'memory':memory},'requests':{'cpu':request_cpu,'memory':request_memory}}}]}}
            result=await runner.k('apply','-f','-',stdin=json.dumps(pod),ns=ns)
            if result.code: raise RuntimeError(result.err[:300])
            yield 'container '+name+' with equivalent quantities'
    elif tid=='s02':
        variants=[(['sh','-c','echo Backup completed'],[]),(['echo'],['Backup','completed'])]
        for index,(command,args) in enumerate(variants):
            await apply('cronjob','backup-job',{'spec':{'jobTemplate':{'spec':{'template':{'spec':{
                'containers':[{'name':'backup','image':'busybox:latest','command':command,'args':args}]}}}}}})
            name='acceptance-backup-'+str(index)
            for command_args in (('create','job',name,'--from=cronjob/backup-job'),
                                 ('wait','--for=condition=complete','job/'+name,'--timeout=90s')):
                result=await runner.k(*command_args,ns=ns,timeout=100)
                if result.code: raise RuntimeError(result.err[:300])
            result=await runner.k('logs','job/'+name,ns=ns)
            if result.code or result.out.strip()!='Backup completed': raise RuntimeError('Alternative backup Job produced incorrect output.')
            yield 'backup command layout '+str(index+1)+' executed successfully'
    elif tid=='s01':
        result=await runner.k('set','env','deployment/api-server','UNRELATED=preserved',ns=ns)
        if result.code: raise RuntimeError(result.err[:300])
        yield 'additional unrelated environment variable'
    elif tid=='s11':
        result=await runner.k('patch','deployment','secure-app','--type=json','-p',json.dumps([
            {'op':'add','path':'/spec/template/spec/containers/0/securityContext/capabilities/add/-','value':'NET_BIND_SERVICE'}]),ns=ns)
        if result.code: raise RuntimeError(result.err[:300])
        yield 'additional container capability'
    elif tid in ('n08','n09','n10'):
        for c in task['checks']:
            if c.get('op')!='network_policy': continue
            policy=deepcopy(c['expected'])
            selector=policy.get('podSelector',{})
            labels=selector.pop('matchLabels',{})
            if labels: selector['matchExpressions']=[{'key':key,'operator':'In','values':[value]} for key,value in labels.items()]
            if tid=='n10':
                rules=[]
                for rule in policy['egress']:
                    rules.extend([{**rule,'ports':[port]} for port in rule['ports']])
                policy['egress']=rules
            # Replace the entire spec so merge semantics do not retain old selectors.
            result=await runner.k('patch','networkpolicy',c['name'],'--type=json','-p',
                json.dumps([{'op':'replace','path':'/spec','value':policy}]),ns=ns)
            if result.code: raise RuntimeError(result.err[:300])
        yield 'equivalent policy selectors and split port rules'


async def invalidate_answer(runner, task):
    tid=task['id']; ns=task['namespace']
    files={'p09':('overlays/prod/kustomization.yaml','resources: []\n'),
           'o03':('errors.txt','INFO not-an-error\n'),
           'o06':('usage.txt','wrong-pod 1m 1Mi\n'),
           's05':('my-app.tar','not an image archive\n'),
           's08':('broken-deploy.yaml','apiVersion: extensions/v1beta1\nkind: Deployment\n'),
           's15':('fix-ingress.yaml','apiVersion: v1\nkind: Service\n')}
    if tid in files:
        name,text=files[tid]
        runner.map_path(task['workspace']+'/'+name).write_text(text)
        return
    # Each mutation changes a stated requirement while leaving enough of the
    # answer present to distinguish rejection from an infrastructure error.
    patches={
        'p01':('deployment','api',{'spec':{'replicas':2}}),
        'p06':('deployment','notes-web',{'spec':{'replicas':1}}),
        'p10':('hpa','autoscale',{'spec':{'maxReplicas':6}}),
        'c01':('configmap','app-settings',{'data':{'APP_ENV':'incorrect'}}),
        'c04':('secret','db-auth',{'data':{'password':'aW5jb3JyZWN0'}}),
        'c06':('role','pod-reader',{'rules':[{'apiGroups':[''],'resources':['*'],'verbs':['*']}]}),
        'c11':('widgets.practice.ckad.local','gallery',{'spec':{'replicas':1}}),
        'n01':('service','web',{'spec':{'selector':{'app':'incorrect'}}}),
        's01':('secret','db-credentials',{'data':{'DB_USER':'aW5jb3JyZWN0'}}),
        's02':('cronjob','backup-job',{'spec':{'schedule':'*/10 * * * *'}}),
        's03':('role','log-role',{'rules':[{'apiGroups':[''],'resources':['*'],'verbs':['*']}]}),
        's06':('deployment','web-app-canary',{'spec':{'template':{'spec':{'containers':[
            {'name':'canary','image':'busybox:1.37.0','command':['sh','-c','sleep 86400']}]}}}}),
        's12':('service','web-svc',{'spec':{'selector':{'app':'incorrect'}}}),
        's13':('service','api-nodeport',{'spec':{'ports':[{'port':80,'targetPort':9999}]}}),
        's14':('ingress','web-ingress',{'spec':{'rules':[{'host':'incorrect.example.com','http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':'web-svc','port':{'number':8080}}}}]}}]}}),
    }
    if tid in patches:
        kind,name,patch=patches[tid]
        result=await runner.k('patch',kind,name,'--type=merge','-p',json.dumps(patch),ns=ns)
    elif tid in ('n08','n09','n10'):
        direction='Egress' if tid=='n10' else 'Ingress'
        policy={'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy',
                'metadata':{'name':'selftest-bypass','namespace':ns},
                'spec':{'podSelector':{},'policyTypes':[direction],direction.lower():[{}]}}
        result=await runner.k('apply','-f','-',stdin=json.dumps(policy),ns=ns)
    elif tid in ('o01','s10','s11'):
        name,path={'o01':('healthy','readinessProbe'),
                   's10':('api-deploy','readinessProbe'),
                   's11':('secure-app','securityContext/capabilities/add')}[tid]
        patch=[{'op':'remove','path':'/spec/template/spec/containers/0/'+path}]
        result=await runner.k('patch','deployment',name,'--type=json','-p',json.dumps(patch),ns=ns)
    elif tid in ('d01','s07'):
        name,label=('catalog','tier=incorrect') if tid=='d01' else ('backend','role=incorrect')
        result=await runner.k('label','pod',name,label,'--overwrite',ns=ns)
    elif tid=='s09':
        result=await runner.k('set','image','deployment/app-v1','web=nginx:1.25',ns=ns)
    elif tid=='s16':
        result=await runner.k('set','image','pod/resource-pod','*=busybox:1.37.0',ns=ns)
    elif tid=='d02':
        result=await runner.k('exec','landing','-c','web','--','sh','-c',
                              'printf incorrect > /usr/share/nginx/html/index.html',ns=ns)
    elif tid in ('d03','d06','c09','s04'):
        name={'d03':'audit','d06':'archive','c09':'hardened','s04':'metrics-pod'}[tid]
        result=await runner.k('delete','pod',name,'--wait=true','--timeout=60s',ns=ns,timeout=70)
    else:
        raise ValueError('No negative acceptance case for '+tid)
    if result.code: raise RuntimeError('Negative-test mutation failed: '+result.err[:300])
    if tid=='s06':
        result=await runner.k('rollout','status','deployment/web-app-canary','--timeout=180s',ns=ns,timeout=190)
        if result.code: raise RuntimeError('Non-serving canary did not become Ready: '+result.err[:300])
