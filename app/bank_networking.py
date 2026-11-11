from bank_helpers import *

def policy(name,spec): return obj('NetworkPolicy',name,spec,api='networking.k8s.io/v1')

def task_fixture_checks(seeds):
    """Protect the traffic fixtures from accidental 'fixes' that bypass the task."""
    result=[]
    for p in seeds:
        if p['kind']=='Pod':
            c=resource(f"Fixture Pod {p['metadata']['name']} keeps its labels and workload",'pod',p['metadata']['name'],
                 {'metadata':{'labels':p['metadata'].get('labels',{})},'spec':p['spec']},namespace=p['metadata'].get('namespace'))
            result.append(c)
    return result

def tasks():
    out=[]
    dep=http_deployment('web',2,body='CLUSTERIP OK')
    svc=service('web',{'app':'web'},80,8080)
    out.append(task('n01','Expose an application with ClusterIP','networking',[
      'Deployment `web` runs two Pods listening on container port `8080`, with Pod label `app=web`.',
      'Create Service `web` of type `ClusterIP`, selecting `app=web`, with TCP Service port `80` and target port `8080`.',
      'Keep the Deployment unchanged. From Pod `client`, verify that `http://web` returns CLUSTERIP OK.'
    ],minutes=5,seeds=[dep,sleeper('client')],final=[svc],checks=[resource('Explicit ClusterIP Service and correct ports','service','web',svc['spec'],['spec']),check('Two ready endpoints','endpoints',name='web',count=2),check('Live in-cluster Service response','http',source='client',url='http://web',expected='CLUSTERIP OK'),resource('Deployment is preserved','deployment','web',dep['spec'],['spec'])],docs=['service'],explanation='Service port 80 maps to targetPort 8080 on a selected Pod. There is no additional independently configured “Pod port” hop between the Service and the container’s listener.'))

    dep=http_deployment('gateway',2,body='NODEPORT OK')
    svc=service('gateway',{'app':'gateway'},80,8080,type='NodePort')
    svc['spec']['ports'][0]['nodePort']=30080
    out.append(task('n02','Expose a NodePort on both nodes','networking',[
      'Deployment `gateway` listens on `8080` and has label `app=gateway`.',
      'Create Service `gateway` with `type: NodePort`, TCP `port: 80`, `targetPort: 8080`, and `nodePort: 30080`. Select `app=gateway`.',
      'Verify `curl http://cluster:30080` and `curl http://worker:30080` from this terminal. Both should return NODEPORT OK.',
      'Do not try to create a second ClusterIP Service. The NodePort Service receives its own ClusterIP automatically.'
    ],minutes=6,seeds=[dep],final=[svc],checks=[resource('NodePort Service has all three correct ports','service','gateway',svc['spec'],['spec']),resource('A ClusterIP was also allocated','service','gateway',True,['spec','clusterIP'],'nonempty'),check('Control-plane node NodePort responds','http_external',url='http://cluster:30080',expected='NODEPORT OK'),check('Worker node NodePort responds','http_external',url='http://worker:30080',expected='NODEPORT OK')],docs=['service'],explanation='NodePort builds on ClusterIP behavior. With the default externalTrafficPolicy: Cluster, the NodePort can be used on either node and routed to an eligible backend, even when that node does not host the selected Pod. Docker keeps these lab node addresses inside its private network.'))

    dep=http_deployment('named-web',2,body='NAMED PORT OK')
    svc=service('named-web',{'app':'named-web'},9090,'http')
    out.append(task('n03','Resolve a named targetPort','networking',[
      'Deployment `named-web` declares a container port named `http` with numeric port `8080`.',
      'Create ClusterIP Service `named-web` selecting `app=named-web`, exposing Service port `9090`, with the literal named targetPort `http`.',
      'Keep the workload unchanged. Verify from Pod `client` that `http://named-web:9090` returns NAMED PORT OK.'
    ],minutes=5,seeds=[dep,sleeper('client')],final=[svc],checks=[resource('Service uses the named targetPort','service','named-web',svc['spec'],['spec']),check('Named-port Service has two ready backends','endpoints',name='named-web',count=2),check('Named-port request reaches the application','http',source='client',url='http://named-web:9090',expected='NAMED PORT OK')],docs=['service'],explanation='A named targetPort is resolved against named container ports on selected Pods. The Service’s outward-facing port need not equal the container listener port.'))

    dep=http_deployment('catalog',2,body='CATALOG OK')
    old=service('catalog',{'app':'wrong-catalog'},80,8080)
    new=service('catalog',{'app':'catalog'},80,8080)
    out.append(task('n04','Troubleshoot an empty Service endpoint set','networking',[
      'Deployment `catalog` is healthy but Service `catalog` has no working backends. Inspect labels, the Service selector, and EndpointSlices.',
      'Fix the Service selector to exactly `app=catalog`, leaving Service port `80` and target port `8080`.',
      'Do not modify the Deployment. Verify from Pod `client` that `http://catalog` returns CATALOG OK.'
    ],minutes=5,seeds=[dep,old,sleeper('client')],final=[new],checks=[resource('Selector and ports corrected','service','catalog',new['spec'],['spec']),resource('Original workload retained','deployment','catalog',dep['spec'],['spec']),check('Two ready EndpointSlice backends','endpoints',name='catalog',count=2),check('Service request succeeds','http',source='client',url='http://catalog',expected='CATALOG OK')],docs=['service','debug'],explanation='A Service selector matches Pod labels, not Deployment names. EndpointSlices reveal which backend addresses and ports the control plane has actually published.'))

    dep=http_deployment('payments',2,body='PAYMENTS OK')
    old=service('payments',{'app':'payments'},80,8081)
    new=service('payments',{'app':'payments'},80,8080)
    out.append(task('n05','Repair a Service target port','networking',[
      'Service `payments` selects the correct Pods, but requests fail. The application is listening on `8080`.',
      'Fix only the Service targetPort to `8080`; preserve type ClusterIP, selector `app=payments`, and Service port `80`.',
      'Keep the Deployment unchanged. Verify `http://payments` from Pod `client` returns PAYMENTS OK.'
    ],minutes=5,seeds=[dep,old,sleeper('client')],final=[new],checks=[resource('Service target port repaired','service','payments',new['spec'],['spec']),resource('Deployment unchanged','deployment','payments',dep['spec'],['spec']),check('Live request reaches the correct port','http',source='client',url='http://payments',expected='PAYMENTS OK')],docs=['service','debug'],explanation='A correct selector is not enough. EndpointSlices can exist while the target port points to a socket where no process is listening.'))

    dep=http_deployment('portal',2,body='PORTAL OK'); svc=service('portal',{'app':'portal'},80,8080)
    ing=obj('Ingress','portal',{'ingressClassName':'traefik','rules':[{'host':'portal.ckad.test','http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':'portal','port':{'number':80}}}}]}}]},api='networking.k8s.io/v1')
    out.append(task('n06','Route an HTTP hostname through Ingress','networking',[
      'Deployment and Service `portal` are ready. The Service exposes port `80`. The lab has a real Traefik Ingress controller and IngressClass `traefik`.',
      'Create networking.k8s.io/v1 Ingress `portal`, class `traefik`, host `portal.ckad.test`, and path `/` with pathType `Prefix`.',
      'Route to Service `portal` port `80`. Verify from the terminal with `curl -H "Host: portal.ckad.test" http://cluster/` and expect PORTAL OK.'
    ],minutes=7,seeds=[dep,svc],final=[ing],checks=[resource('Host, class, path and v1 backend','ingress','portal',ing['spec'],['spec']),check('Actual Ingress request is routed correctly','http_external',url='http://cluster/',host='portal.ckad.test',expected='PORTAL OK')],docs=['ingress'],explanation='An Ingress object requires an installed controller to route traffic. This lab supplies Traefik. The Host header lets you test host-based routing without editing your computer’s DNS or hosts file.'))

    red=http_deployment('red',1,body='RED ROUTE',subdir='red'); blue=http_deployment('blue',1,body='BLUE ROUTE',subdir='blue')
    redsvc=service('red',{'app':'red'},80,8080); bluesvc=service('blue',{'app':'blue'},80,8080)
    paths=[{'path':'/'+name,'pathType':'Prefix','backend':{'service':{'name':name,'port':{'number':80}}}} for name in ('red','blue')]
    ing=obj('Ingress','colors',{'ingressClassName':'traefik','rules':[{'host':'colors.ckad.test','http':{'paths':paths}}]},api='networking.k8s.io/v1')
    out.append(task('n07','Route different paths to different applications','networking',[
      'Services `red` and `blue` expose their corresponding applications on port `80`. They already serve pages under `/red/` and `/blue/` respectively.',
      'Create Ingress `colors`, class `traefik`, host `colors.ckad.test`.',
      'Use Prefix path `/red` to Service `red:80` and Prefix path `/blue` to Service `blue:80`. Do not add rewrite annotations or change the applications.',
      'Verify both paths using a Host header from the terminal. Expect RED ROUTE and BLUE ROUTE respectively.'
    ],level='Advanced',minutes=8,seeds=[red,blue,redsvc,bluesvc],final=[ing],checks=[resource('Both prefix routes and backends','ingress','colors',ing['spec'],['spec']),check('Red HTTP route works','http_external',url='http://cluster/red/',host='colors.ckad.test',expected='RED ROUTE'),check('Blue HTTP route works','http_external',url='http://cluster/blue/',host='colors.ckad.test',expected='BLUE ROUTE')],docs=['ingress'],explanation='The backend applications already understand the requested paths. Prefix matching does not inherently remove the matched path segment; rewriting is controller-specific and is intentionally unnecessary here.'))

    fixtures=[http_pod('backend',{'app':'backend'}),sleeper('frontend',{'role':'frontend'}),sleeper('outsider',{'role':'other'})]
    deny=policy('default-deny',{'podSelector':{},'policyTypes':['Ingress'],'ingress':[]})
    allow=policy('allow-frontend',{'podSelector':{'matchLabels':{'app':'backend'}},'policyTypes':['Ingress'],'ingress':[{'from':[{'podSelector':{'matchLabels':{'role':'frontend'}}}],'ports':[{'protocol':'TCP','port':8080}]}]})
    out.append(task('n08','Deny inbound traffic and allow one application tier','networking',[
      'Pods `backend`, `frontend`, and `outsider` are provided. Do not modify their labels, images, commands, or security settings.',
      'Create NetworkPolicy `default-deny` selecting all Pods and denying all ingress in this namespace. Do not restrict egress.',
      'Create NetworkPolicy `allow-frontend` selecting `app=backend`. Permit ingress only from Pods labeled `role=frontend` in this same namespace, on TCP `8080`.',
      'Verify frontend can reach backend’s Pod IP on 8080 while outsider cannot. The lab actually enforces NetworkPolicies.'
    ],level='Advanced',minutes=9,seeds=fixtures,final=[deny,allow],checks=[resource('Namespace default-deny ingress policy','networkpolicy','default-deny',deny['spec'],['spec'],'network_policy'),resource('Precisely scoped frontend exception','networkpolicy','allow-frontend',allow['spec'],['spec'],'network_policy'),*task_fixture_checks(fixtures),traffic('Frontend traffic is allowed','frontend','backend'),traffic('Outsider traffic is blocked','outsider','backend',False)],docs=['networkpolicy'],explanation='Policies are additive: the default deny and explicit allow combine. A podSelector inside from, without a namespaceSelector, selects source Pods in the policy’s own namespace. Incoming and outgoing isolation are separate.'))

    trusted='ckad-n09-trusted'; foreign='ckad-n09-foreign'
    target=http_pod('backend',{'app':'backend'})
    good=sleeper('good-client',{'role':'client'}); good['metadata']['namespace']=trusted
    wrong=sleeper('wrong-role',{'role':'batch'}); wrong['metadata']['namespace']=trusted
    outside=sleeper('foreign-client',{'role':'client'}); outside['metadata']['namespace']=foreign
    fixtures=[target,good,wrong,outside]
    allow=policy('finance-clients',{'podSelector':{'matchLabels':{'app':'backend'}},'policyTypes':['Ingress'],'ingress':[{'from':[{'namespaceSelector':{'matchLabels':{'team':'finance'}},'podSelector':{'matchLabels':{'role':'client'}}}],'ports':[{'protocol':'TCP','port':8080}]}]})
    out.append(task('n09','Combine namespace and Pod selectors with AND','networking',[
      'The backend Pod in this task namespace listens on 8080. Namespace `ckad-n09-trusted` is labeled `team=finance`; namespace `ckad-n09-foreign` is labeled `team=engineering`.',
      'Create NetworkPolicy `finance-clients` selecting `app=backend`. Allow only TCP `8080` from Pods labeled `role=client` in namespaces labeled `team=finance`.',
      'Both selectors must apply to the same source peer (AND), not separate peers (OR). Preserve all fixture Pods and namespace labels.',
      'The trusted good-client must connect. The trusted wrong-role Pod and foreign foreign-client Pod must both be blocked.'
    ],level='Advanced',minutes=10,seeds=fixtures,final=[allow],extra_namespaces=[{'name':trusted,'labels':{'team':'finance'}},{'name':foreign,'labels':{'team':'engineering'}}],checks=[
      resource('AND-scoped namespace and Pod selectors','networkpolicy','finance-clients',allow['spec'],['spec'],'network_policy'),resource('Trusted namespace label preserved','namespace',trusted,{'team':'finance'},['metadata','labels']),resource('Foreign namespace label preserved','namespace',foreign,{'team':'engineering'},['metadata','labels']),*task_fixture_checks(fixtures),
      traffic('Finance client allowed','good-client','backend',True,trusted),traffic('Wrong role within finance blocked','wrong-role','backend',False,trusted),traffic('Correct role in wrong namespace blocked','foreign-client','backend',False,foreign)],docs=['networkpolicy'],explanation='namespaceSelector and podSelector in one from item are ANDed. Putting them in separate list items creates an OR, which is a materially broader rule. The grader checks real cross-namespace traffic in addition to the API shape.'))

    fixtures=[sleeper('client',{'role':'client'}),http_pod('backend',{'app':'backend'},'EGRESS OK'),http_pod('unrelated',{'app':'other'},'OTHER')]
    svc=service('backend',{'app':'backend'},8080,8080)
    egress=policy('restrict-client',{'podSelector':{'matchLabels':{'role':'client'}},'policyTypes':['Egress'],'egress':[
      {'to':[{'podSelector':{'matchLabels':{'app':'backend'}}}],'ports':[{'protocol':'TCP','port':8080}]},
      {'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}]}
    ]})
    out.append(task('n10','Restrict egress without breaking cluster DNS','networking',[
      'Pods `client`, `backend`, and `unrelated`, plus Service `backend:8080`, are provided. Preserve these fixtures.',
      'Create NetworkPolicy `restrict-client` selecting `role=client` and isolating its egress only.',
      'Allow TCP 8080 to Pods labeled `app=backend` in this namespace. Also allow UDP and TCP port 53 to Pods labeled `k8s-app=kube-dns` in namespace `kube-system`, selected with `kubernetes.io/metadata.name=kube-system`.',
      'Permit no other egress. The client must resolve and fetch `http://backend:8080`, but must not reach unrelated’s Pod IP on 8080.'
    ],level='Advanced',minutes=10,seeds=[*fixtures,svc],final=[egress],checks=[resource('Only backend and DNS egress rules','networkpolicy','restrict-client',egress['spec'],['spec'],'network_policy'),*task_fixture_checks(fixtures),check('DNS resolution and permitted Service request work','http',source='client',url='http://backend:8080',expected='EGRESS OK'),traffic('Unrelated destination is blocked','client','unrelated',False)],docs=['networkpolicy','service'],explanation='Egress isolation can accidentally break DNS, even when the application’s destination is permitted. This task includes both UDP and TCP DNS and scopes the resolver allowance using namespace and Pod selectors together.'))
    return out
