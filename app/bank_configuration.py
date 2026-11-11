from bank_helpers import *
import base64

def encoded(text): return base64.b64encode(text.encode()).decode()

def tasks():
    out=[]
    cm=obj('ConfigMap','app-settings',data={'APP_ENV':'production','REGION':'us-central'})
    env=[{'name':k,'valueFrom':{'configMapKeyRef':{'name':'app-settings','key':k}}} for k in ('APP_ENV','REGION')]
    p=pod('configured',[container('app',BUSYBOX,['sh','-c','sleep 86400'],env=env)])
    out.append(task('c01','Inject ConfigMap values as environment variables','configuration',[
      'Create ConfigMap `app-settings` with keys `APP_ENV=production` and `REGION=us-central`.',
      'Create Pod `configured`, container `app`, image `busybox:1.37.0`, and a long-running sleep command.',
      'Populate environment variables `APP_ENV` and `REGION` using individual `configMapKeyRef` entries referring to the corresponding keys. Do not use literal values or envFrom in this task.',
      'Leave the Pod Ready, with both values available inside its container.'
    ],minutes=6,final=[cm,p],checks=[resource('ConfigMap data','configmap','app-settings',cm['data'],['data']),resource('Busybox container and both explicit ConfigMap key references','pod','configured',{'image':BUSYBOX,'env':env},C('app')),exec_check('Actual environment values','configured',['sh','-c','printf "%s %s" "$APP_ENV" "$REGION"'],'production us-central','app'),ready('pod','configured')],docs=['configmap'],explanation='The environment variable name and the ConfigMap key need not be the same in general; this task specifies both. Environment values from a ConfigMap are captured at container creation, not refreshed automatically in an already running process.'))

    cm=obj('ConfigMap','file-settings',data={'app.json':'{"port":8080,"mode":"production"}'})
    p=pod('file-app',[container('app',BUSYBOX,['sh','-c','sleep 86400'],volumeMounts=[{'name':'settings','mountPath':'/etc/app','readOnly':True}])],volumes=[{'name':'settings','configMap':{'name':'file-settings','items':[{'key':'app.json','path':'config.json'}]}}])
    out.append(task('c02','Project a ConfigMap key to a named file','configuration',[
      'Create ConfigMap `file-settings` with key `app.json` containing `{"port":8080,"mode":"production"}`.',
      'Create Pod `file-app`, container `app`, image `busybox:1.37.0`, kept running.',
      'Mount a ConfigMap volume named `settings` read-only at `/etc/app`. Project key `app.json` specifically to filename `config.json`.',
      'The file `/etc/app/config.json` inside the container must contain the supplied JSON.'
    ],minutes=6,final=[cm,p],checks=[resource('ConfigMap key exists with requested JSON','configmap','file-settings',cm['data'],['data']),resource('Key-to-path mapping and read-only mount','pod','file-app',{'volumes':p['spec']['volumes'],'containers':[{'name':'app','image':BUSYBOX,'volumeMounts':p['spec']['containers'][0]['volumeMounts']}]},['spec']),exec_check('Mounted file content','file-app',['cat','/etc/app/config.json'],cm['data']['app.json'],'app'),ready('pod','file-app')],docs=['configmap','volume'],explanation='items maps a ConfigMap key to a relative filename within the mounted volume. The volume mount path is a directory, so config.json appears underneath /etc/app.'))

    sec=obj('Secret','credentials',type='Opaque',stringData={'username':'ckad','password':'practice-only-42'})
    env=[{'name':'DB_USER','valueFrom':{'secretKeyRef':{'name':'credentials','key':'username'}}},{'name':'DB_PASSWORD','valueFrom':{'secretKeyRef':{'name':'credentials','key':'password'}}}]
    p=pod('secret-app',[container('app',BUSYBOX,['sh','-c','sleep 86400'],env=env)])
    out.append(task('c03','Create and consume a Secret','configuration',[
      'Create an Opaque Secret named `credentials` with `username=ckad` and `password=practice-only-42`. These are fictional lab values.',
      'Create Pod `secret-app`, container `app`, image `busybox:1.37.0`, kept running.',
      'Use Secret key references to expose username as `DB_USER` and password as `DB_PASSWORD`. Do not put the literal credentials in the Pod spec.',
      'Leave the Pod Ready and verify that the values are available to the process.'
    ],minutes=6,final=[sec,p],checks=[resource('Secret type and data','secret','credentials',{'type':'Opaque','data':{k:encoded(v) for k,v in sec['stringData'].items()}}),resource('Busybox container uses Secret key references','pod','secret-app',{'image':BUSYBOX,'env':env},C('app')),exec_check('Runtime environment contains the expected lab values','secret-app',['sh','-c','printf "%s %s" "$DB_USER" "$DB_PASSWORD"'],'ckad practice-only-42','app'),ready('pod','secret-app')],docs=['secret'],explanation='stringData accepts ordinary strings and is converted to data by the API server. data values are base64 encoded; that encoding alone is not encryption. Only synthetic credentials are used in this lab.'))

    sec=obj('Secret','db-auth',type='Opaque',stringData={'password':'mount-only-42'})
    p=pod('secret-file',[container('app',BUSYBOX,['sh','-c','sleep 86400'],volumeMounts=[{'name':'auth','mountPath':'/run/auth','readOnly':True}])],volumes=[{'name':'auth','secret':{'secretName':'db-auth','defaultMode':256}}])
    out.append(task('c04','Mount a Secret with restrictive file permissions','configuration',[
      'Create Opaque Secret `db-auth` with key `password=mount-only-42`.',
      'Create Pod `secret-file`, container `app`, image `busybox:1.37.0`, kept running as its default user.',
      'Mount Secret volume `auth` read-only at `/run/auth`, with default file mode `0400` (decimal `256`).',
      'Verify the projected `/run/auth/password` file is readable by the container and contains the supplied value.'
    ],minutes=6,final=[sec,p],checks=[resource('Secret data','secret','db-auth',{'password':encoded('mount-only-42')},['data']),resource('Secret volume has 0400 default mode','pod','secret-file',p['spec']['volumes'],['spec','volumes']),resource('Busybox image and read-only volume mount','pod','secret-file',{'image':BUSYBOX,'volumeMounts':[{'name':'auth','mountPath':'/run/auth','readOnly':True}]},C('app')),exec_check('Mounted secret value','secret-file',['cat','/run/auth/password'],'mount-only-42','app'),exec_check('Actual projected file mode is 400','secret-file',['stat','-c','%a','/run/auth/..data/password'],'400','app'),ready('pod','secret-file')],docs=['secret'],explanation='Kubernetes Secret projection uses symlinks. The grader checks the backing projected file’s permissions rather than the permissions of the symlink. Octal 0400 and decimal 256 express the same permission bits.'))

    sa=obj('ServiceAccount','auditor')
    p=pod('agent',[container('agent',BUSYBOX,['sh','-c','sleep 86400'])],serviceAccountName='auditor',automountServiceAccountToken=False)
    out.append(task('c05','Assign a ServiceAccount without mounting its token','configuration',[
      'Create ServiceAccount `auditor`.',
      'Create Pod `agent` with container `agent`, image `busybox:1.37.0`, and a long-running sleep command.',
      'Set `serviceAccountName: auditor` and explicitly set Pod-level `automountServiceAccountToken: false`.',
      'Leave the Pod Ready without a token file at `/var/run/secrets/kubernetes.io/serviceaccount/token`.'
    ],minutes=5,final=[sa,p],checks=[resource('ServiceAccount exists','serviceaccount','auditor',{'metadata':{'name':'auditor'}}),resource('Pod identity and explicit token setting','pod','agent',{'serviceAccountName':'auditor','automountServiceAccountToken':False,'containers':[{'name':'agent','image':BUSYBOX}]},['spec']),exec_check('No default token is mounted','agent',['sh','-c','test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token && printf absent'],'absent','agent'),ready('pod','agent')],docs=['sa'],explanation='The ServiceAccount identity and automatic token-volume mounting are distinct settings. A workload can be assigned an identity without receiving an automatically mounted API credential.'))

    sa=obj('ServiceAccount','reporter')
    role=obj('Role','pod-reader',api='rbac.authorization.k8s.io/v1',rules=[{'apiGroups':[''],'resources':['pods'],'verbs':['get','list','watch']},{'apiGroups':[''],'resources':['pods/log'],'verbs':['get']}])
    bind=obj('RoleBinding','read-pods',api='rbac.authorization.k8s.io/v1',subjects=[{'kind':'ServiceAccount','name':'reporter','namespace':'ckad-c06'}],roleRef={'kind':'Role','name':'pod-reader','apiGroup':'rbac.authorization.k8s.io'})
    checks=[resource('Reporter ServiceAccount exists','serviceaccount','reporter',{'metadata':{'name':'reporter'}}),check('Role has exactly the intended permissions','rbac_rules',name='pod-reader',rules=role['rules']),resource('RoleBinding targets the reporter ServiceAccount','rolebinding','read-pods',{'subjects':bind['subjects'],'roleRef':bind['roleRef']})]
    for verb,res,allowed,ns in [('get','pods',True,None),('list','pods',True,None),('watch','pods',True,None),('get','pods/log',True,None),('get','secrets',False,None),('delete','pods',False,None),('create','pods',False,None),('list','pods',False,'default')]:
        checks.append(check(f"reporter {'can' if allowed else 'cannot'} {verb} {res}"+(' in default' if ns else ''),'auth',sa='reporter',verb=verb,resource=res,allowed=allowed,target_namespace=ns))
    out.append(task('c06','Grant narrowly scoped application permissions','configuration',[
      'Create ServiceAccount `reporter`, Role `pod-reader`, and RoleBinding `read-pods` in this task namespace.',
      'The Role must allow get/list/watch of core API Pods and get of the core `pods/log` subresource.',
      'Bind the Role to this namespace’s reporter ServiceAccount. Do not grant access to Secrets, permission to create/delete Pods, or Pod-reading privileges in namespace `default`.',
      'Use impersonation with kubectl auth can-i to verify both allowed and denied operations.'
    ],level='Advanced',minutes=9,final=[sa,role,bind],checks=checks,docs=['rbac','sa'],explanation='Authentication identifies a caller; RBAC authorization decides which operations that identity may perform. pods/log is a separate subresource. A RoleBinding grants the referenced namespaced Role within its own namespace, not cluster-wide.'))

    dep=deployment('sized',2)
    new=deepcopy(dep); new['spec']['template']['spec']['containers'][0]['resources']={'requests':{'cpu':'100m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'128Mi'}}
    checks=[quantity(f'{area} {key} equals {value}','deployment','sized',D()+['resources',area,key],value) for area,vals in new['spec']['template']['spec']['containers'][0]['resources'].items() for key,value in vals.items()]
    checks += [resource('Two replicas and original image remain','deployment','sized',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','sized')]
    out.append(task('c07','Set container resource requests and limits','configuration',[
      'Deployment `sized` already exists. Set resource requests on container `web` to CPU `100m` and memory `64Mi`.',
      'Set resource limits to CPU `500m` and memory `128Mi`.',
      'Keep two replicas and the existing image. Leave the rollout complete. Equivalent valid Kubernetes quantity representations are accepted.'
    ],minutes=5,seeds=[dep],final=[new],checks=checks,docs=['resources'],explanation='Requests influence scheduling and resource allocation; limits constrain resource use. CPU is commonly expressed in millicores. Mi is mebibytes, not decimal megabytes. The grader compares quantity values semantically.'))

    lr=obj('LimitRange','container-defaults',{'limits':[{'type':'Container','defaultRequest':{'cpu':'100m','memory':'64Mi'},'default':{'cpu':'500m','memory':'128Mi'}}]})
    rq=obj('ResourceQuota','namespace-budget',{'hard':{'requests.cpu':'1','requests.memory':'512Mi','limits.cpu':'2','limits.memory':'1Gi','pods':'5'}})
    p=sleeper('defaults')
    checks=[resource('Container LimitRange exists','limitrange','container-defaults',{'limits':[{'type':'Container'}]},['spec'])]
    for section, vals in lr['spec']['limits'][0].items():
        if isinstance(vals,dict):
            for key,val in vals.items(): checks.append(quantity(f'LimitRange {section} {key}','limitrange','container-defaults',['spec','limits',{'type':'Container'},section,key],val))
    for key,val in rq['spec']['hard'].items(): checks.append(quantity(f'Quota {key}','resourcequota','namespace-budget',['spec','hard',key],val))
    for area, vals in {'requests':{'cpu':'100m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'128Mi'}}.items():
        for key,val in vals.items(): checks.append(quantity(f'Admitted Pod {area} {key}','pod','defaults',C('client')+['resources',area,key],val))
    checks.append(ready('pod','defaults'))
    out.append(task('c08','Apply namespace defaults and a resource budget','configuration',[
      'Create LimitRange `container-defaults` for type `Container`: default requests CPU `100m`, memory `64Mi`; default limits CPU `500m`, memory `128Mi`.',
      'Create ResourceQuota `namespace-budget` with hard limits: `requests.cpu=1`, `requests.memory=512Mi`, `limits.cpu=2`, `limits.memory=1Gi`, and `pods=5`.',
      'After those policies exist, create Pod `defaults`, container `client`, image `busybox:1.37.0`, sleeping for a long time. Do not specify resources in your submitted Pod manifest.',
      'Verify that admission filled in its requests and limits, and leave the Pod Ready.'
    ],level='Advanced',minutes=9,final=[lr,rq,p],checks=checks,docs=['limitrange','quota','resources'],
      explanation='LimitRange supplies per-container defaults at admission; ResourceQuota limits aggregate namespace consumption. This grader checks admitted values. It cannot prove that you omitted explicit values from a manifest unless the manifest itself is separately required.'))

    security={'runAsNonRoot':True,'runAsUser':1000,'runAsGroup':3000,'fsGroup':2000,'seccompProfile':{'type':'RuntimeDefault'}}
    csec={'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}}
    p=pod('hardened',[container('app',BUSYBOX,['sh','-c','echo writable > /tmp/check; sleep 86400'],securityContext=csec,volumeMounts=[{'name':'tmp','mountPath':'/tmp'}])],securityContext=security,volumes=[{'name':'tmp','emptyDir':{}}])
    out.append(task('c09','Harden a container while preserving writable scratch space','configuration',[
      'Create Pod `hardened`, container `app`, image `busybox:1.37.0`, kept running.',
      'At Pod level set runAsNonRoot true, UID `1000`, primary GID `3000`, fsGroup `2000`, and seccomp profile `RuntimeDefault`.',
      'At container level disallow privilege escalation, drop all Linux capabilities, and make the root filesystem read-only.',
      'Mount emptyDir `tmp` at `/tmp`. Write `writable` to `/tmp/check` and keep the application running with the requested identity.'
    ],level='Advanced',minutes=9,final=[p],checks=[resource('Pod-level identity and seccomp','pod','hardened',security,['spec','securityContext']),resource('Container-level restrictions','pod','hardened',csec,C('app')+['securityContext']),resource('Writable emptyDir mount','pod','hardened',{'volumes':[{'name':'tmp','emptyDir':{}}],'containers':[{'name':'app','image':BUSYBOX,'volumeMounts':[{'name':'tmp','mountPath':'/tmp'}]}]},['spec']),exec_check('Actual UID and primary GID','hardened',['sh','-c','printf "%s:%s" "$(id -u)" "$(id -g)"'],'1000:3000','app'),exec_check('Scratch file is present','hardened',['cat','/tmp/check'],'writable','app'),ready('pod','hardened')],docs=['security','volume'],explanation='Pod-level securityContext applies identity and volume ownership settings; container-level securityContext configures capabilities and root filesystem policy. A read-only root filesystem can coexist with a writable mounted emptyDir.'))

    ns=obj('Namespace','ckad-c10',labels={'pod-security.kubernetes.io/enforce':'restricted','pod-security.kubernetes.io/enforce-version':'v1.35'})
    p=pod('restricted-app',[container('app',BUSYBOX,['sh','-c','sleep 86400'],securityContext={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}})],securityContext={'runAsNonRoot':True,'runAsUser':1000,'seccompProfile':{'type':'RuntimeDefault'}})
    out.append(task('c10','Meet a restricted Pod Security admission policy','configuration',[
      'Label this namespace to enforce Pod Security level `restricted` at policy version `v1.35`.',
      'Create Pod `restricted-app`, container `app`, image `busybox:1.37.0`, and a long-running sleep command.',
      'Use non-root UID `1000`, runAsNonRoot true, RuntimeDefault seccomp, allowPrivilegeEscalation false, and drop ALL capabilities so the Pod is admitted.',
      'Leave the namespace policy active and the Pod Ready. Do not weaken the policy to make the Pod run.'
    ],level='Advanced',minutes=8,final=[ns,p],checks=[resource('Namespace enforces restricted v1.35','namespace','ckad-c10',ns['metadata']['labels'],['metadata','labels']),resource('Requested security settings','pod','restricted-app',p['spec'],['spec']),ready('pod','restricted-app'),check('A privileged test Pod is rejected by server-side dry-run admission','admission_denied')],docs=['admission','security'],explanation='Pod Security Admission evaluates new or changed Pod requests. Applying an enforce label does not automatically evict pre-existing running Pods. The grader makes a server-side dry-run request; it does not create a privileged test Pod.'))

    cr=obj('Widget','gallery',{'replicas':2,'image':NGINX},api='practice.ckad.local/v1')
    out.append(task('c11','Discover a custom API and drive its operator','configuration',[
      'A namespaced custom API `widgets.practice.ckad.local` is installed, with version `v1`. Discover it with kubectl api-resources and kubectl explain.',
      'Create a `Widget` named `gallery` with `spec.replicas: 2` and `spec.image: nginx:1.27.5-alpine`.',
      'The provided lab operator reconciles each Widget into Deployment `widget-<name>`. Leave `widget-gallery` with two available replicas.',
      'Manage the Widget, not the generated Deployment. Do not alter or delete the cluster-wide CRD. This is a deliberately small, real training controller, not a production operator.'
    ],minutes=7,final=[cr],checks=[resource('Custom resource spec','widgets.practice.ckad.local','gallery',cr['spec'],['spec']),resource('Generated Deployment belongs to the Widget','deployment','widget-gallery',[{'kind':'Widget','name':'gallery','apiVersion':'practice.ckad.local/v1','controller':True}],['metadata','ownerReferences']),resource('Generated replica count and image','deployment','widget-gallery',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','widget-gallery')],docs=['crd','operator'],
      explanation='A CRD adds an API and validation schema; it does not by itself run an application. A controller implements reconciliation. This app runs a small real reconciliation loop for the provided Widget API, so changing spec.replicas changes its owned Deployment.'))

    p=pod('identity',[container('app',BUSYBOX,['sh','-c','sleep 86400'],env=[{'name':'MY_POD_NAME','valueFrom':{'fieldRef':{'fieldPath':'metadata.name'}}}],volumeMounts=[{'name':'meta','mountPath':'/meta','readOnly':True}])],volumes=[{'name':'meta','downwardAPI':{'items':[{'path':'namespace','fieldRef':{'fieldPath':'metadata.namespace'}}]}}])
    out.append(task('c12','Expose Pod identity with the Downward API','configuration',[
      'Create Pod `identity`, container `app`, image `busybox:1.37.0`, kept running.',
      'Populate `MY_POD_NAME` through a fieldRef to `metadata.name`, not a literal string.',
      'Use a downwardAPI volume named `meta` with an item named `namespace` referencing `metadata.namespace`. Mount it read-only at `/meta`.',
      'Verify that the process sees MY_POD_NAME=identity and that `/meta/namespace` contains this task namespace.'
    ],minutes=6,final=[p],checks=[resource('Busybox image and Pod-name field reference','pod','identity',{'image':BUSYBOX,'env':p['spec']['containers'][0]['env']},C('app')),resource('Downward API projection and mount','pod','identity',{'volumes':p['spec']['volumes'],'containers':[{'name':'app','volumeMounts':p['spec']['containers'][0]['volumeMounts']}]},['spec']),exec_check('Runtime Pod name','identity',['sh','-c','printf %s "$MY_POD_NAME"'],'identity','app'),exec_check('Projected namespace','identity',['cat','/meta/namespace'],'ckad-c12','app'),ready('pod','identity')],docs=['downward'],explanation='The Downward API exposes selected metadata without requiring the application to call the Kubernetes API. Environment and volume forms have different available fields and update behavior.'))
    return out
