"""Small, explicit building blocks for the original CKAD practice tasks."""
from copy import deepcopy
import json
import re
import textwrap
import yaml

NGINX = 'nginx:1.27.5-alpine'
NGINX_NEW = 'nginx:1.28.0-alpine'
BUSYBOX = 'busybox:1.37.0'
DOMAINS = {
 'design': {'name': 'Application Design and Build', 'weight': 20, 'short': 'Design & build'},
 'deployment': {'name': 'Application Deployment', 'weight': 20, 'short': 'Deployment'},
 'observability': {'name': 'Application Observability and Maintenance', 'weight': 15, 'short': 'Observability'},
 'configuration': {'name': 'Application Environment, Configuration and Security', 'weight': 25, 'short': 'Configuration & security'},
 'networking': {'name': 'Services and Networking', 'weight': 20, 'short': 'Services & networking'},
}
DOCS = {
 'pod': 'https://kubernetes.io/docs/concepts/workloads/pods/',
 'init': 'https://kubernetes.io/docs/concepts/workloads/pods/init-containers/',
 'sidecar': 'https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/',
 'volume': 'https://kubernetes.io/docs/concepts/storage/volumes/',
 'pvc': 'https://kubernetes.io/docs/concepts/storage/persistent-volumes/',
 'job': 'https://kubernetes.io/docs/concepts/workloads/controllers/job/',
 'cronjob': 'https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/',
 'daemonset': 'https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/',
 'statefulset': 'https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/',
 'deployment': 'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/',
 'helm': 'https://helm.sh/docs/intro/using_helm/',
 'kustomize': 'https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/',
 'hpa': 'https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/',
 'probes': 'https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/',
 'debug': 'https://kubernetes.io/docs/tasks/debug/debug-application/',
 'logs': 'https://kubernetes.io/docs/reference/kubectl/generated/kubectl_logs/',
 'top': 'https://kubernetes.io/docs/reference/kubectl/generated/kubectl_top/',
 'deprecation': 'https://kubernetes.io/docs/reference/using-api/deprecation-guide/',
 'configmap': 'https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/',
 'secret': 'https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/',
 'sa': 'https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/',
 'rbac': 'https://kubernetes.io/docs/reference/access-authn-authz/rbac/',
 'resources': 'https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/',
 'quota': 'https://kubernetes.io/docs/concepts/policy/resource-quotas/',
 'limitrange': 'https://kubernetes.io/docs/concepts/policy/limit-range/',
 'security': 'https://kubernetes.io/docs/tasks/configure-pod-container/security-context/',
 'admission': 'https://kubernetes.io/docs/concepts/security/pod-security-admission/',
 'crd': 'https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/',
 'operator': 'https://kubernetes.io/docs/concepts/extend-kubernetes/operator/',
 'downward': 'https://kubernetes.io/docs/tasks/inject-data-application/downward-api-volume-expose-pod-information/',
 'service': 'https://kubernetes.io/docs/concepts/services-networking/service/',
 'ingress': 'https://kubernetes.io/docs/concepts/services-networking/ingress/',
 'networkpolicy': 'https://kubernetes.io/docs/concepts/services-networking/network-policies/',
 'docker': 'https://docs.docker.com/build/concepts/dockerfile/',
 'save': 'https://docs.docker.com/reference/cli/docker/image/save/',
}

def obj(kind, name, spec=None, api='v1', labels=None, **other):
    value = {'apiVersion': api, 'kind': kind, 'metadata': {'name': name}}
    if labels is not None: value['metadata']['labels'] = labels
    if spec is not None: value['spec'] = spec
    value.update(other)
    return value

def container(name='web', image=NGINX, command=None, **kw):
    value = {'name': name, 'image': image}
    if command is not None: value['command'] = command
    value.update(kw)
    return value

def pod(name, containers=None, labels=None, **spec):
    return obj('Pod', name, {'containers': containers or [container()], **spec}, labels=labels)

def sleeper(name, labels=None):
    return pod(name, [container('client', BUSYBOX, ['sh','-c','sleep 86400'])], labels=labels)

def deployment(name, replicas=2, image=NGINX, labels=None, containers=None, **pspec):
    labels = labels or {'app': name}
    return obj('Deployment', name, {
        'replicas': replicas, 'selector': {'matchLabels': labels},
        'template': {'metadata': {'labels': deepcopy(labels)},
                     'spec': {'containers': containers or [container('web',image)], **pspec}}
    }, api='apps/v1')

def service(name, selector, port=80, target=80, **spec):
    return obj('Service', name, {'type':'ClusterIP','selector':selector,
        'ports':[{'port':port,'targetPort':target,'protocol':'TCP'}], **spec})

def http_container(body='CKAD OK', port=8080, name='web', subdir=''):
    dest = '/www' + ('/'+subdir if subdir else '')
    # All arguments originate in this maintained bank, not in HTTP input.
    return container(name, BUSYBOX, ['sh','-c',
        f"mkdir -p {dest}; printf '%s\\n' '{body}' > {dest}/index.html; exec httpd -f -p {port} -h /www"],
        ports=[{'name':'http','containerPort':port}])

def http_pod(name, labels=None, body='CKAD OK', port=8080):
    return pod(name,[http_container(body,port)],labels=labels or {'app':name})

def http_deployment(name, replicas=2, labels=None, body='CKAD OK', subdir=''):
    return deployment(name,replicas,labels=labels,containers=[http_container(body,subdir=subdir)])

def probe(port=80, path='/', **kw):
    return {'httpGet':{'path':path,'port':port}, **kw}

def check(label, kind, **kw): return {'label':label,'kind':kind, **kw}
def resource(label, res, name, expected, path=None, op='subset', namespace=None, items_path=None):
    c = check(label,'resource',resource=res,name=name,path=path or [],op=op,expected=expected)
    if namespace: c['namespace']=namespace
    if items_path is not None: c['items_path']=items_path
    return c

def ready(res,name,label=None):
    return check(label or f'{res}/{name} is healthy','ready',resource=res,name=name)

def exec_check(label,podname,command,expected='',container_name=None,op='equals'):
    return check(label,'exec',pod=podname,command=command,expected=expected,container=container_name,op=op)

def filecheck(label,path,expected,op='equals'):
    return check(label,'file',path=path,expected=expected,op=op)

def quantity(label,res,name,path,expected):
    return resource(label,res,name,expected,path,'quantity')

def traffic(label,source,target,allowed=True,source_ns=None,port=8080):
    return check(label,'traffic',source=source,target=target,allowed=allowed,source_namespace=source_ns,port=port)

def scoped(objects, ns):
    objects = deepcopy(objects)
    for o in objects:
        if o['kind'] not in ['Namespace','CustomResourceDefinition','ClusterRole','ClusterRoleBinding','PersistentVolume','StorageClass']:
            o.setdefault('metadata',{}).setdefault('namespace',ns)
    return objects

def apply_script(objects, ns, filename='solution.yaml'):
    if not objects: return ''
    return f"cat > {filename} <<'YAML'\n" + yaml.safe_dump_all(scoped(objects,ns),sort_keys=False) + f"YAML\nkubectl apply -f {filename}\n"

def namespace_script(script, ns):
    def qualify(match):
        prefix, tool, args = match.groups()
        options = args.split(' -- ', 1)[0]
        if (tool == 'kubectl' and args.startswith('kustomize ')) or re.search(r'(^|\s)(-n|--namespace)([ =]|$)', options):
            return match.group()
        return f'{prefix}{tool} -n {ns} {args}'

    lines, heredoc = [], None
    for line in script.splitlines(keepends=True):
        if heredoc:
            if line.strip() == heredoc: heredoc = None
            lines.append(line)
            continue
        marker = re.search(r"<<\s*['\"]?(\w+)['\"]?", line)
        if marker: heredoc = marker[1]
        lines.append(re.sub(r'(^[ \t]*|\$\()(kubectl|helm) (.*)', qualify, line))
    return ''.join(lines)


def task(tid,title,domain,requirements,*,level='Intermediate',minutes=7,seeds=None,final=None,checks=None,
         files=None,setup=None,solution=None,after=None,hints=None,explanation='',docs=None,extra_namespaces=None):
    ns = 'ckad-'+tid
    path = '/workspace/'+tid
    final = final or []
    solution = solution if solution is not None else apply_script(final, ns, path+'/solution.yaml')
    return dict(id=tid,title=title,domain=domain,level=level,minutes=minutes,namespace=ns,context='ckad-lab',
        requirements=requirements,seeds=scoped(seeds or [],ns),checks=checks or [],files=files or {},
        setup=setup or [],solution=namespace_script(solution+(after or ''),ns),final=scoped(final,ns),
        hints=hints or ['Inspect the existing objects before editing. Use kubectl explain to locate unfamiliar fields.',
                          'Use kubectl get -o yaml, apply your changes, then verify the resulting workload.'],
        explanation=explanation,docs=[{'label':k.replace('_',' ').title(),'url':DOCS[k]} for k in (docs or ['pod'])],
        extra_namespaces=extra_namespaces or [],workspace=path)

C = lambda name='web': ['spec','containers',{'name':name}]
D = lambda name='web': ['spec','template','spec','containers',{'name':name}]
