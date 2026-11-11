"""Real process execution and live-state grading. There is no kubectl simulator."""
from __future__ import annotations
import asyncio
import base64
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import signal
import shlex
import tarfile
from typing import Any
import yaml

class InfrastructureError(RuntimeError): pass
class MissingResource(RuntimeError): pass

@dataclass
class Result:
    code: int
    out: str
    err: str

class Runner:
    def __init__(self, kubeconfig: str='/run/lab-kubeconfig', workspace: str='/workspace'):
        self.kubeconfig=kubeconfig
        self.workspace=Path(workspace).resolve()
        self.semaphore=asyncio.Semaphore(12)
    def map_path(self, path: str) -> Path:
        if not path.startswith('/workspace/') and path != '/workspace':
            raise ValueError('Expected a path inside the lab workspace')
        mapped=self.workspace / path.removeprefix('/workspace').lstrip('/')
        resolved=mapped.resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise ValueError('Path escapes the lab workspace')
        return resolved
    def map_arg(self, arg: str) -> str:
        return arg.replace('/workspace/',str(self.workspace)+'/')
    async def run(self, args: list[str], *, stdin: str | None=None, timeout: float=25, cwd: str | None=None) -> Result:
        env={**os.environ, 'KUBECONFIG':self.kubeconfig, 'LC_ALL':'C.UTF-8'}
        args=[self.map_arg(str(x)) for x in args]
        async with self.semaphore:
            try:
                process=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,cwd=cwd,start_new_session=True)
            except FileNotFoundError as exc:
                raise InfrastructureError(f'{args[0]} is not installed in the app container') from exc
            try:
                stdout,stderr=await asyncio.wait_for(process.communicate(stdin.encode() if stdin is not None else None),timeout)
            except (asyncio.TimeoutError,asyncio.CancelledError) as exc:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                await process.communicate()
                if isinstance(exc,asyncio.CancelledError): raise
                raise InfrastructureError(f'{args[0]} did not finish within its {timeout:g}-second command limit') from exc
            return Result(process.returncode,stdout.decode(errors='replace')[:2_000_000],stderr.decode(errors='replace')[:200_000])
    async def k(self,*args: str,ns: str | None=None,stdin: str | None=None,timeout: float=25) -> Result:
        request_timeout=min(max(timeout-5,15),180) if args and args[0] in ('wait','delete') else 15
        cmd=['kubectl','--kubeconfig',self.kubeconfig,'--context','ckad-lab',f'--request-timeout={request_timeout:g}s']
        if ns: cmd += ['-n',ns]
        return await self.run(cmd+list(args),stdin=stdin,timeout=timeout)

QUANTITY=re.compile(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|K|M|G|T|P|E)|([eE][+-]?\d+))?$')

def quantity(value: Any) -> Decimal:
    """Compare ordinary Kubernetes decimal/binary quantities without float rounding."""
    if isinstance(value,bool) or value is None: raise ValueError('Not a resource quantity')
    match=QUANTITY.fullmatch(str(value).strip())
    if not match: raise ValueError(f'Invalid resource quantity: {value!r}')
    number,suffix,exponent=match.groups()
    result=Decimal(number)
    if exponent: return result * (Decimal(10) ** int(exponent[1:]))
    if suffix and suffix.endswith('i'): return result * (Decimal(1024) ** ('KMGTPE'.index(suffix[0])+1))
    factors={'n':-9,'u':-6,'m':-3,'k':3,'K':3,'M':6,'G':9,'T':12,'P':15,'E':18}
    return result * (Decimal(10) ** factors.get(suffix,0))

def select(value: Any,path: list[Any]) -> Any:
    for part in path:
        if isinstance(part,dict):
            if not isinstance(value,list): return None
            matches=[]
            for item in value:
                if all(select(item,key.split('.'))==expected for key,expected in part.items()): matches.append(item)
            # Ambiguous selectors should not silently choose a convenient match.
            value=matches[0] if len(matches)==1 else None
        elif isinstance(value,dict): value=value.get(part)
        elif isinstance(value,list) and isinstance(part,int): value=value[part] if -len(value)<=part<len(value) else None
        else: return None
    return value

SET_FIELDS={'verbs','resources','apiGroups','accessModes','policyTypes','drop','add'}

def equal(actual: Any,expected: Any, field: str | None=None) -> bool:
    """Exact object equality, with order-insensitive lists of Kubernetes objects."""
    if isinstance(expected,dict):
        return isinstance(actual,dict) and set(actual)==set(expected) and all(equal(actual[k],v,k) for k,v in expected.items())
    if isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected): return False
        if field in SET_FIELDS and all(isinstance(x,str) for x in actual+expected): return sorted(actual)==sorted(expected)
        if expected and all(isinstance(x,dict) for x in expected):
            remaining=list(actual)
            for target in expected:
                index=next((i for i,item in enumerate(remaining) if equal(item,target)),None)
                if index is None: return False
                remaining.pop(index)
            return True
        return all(equal(a,b) for a,b in zip(actual,expected))
    if isinstance(expected,bool): return isinstance(actual,bool) and actual is expected
    return actual==expected and not (isinstance(actual,bool) ^ isinstance(expected,bool))

def subset(actual: Any,expected: Any, field: str | None=None) -> bool:
    if isinstance(expected,dict):
        return isinstance(actual,dict) and all(k in actual and subset(actual[k],v,k) for k,v in expected.items())
    if isinstance(expected,list):
        if not isinstance(actual,list): return False
        if not expected: return not actual
        if all(isinstance(x,dict) for x in expected):
            remaining=list(actual)
            for target in expected:
                index=next((i for i,item in enumerate(remaining) if subset(item,target)),None)
                if index is None: return False
                remaining.pop(index)
            return True
        # Command/argument order matters; don't treat every list as a set.
        return equal(actual,expected,field)
    return equal(actual,expected,field)

def compare(actual: Any,expected: Any,op: str='equals') -> bool:
    if op=='subset': return subset(actual,expected)
    if op=='named_subset':
        return isinstance(actual,list) and isinstance(expected,list) and all(
            subset(select(actual,[{'name':item['name']}]),item) for item in expected)
    if op=='equals': return equal(actual,expected)
    if op=='contains': return isinstance(actual,(str,list,dict)) and expected in actual
    if op in ('quantity','at_least_quantity'):
        try: return quantity(actual)==quantity(expected) if op=='quantity' else quantity(actual)>=quantity(expected)
        except (ValueError,InvalidOperation): return False
    if op=='one_of': return isinstance(expected,(list,tuple)) and actual in expected
    if op=='at_least': return isinstance(actual,(int,float)) and not isinstance(actual,bool) and actual>=expected
    if op=='length': return isinstance(actual,(list,dict,str)) and len(actual)==expected
    if op=='nonempty': return actual not in (None,'','None',[],{})
    if op=='echo_command': return echo_output(actual)==expected
    if op=='network_policy':
        try: return policy_permissions(actual)==policy_permissions(expected)
        except (TypeError,ValueError,KeyError): return False
    raise ValueError(f'Unknown comparison {op}')

def policy_permissions(spec: dict) -> dict:
    """Compare policy grants independently of rule grouping and selector syntax."""
    if not isinstance(spec,dict): raise ValueError('Expected a policy spec')
    def selector(value):
        expressions=[{'key':k,'operator':'In','values':[v]} for k,v in value.get('matchLabels',{}).items()]
        for term in value.get('matchExpressions',[]):
            term=deepcopy(term)
            if 'values' in term: term['values']=sorted(set(term['values']))
            expressions.append(term)
        return sorted({json.dumps(x,sort_keys=True) for x in expressions})
    result=deepcopy(spec)
    result['podSelector']=selector(spec['podSelector'])
    types=spec.get('policyTypes',['Ingress']+(['Egress'] if spec.get('egress') else []))
    result['policyTypes']=sorted(set(types))
    for direction,peer_key in (('ingress','from'),('egress','to')):
        if direction.capitalize() not in types: continue
        grants=set()
        for rule in spec.get(direction,[]):
            for peer in rule.get(peer_key) or [{}]:
                peer=deepcopy(peer)
                for key in ('podSelector','namespaceSelector'):
                    if key in peer: peer[key]=selector(peer[key])
                if 'ipBlock' in peer and 'except' in peer['ipBlock']:
                    peer['ipBlock']['except']=sorted(set(peer['ipBlock']['except']))
                for port in rule.get('ports') or [None]:
                    port=None if port is None else {'protocol':'TCP',**port}
                    grants.add(json.dumps([peer,port],sort_keys=True))
        result[direction]=sorted(grants)
    return result


def echo_output(container: Any) -> str | None:
    """Recognize a simple echo invocation without executing student shell code."""
    if not isinstance(container,dict): return None
    command=container.get('command',[]); args=container.get('args',[])
    if not isinstance(command,list) or not isinstance(args,list): return None
    argv=command+args
    if not argv or not all(isinstance(x,str) for x in argv): return None
    if argv[0] in ('sh','/bin/sh'):
        if len(argv)!=3 or argv[1]!='-c': return None
        script=argv[2].strip()
        if any(x in script for x in ('$','`','\n')): return None
        try:
            lexer=shlex.shlex(script,posix=True,punctuation_chars=True)
            lexer.whitespace_split=True; lexer.commenters=''
            argv=list(lexer)
        except ValueError: return None
        if argv and argv[-1]==';': argv.pop()
    if not argv or argv[0] not in ('echo','/bin/echo'): return None
    if any(x in (';','&&','||','|','&','>','>>','<','(',')') for x in argv[1:]): return None
    if len(argv)>1 and argv[1].startswith('-'): return None
    return ' '.join(argv[1:])


def check_value(value: Any, criterion: dict, checks: list[dict]) -> Any:
    """Inspect one consistent unnamed item across related field checks.

    The best matching item gives useful partial feedback without combining one
    container's image with another's resources. Named selectors stay strict.
    """
    if 'items_path' in criterion:
        items=select(value,criterion['items_path'])
        if not isinstance(items,list) or not items: return None
        peers=[c for c in checks if all(c.get(k)==criterion.get(k)
               for k in ('kind','resource','name','namespace','items_path'))]
        value=max(items,key=lambda item:sum(compare(select(item,c.get('path',[])),
                  c.get('expected'),c.get('op','equals')) for c in peers))
    return select(value,criterion.get('path',[]))


def is_ready(obj: dict | None) -> bool:
    if not obj: return False
    kind=obj.get('kind'); status=obj.get('status',{}); spec=obj.get('spec',{})
    if kind=='Pod':
        return status.get('phase')=='Running' and any(c.get('type')=='Ready' and c.get('status')=='True' for c in status.get('conditions',[]))
    observed=status.get('observedGeneration',0)>=obj.get('metadata',{}).get('generation',1)
    if kind=='Deployment':
        wanted=spec.get('replicas',1)
        return wanted>0 and observed and status.get('replicas',0)==wanted and status.get('updatedReplicas',0)==wanted and status.get('availableReplicas',0)>=wanted
    if kind=='DaemonSet':
        wanted=status.get('desiredNumberScheduled',0)
        return wanted>0 and observed and status.get('numberReady',0)==wanted and status.get('updatedNumberScheduled',0)==wanted
    if kind=='StatefulSet':
        wanted=spec.get('replicas',1)
        return wanted>0 and observed and status.get('readyReplicas',0)==wanted and status.get('updatedReplicas',0)==wanted
    return False

CLUSTER_SCOPED={'namespace','namespaces','ns','customresourcedefinition','crd','storageclass','sc','node','nodes','persistentvolume','pv','clusterrole','clusterrolebinding'}

class Grader:
    def __init__(self, runner: Runner, task: dict):
        self.runner=runner; self.task=task; self.ns=task['namespace']; self.cache={}
    async def get(self, resource: str, name: str, ns: str | None=None) -> dict | None:
        ns=None if resource.lower() in CLUSTER_SCOPED else (ns or self.ns)
        key=(resource,name,ns)
        if key not in self.cache:
            async def fetch():
                r=await self.runner.k('get',resource,name,'-o','json',ns=ns)
                if r.code:
                    if '(NotFound)' in r.err or ' not found' in r.err: return None
                    raise InfrastructureError(r.err.strip()[:500] or f'Cannot read {resource}/{name}')
                try:
                    value=json.loads(r.out)
                    # The API omits empty ingress/egress slices. For an isolated
                    # direction, omission and [] both mean no allowed peers.
                    if value.get('kind')=='NetworkPolicy':
                        spec=value.setdefault('spec',{})
                        for direction in spec.get('policyTypes',[]):
                            spec.setdefault(direction.lower(),[])
                    return value
                except json.JSONDecodeError as exc: raise InfrastructureError('kubectl returned invalid JSON') from exc
            self.cache[key]=asyncio.create_task(fetch())
        return await self.cache[key]
    async def pod_exec(self,name,command,ns=None,container=None,timeout=15):
        args=['exec',name]
        if container: args += ['-c',container]
        return await self.runner.k(*args,'--',*command,ns=ns or self.ns,timeout=timeout)
    async def evaluate(self,c: dict) -> tuple[bool,str]:
        kind=c['kind']; expected=c.get('expected'); op=c.get('op','equals')
        if kind=='resource':
            value=await self.get(c['resource'],c['name'],c.get('namespace'))
            if value is None: return False,f"{c['resource']}/{c['name']} does not exist in the required scope."
            actual=check_value(value,c,self.task.get('selection_checks',self.task['checks'])); passed=compare(actual,expected,op)
            # Deliberately avoid printing Secret data or environment values into reports.
            return passed,'Required live fields match.' if passed else 'One or more required live fields do not match. Inspect the object with kubectl get -o yaml.'
        if kind=='inventory':
            r=await self.runner.k('get',c['resource'],'-o','json',ns=self.ns)
            if r.code: raise InfrastructureError('Could not inspect the required namespace resource inventory.')
            names={item.get('metadata',{}).get('name') for item in json.loads(r.out).get('items',[])}
            passed=names==set(c['names'])
            return passed,'The namespace contains exactly the required resource names.' if passed else 'The namespace has missing or extra resources of this type. Preserve the supplied inventory.'
        if kind=='rollout_history':
            value=await self.get('deployment',c['name'])
            if not value: return False,'The requested Deployment is missing.'
            meta=value.get('metadata',{})
            try: revision=int(meta.get('annotations',{}).get('deployment.kubernetes.io/revision','0'))
            except (ValueError,TypeError): revision=0
            r=await self.runner.k('get','replicasets','-o','json',ns=self.ns)
            if r.code: raise InfrastructureError('Could not inspect Deployment revision history.')
            images=set()
            for rs in json.loads(r.out).get('items',[]):
                if not any(ref.get('uid')==meta.get('uid') and ref.get('controller') is True for ref in rs.get('metadata',{}).get('ownerReferences',[])): continue
                for item in rs.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[]):
                    if item.get('name')==c['container']: images.add(item.get('image'))
            passed=revision>=c['min_revision'] and set(c['images']).issubset(images)
            return passed,'Owned history contains both image versions and a later revision.' if passed else 'Update/rollback history is incomplete. Keep the Deployment and inspect its owned ReplicaSets.'
        if kind=='rbac_rules':
            value=await self.get('role',c['name'])
            if value is None: return False,'The requested Role does not exist.'
            def permissions(rules):
                result=set()
                for rule in rules:
                    if rule.get('resourceNames') or rule.get('nonResourceURLs'):
                        return None
                    for group in rule.get('apiGroups',[]):
                        for res in rule.get('resources',[]):
                            for verb in rule.get('verbs',[]): result.add((group,res,verb))
                return result
            return permissions(value.get('rules',[]))==permissions(c['rules']),'Compared effective Role grants independently of rule grouping and verb order.'
        if kind=='ready':
            value=await self.get(c['resource'],c['name']); passed=is_ready(value)
            return passed,'Workload is Ready / fully rolled out.' if passed else 'Workload is missing, still converging, or unhealthy. Check Pods, events, and rollout status.'
        if kind=='job_complete':
            value=await self.get('job',c['name']); status=(value or {}).get('status',{})
            passed=status.get('succeeded',0)>=c['completions'] and any(x.get('type')=='Complete' and x.get('status')=='True' for x in status.get('conditions',[]))
            return passed,'Required successful executions completed.' if passed else 'The Job has not reached the required successful completion state.'
        if kind=='exec':
            if not is_ready(await self.get('pod',c['pod'])): return False,'The target Pod must be Ready before its runtime output can be checked.'
            r=await self.pod_exec(c['pod'],c['command'],container=c.get('container'))
            passed=r.code==0 and compare(r.out.strip(),str(expected).strip(),op)
            return passed,'Runtime check passed.' if passed else 'The container command failed or its output did not match the task.'
        if kind=='logs':
            args=['logs',c['resource'],'--tail=100','--limit-bytes=16384']
            if c.get('container'): args+=['-c',c['container']]
            r=await self.runner.k(*args,ns=self.ns)
            return r.code==0 and compare(r.out.strip(),expected,op),'Checked the named workload/container logs.'
        if kind=='file':
            path=self.runner.map_path(c['path'])
            if not path.is_file(): return False,'Required workspace file does not exist.'
            if path.stat().st_size>2_000_000: return False,'Answer file is unexpectedly large.'
            content=path.read_text(errors='replace').strip()
            return compare(content,str(expected).strip(),op),'Checked the saved workspace file.'
        if kind in ('yaml_file','render'):
            if kind=='render':
                path=self.runner.map_path(c['path'])
                r=await self.runner.run(['kubectl','kustomize',str(path)])
                if r.code: return False,'The saved Kustomize overlay does not build: '+r.err[:250]
                text=r.out
            else:
                path=self.runner.map_path(c['path'])
                if not path.is_file(): return False,'Required YAML file is missing.'
                if path.stat().st_size>2_000_000: return False,'YAML answer is unexpectedly large.'
                text=path.read_text()
            try: actual=[x for x in yaml.safe_load_all(text) if isinstance(x,dict)]
            except yaml.YAMLError: return False,'The saved YAML cannot be parsed.'
            expected=deepcopy(expected)
            if c.get('allowed_path_types'):
                target=expected[0]['metadata']['name']
                ingress=next((x for x in actual if x.get('kind')=='Ingress' and x.get('metadata',{}).get('name')==target),None)
                paths=[path for rule in (ingress or {}).get('spec',{}).get('rules',[]) for path in rule.get('http',{}).get('paths',[])]
                if not paths or any(path.get('pathType') not in c['allowed_path_types'] for path in paths):
                    return False,'The saved Ingress file needs a supported pathType for each path.'
            if c.get('ignore_namespace'):
                for target in expected:
                    matches=[x for x in actual if x.get('kind')==target.get('kind') and x.get('metadata',{}).get('name')==target['metadata']['name']]
                    if len(matches)==1 and 'namespace' not in matches[0].get('metadata',{}): target['metadata'].pop('namespace',None)
            return subset(actual,expected),'Checked the saved/rendered resource definitions, not only the live objects.'
        if kind=='endpoints':
            r=await self.runner.k('get','endpointslices','-l',f'kubernetes.io/service-name={c["name"]}','-o','json',ns=self.ns)
            if r.code: raise InfrastructureError(r.err[:300])
            items=json.loads(r.out).get('items',[]); endpoints=set()
            for item in items:
                for endpoint in item.get('endpoints') or []:
                    if endpoint.get('conditions',{}).get('ready') is True:
                        ref=endpoint.get('targetRef',{})
                        endpoints.add(ref.get('uid') or tuple(endpoint.get('addresses',[])))
            return len(endpoints)==c['count'],f'Observed {len(endpoints)} distinct ready backends; required {c["count"]}.'
        if kind=='http':
            if not is_ready(await self.get('pod',c['source'])): return False,'The client Pod is not Ready; an HTTP result cannot yet be assessed.'
            r=await self.pod_exec(c['source'],['wget','-q','-T','5','-O-',c['url']])
            return r.code==0 and compare(r.out.strip(),expected,op),'Made a real HTTP request from the provided client Pod.'
        if kind=='http_endpoints':
            source_kind,source_name=c['source'].split('/',1)
            if not is_ready(await self.get(source_kind,source_name)): return False,'The source workload must be Ready.'
            r=await self.runner.k('get','endpointslices','-l',f'kubernetes.io/service-name={c["name"]}','-o','json',ns=self.ns)
            if r.code: raise InfrastructureError('Could not inspect Service backends.')
            addresses={address for item in json.loads(r.out).get('items',[])
                       for endpoint in item.get('endpoints') or [] if endpoint.get('conditions',{}).get('ready') is True
                       for address in endpoint.get('addresses',[])}
            if len(addresses)!=c['count']: return False,'The Service does not have the required ready backends.'
            for address in addresses:
                host='['+address+']' if ':' in address else address
                r=await self.pod_exec(c['source'],['wget','-q','-T','3','-O','/dev/null',f'http://{host}:{c["port"]}/'])
                if r.code: return False,'A selected backend does not serve HTTP on the required port.'
            return True,'Every selected stable and canary backend serves HTTP.'
        if kind=='http_nodeport':
            service=await self.get('service',c['service'])
            ports=(service or {}).get('spec',{}).get('ports',[])
            port=next((p.get('nodePort') for p in ports if p.get('port')==80 and p.get('protocol')=='TCP'),None)
            if (service or {}).get('spec',{}).get('type')!='NodePort' or not isinstance(port,int) or not 1<=port<=65535:
                return False,'The Service has no assigned NodePort for its TCP port 80.'
            return await self.evaluate({**c,'kind':'http_external','url':f'http://{c["host"]}:{port}'})
        if kind=='http_external':
            cmd=['curl','--noproxy','*','-fsSL','--connect-timeout','3','--max-time','10']
            if c.get('host'): cmd+=['-H','Host: '+c['host']]
            r=await self.runner.run(cmd+[c['url']],timeout=15)
            return r.code==0 and compare(r.out.strip(),expected,op),'Made a real HTTP request to the lab node / Ingress controller.'
        if kind=='traffic':
            source_ns=c.get('source_namespace') or self.ns
            source=await self.get('pod',c['source'],source_ns); target=await self.get('pod',c['target'])
            if not is_ready(source) or not is_ready(target): return False,'Both fixture Pods must be Ready. A dead client/server is not counted as a successful block.'
            ip=target.get('status',{}).get('podIP')
            if not ip: return False,'Backend Pod has no IP address yet.'
            local=await self.pod_exec(c['target'],['wget','-q','-T','3','-O-',f'http://127.0.0.1:{c["port"]}'])
            if local.code!=0: return False,'Backend does not serve HTTP locally. This failure is not counted as network isolation.'
            script='command -v wget >/dev/null || exit 125; if wget -q -T 3 -O /dev/null "$1"; then printf OPEN; else printf BLOCKED; fi'
            r=await self.pod_exec(c['source'],['sh','-c',script,'probe',f'http://{ip}:{c["port"]}'],ns=source_ns)
            if r.code or r.out not in ('OPEN','BLOCKED'): return False,'Traffic probe could not execute reliably.'
            wanted='OPEN' if c['allowed'] else 'BLOCKED'
            return r.out==wanted,f'Traffic is {r.out.lower()}; backend health was verified independently.'
        if kind=='auth':
            ns=c.get('target_namespace') or self.ns
            res=c['resource']; args=['auth','can-i',c['verb'],res.split('/')[0],f'--as=system:serviceaccount:{self.ns}:{c["sa"]}']
            if '/' in res: args+=['--subresource='+res.split('/',1)[1]]
            r=await self.runner.k(*args,ns=ns)
            answer=r.out.strip()
            if answer not in ('yes','no'): raise InfrastructureError('RBAC authorization could not be evaluated: '+r.err[:200])
            return (answer=='yes')==c['allowed'],f'Live authorization returned {answer}.'
        if kind=='admission_denied':
            doc={'apiVersion':'v1','kind':'Pod','metadata':{'name':'admission-check','namespace':self.ns},'spec':{'containers':[{'name':'probe','image':'busybox:1.37.0','command':['sleep','60'],'securityContext':{'privileged':True}}]}}
            r=await self.runner.k('create','--dry-run=server','-f','-',stdin=json.dumps(doc),ns=self.ns)
            passed=r.code!=0 and 'violates PodSecurity' in r.err
            return passed,'Server-side dry-run verified Pod Security rejection.' if passed else 'The API did not specifically reject this Pod for violating Pod Security.'
        if kind=='helm':
            r=await self.runner.run(['helm','status',c['release'],'-n',self.ns,'-o','json'])
            if r.code: return False,'The named Helm release could not be found/read.'
            info=json.loads(r.out)
            if info.get('info',{}).get('status')!='deployed': return False,'Helm release is not in deployed status.'
            if int(info.get('version',0))<c.get('min_revision',1): return False,'The required Helm revision change has not occurred.'
            r=await self.runner.run(['helm','get','values',c['release'],'-n',self.ns,'--all','-o','json'])
            return r.code==0 and subset(json.loads(r.out or '{}'),c['values']),'Checked release status, revision, and effective Helm values.'
        if kind=='metrics_file':
            path=self.runner.map_path(c['path'])
            if not path.is_file() or path.stat().st_size>100_000: return False,'A small saved metrics file is required.'
            def parse(text):
                rows={}
                for line in text.strip().splitlines():
                    fields=line.split()
                    if len(fields)!=3 or fields[0] in rows: raise ValueError('Invalid or duplicate metrics row')
                    if quantity(fields[1])<0 or quantity(fields[2])<0: raise ValueError('Negative metric')
                    rows[fields[0]]=fields[1:]
                return rows
            try: saved=parse(path.read_text())
            except (ValueError,InvalidOperation): return False,'Expected exactly Pod-name, CPU, and memory columns without a header.'
            if set(saved)!=set(c['pods']): return False,'Saved metrics do not contain exactly the requested Pods.'
            r=await self.runner.k('top','pods','-l','metrics-task=true','--no-headers',ns=self.ns)
            if r.code: raise InfrastructureError('Live Pod metrics are not available yet. Retry after metrics-server has sampled the workloads.')
            try: live=parse(r.out)
            except ValueError: raise InfrastructureError('Unexpected live metrics output')
            return set(c['pods']).issubset(live),'Saved rows are valid and live metrics are available; point-in-time values are not compared across changing samples.'
        if kind in ('image','image_same','image_base'):
            async def inspect(name):
                r=await self.runner.run(['docker','image','inspect',name])
                if r.code:
                    if 'No such image' in r.err or 'No such object' in r.err: return None
                    raise InfrastructureError('Docker builder could not inspect an image: '+r.err[:200])
                return json.loads(r.out)[0]
            value=await inspect(c['image'])
            if not value: return False,'The requested built/tagged image does not exist.'
            if kind=='image_base':
                base=await inspect(c['base'])
                if not base: raise InfrastructureError('The provided base image is missing from the builder.')
                layers=base.get('RootFS',{}).get('Layers',[]); actual_layers=value.get('RootFS',{}).get('Layers',[])
                return bool(layers) and actual_layers[:len(layers)]==layers,'Compared the actual base image filesystem layers with the built image ancestry.'
            if kind=='image_same':
                other=await inspect(c['other'])
                return bool(other) and value['Id']==other['Id'],'Compared the actual image IDs behind both tags.'
            return compare(select(value,c['path']),expected,op),'Inspected metadata on the built image.'
        if kind=='image_file':
            r=await self.runner.run(['docker','run','--rm','--network','none','--entrypoint','cat',c['image'],c['file']],timeout=40)
            return r.code==0 and compare(r.out.strip(),expected,op),'Read the page from a real container created from the built image.'
        if kind=='image_archive':
            path=self.runner.map_path(c['path'])
            if not path.is_file(): return False,'The image archive is missing.'
            if path.stat().st_size>2_000_000_000: return False,'The supplied lab image archive is unexpectedly large.'
            try:
                with tarfile.open(path,'r:*') as archive:
                    member=archive.getmember('manifest.json')
                    if not member.isfile() or member.size>1_000_000: return False,'Invalid image manifest.'
                    manifest=json.load(archive.extractfile(member))
                    entry=next((x for x in manifest if c['tag'] in x.get('RepoTags',[])),None)
                    if not entry or not entry.get('Layers'): return False,'Image archive lacks the required tag or layer list.'
                    config_member=archive.getmember(entry['Config'])
                    if not config_member.isfile() or config_member.size>1_000_000: return False,'Invalid image configuration.'
                    import hashlib
                    config_bytes=archive.extractfile(config_member).read()
                    json.loads(config_bytes)
                    for layer in entry['Layers']:
                        if not archive.getmember(layer).isfile(): return False,'Archive layer is missing.'
                    saved_id='sha256:'+hashlib.sha256(config_bytes).hexdigest()
                r=await self.runner.run(['docker','image','inspect',c['tag'],'--format','{{.Id}}'])
                return r.code==0 and r.out.strip()==saved_id,'Validated the docker-save manifest, layer members, tag, and saved image identity without extracting the archive.'
            except (tarfile.TarError,KeyError,ValueError,TypeError,json.JSONDecodeError):
                return False,'File is not a valid docker-save archive for the requested image.'
        raise ValueError(f'Unsupported criterion kind {kind}')

    async def grade(self) -> dict:
        semaphore=asyncio.Semaphore(4)
        async def one(c):
            async with semaphore:
                try:
                    passed,detail=await self.evaluate(c)
                    return {'label':c['label'],'status':'pass' if passed else 'fail','detail':detail}
                except InfrastructureError as exc:
                    return {'label':c['label'],'status':'error','detail':str(exc)}
                except Exception as exc:
                    # Explicit error, never a false success or silent skipped criterion.
                    return {'label':c['label'],'status':'error','detail':f'Grader error ({type(exc).__name__}): {str(exc)[:250]}'}
        results=await asyncio.gather(*(one(c) for c in self.task['checks']))
        earned=sum(c['status']=='pass' for c in results); errors=sum(c['status']=='error' for c in results)
        return {'task_id':self.task['id'],'earned':earned,'possible':len(results),'percent':round(100*earned/len(results),1),
                'complete':earned==len(results),'has_errors':bool(errors),'criteria':results}
