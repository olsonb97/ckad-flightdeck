from bank_helpers import *
import base64

def tasks():
    out=[]
    old=deployment('healthy',2)
    final=deepcopy(old)
    web=final['spec']['template']['spec']['containers'][0]
    web['readinessProbe']=probe(80,'/',initialDelaySeconds=3,periodSeconds=5)
    web['livenessProbe']=probe(80,'/',initialDelaySeconds=5,periodSeconds=10)
    out.append(task('o01','Add readiness and liveness health checks','observability',[
      'Deployment `healthy` exists with two nginx replicas. Add HTTP readiness and liveness probes to container `web`, using path `/` and port `80`.',
      'Readiness: initial delay `3` seconds and period `5` seconds. Liveness: initial delay `5` seconds and period `10` seconds.',
      'Keep the existing image and two replicas. Leave the rollout complete and the application Ready.'
    ],minutes=6,seeds=[old],final=[final],checks=[
      resource('Readiness settings','deployment','healthy',web['readinessProbe'],D()+['readinessProbe']),resource('Liveness settings','deployment','healthy',web['livenessProbe'],D()+['livenessProbe']),
      resource('Image and replicas preserved','deployment','healthy',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','healthy')],docs=['probes'],explanation='Readiness determines whether a Pod should receive Service traffic. A liveness failure can restart the container. Neither probe restarts an entire Deployment.'))

    old=deployment('startup',1)
    final=deepcopy(old); c=final['spec']['template']['spec']['containers'][0]
    c.update(startupProbe=probe(80,'/',periodSeconds=2,failureThreshold=30),readinessProbe=probe(80,'/',periodSeconds=3),livenessProbe=probe(80,'/',periodSeconds=5))
    out.append(task('o02','Protect startup without weakening ongoing checks','observability',[
      'Deployment `startup` has one nginx replica. Configure three HTTP probes on container `web`, all using `/` on port `80`.',
      'Startup probe: `periodSeconds: 2`, `failureThreshold: 30`. Readiness probe: period `3`. Liveness probe: period `5`.',
      'Keep the current image and replica count. Leave the updated Pod Ready. The task specifies the probe budget, not an exact startup delay.'
    ],minutes=6,seeds=[old],final=[final],checks=[resource('All three probe configurations','deployment','startup',{k:c[k] for k in ('startupProbe','readinessProbe','livenessProbe')},D()),resource('Image and replica count preserved','deployment','startup',{'replicas':1,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','startup')],docs=['probes'],
      explanation='While a startup probe has not yet succeeded, Kubernetes does not run that container’s liveness or readiness probes. The startup failure budget is approximately failureThreshold × periodSeconds; it is not a mandated application sleep time.'))

    p=pod('audit',[container('app',BUSYBOX,['sh','-c','echo INFO started; echo ERROR payment-timeout; echo INFO retrying; echo ERROR retry-exhausted; sleep 86400']),container('metrics',BUSYBOX,['sh','-c','echo ERROR metrics-only; sleep 86400'])])
    out.append(task('o03','Extract the correct container logs','observability',[
      'Pod `audit` has containers `app` and `metrics`. Inspect logs from `app` only.',
      'Save all lines beginning with `ERROR` from the app container to `/workspace/o03/errors.txt`, in their original order.',
      'Do not include INFO messages or the metrics container’s error. Do not modify or delete the Pod.'
    ],level='Foundation',minutes=4,seeds=[p],solution="kubectl logs audit -c app | grep '^ERROR' > /workspace/o03/errors.txt\ncat /workspace/o03/errors.txt\n",checks=[filecheck('Only the two application error lines, in order','/workspace/o03/errors.txt','ERROR payment-timeout\nERROR retry-exhausted'),ready('pod','audit'),resource('Audit Pod is preserved','pod','audit',p['spec'],['spec'])],docs=['logs','debug'],
      explanation='Always choose the correct container with -c for multi-container Pods. Shell redirection writes the output on the terminal machine, not inside the container.'))

    old=deployment('broken-image',2,'nginx:not-a-real-ckad-tag')
    out.append(task('o04','Diagnose an image-pull failure','observability',[
      'Deployment `broken-image` is not becoming available. Inspect its Pods and events to identify the image-pull problem.',
      'Correct the `web` container image to `nginx:1.27.5-alpine` without changing the Deployment name or replica count `2`.',
      'Leave two updated replicas available. Do not mask the problem by reducing replicas to zero.'
    ],minutes=5,seeds=[old],solution='kubectl get pods\nkubectl describe deployment broken-image\nkubectl get events --sort-by=.metadata.creationTimestamp\nkubectl set image deployment/broken-image web=nginx:1.27.5-alpine\nkubectl rollout status deployment/broken-image --timeout=180s\n',checks=[resource('Valid image and original replicas','deployment','broken-image',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','broken-image')],docs=['debug','deployment'],explanation='ImagePullBackOff is a symptom, not a root cause. Events distinguish an invalid tag from registry authentication, DNS, network, and rate-limit failures. This fixture deliberately uses an invalid tag.'))

    old=deployment('unready',2)
    old['spec']['template']['spec']['containers'][0]['readinessProbe']=probe(8081,'/',periodSeconds=3)
    new=deepcopy(old); new['spec']['template']['spec']['containers'][0]['readinessProbe']['httpGet']['port']=80
    svc=service('unready',{'app':'unready'})
    out.append(task('o05','Repair readiness and restore Service traffic','observability',[
      'Deployment `unready` is running nginx, but its readiness checks fail and Service `unready` has no ready backends.',
      'Fix the existing HTTP readiness probe on container `web` to use path `/` on port `80`. Keep period `3`, both replicas, and the existing image.',
      'Do not remove the readiness probe. Confirm that Pod `client` can get the nginx page from `http://unready`.'
    ],minutes=6,seeds=[old,svc,sleeper('client')],final=[new],checks=[resource('Readiness probe repaired, not removed','deployment','unready',probe(80,'/',periodSeconds=3),D()+['readinessProbe']),resource('Workload preserved','deployment','unready',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','unready'),check('Two ready backends','endpoints',name='unready',count=2),check('Real Service request succeeds','http',source='client',url='http://unready',expected='Welcome to nginx!',op='contains')],docs=['probes','service','debug'],explanation='A running container can belong to a NotReady Pod. Services ordinarily exclude unready endpoints, so a faulty readiness probe can make a healthy listening process unreachable through its Service.'))

    burn=pod('cpu-worker',[container('worker',BUSYBOX,['sh','-c','while true; do :; done'],resources={'requests':{'cpu':'100m','memory':'8Mi'},'limits':{'cpu':'200m','memory':'32Mi'}})],labels={'metrics-task':'true'})
    idle=sleeper('idle',{'metrics-task':'true'})
    out.append(task('o06','Capture live application resource usage','observability',[
      'Pods `cpu-worker` and `idle` are already running. Use the resource metrics API through `kubectl top pods`.',
      'Save their current Pod-level CPU and memory usage, without a header, to `/workspace/o06/usage.txt`. Include one row for each Pod and no other Pods.',
      'Leave the Pods unchanged. Metrics may take a short interval to appear after first creation; missing metrics are not an invitation to invent values.'
    ],minutes=5,seeds=[burn,idle],solution='kubectl top pods -l metrics-task=true --no-headers > /workspace/o06/usage.txt\ncat /workspace/o06/usage.txt\n',checks=[check('Usage file has both Pods and valid measured CPU/memory fields','metrics_file',path='/workspace/o06/usage.txt',pods=['cpu-worker','idle']),ready('pod','cpu-worker'),ready('pod','idle'),*[resource('Pod '+p['metadata']['name']+' is preserved','pod',p['metadata']['name'],p['spec'],['spec']) for p in (burn,idle)]],docs=['top'],
      explanation='CPU and memory metrics fluctuate. The grader validates the selected Pod names, data format, and availability of live metrics rather than demanding byte-for-byte equality with a later sample. This is a practice grader, not proof of the exact command used.'))

    legacy={'apiVersion':'extensions/v1beta1','kind':'Deployment','metadata':{'name':'legacy'},'spec':{'replicas':2,'template':{'metadata':{'labels':{'app':'legacy'}},'spec':{'containers':[container()]}}}}
    olding={'apiVersion':'networking.k8s.io/v1beta1','kind':'Ingress','metadata':{'name':'legacy'},'spec':{'rules':[{'host':'legacy.ckad.test','http':{'paths':[{'path':'/','backend':{'serviceName':'legacy','servicePort':80}}]}}]}}
    dep=deployment('legacy',2)
    ing=obj('Ingress','legacy',{'ingressClassName':'traefik','rules':[{'host':'legacy.ckad.test','http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':'legacy','port':{'number':80}}}}]}}]},api='networking.k8s.io/v1')
    files={'legacy.yaml':yaml.safe_dump_all([legacy,olding],sort_keys=False)}
    out.append(task('o07','Migrate removed API versions','observability',[
      'The starter file `/workspace/o07/legacy.yaml` uses removed Deployment and Ingress APIs. Edit that file; do not submit a second corrected file instead.',
      'Migrate Deployment `legacy` to `apps/v1`, with an explicit selector `app=legacy` matching its Pod labels. Keep two replicas and nginx image `nginx:1.27.5-alpine`.',
      'Migrate Ingress `legacy` to `networking.k8s.io/v1`, class `traefik`, host `legacy.ckad.test`, path `/`, path type `Prefix`, and backend Service `legacy` port `80`.',
      'Apply the corrected file. The Service is already present. Leave the Deployment Ready.'
    ],level='Advanced',minutes=9,seeds=[service('legacy',{'app':'legacy'})],files=files,solution=apply_script([dep,ing],'ckad-o07','/workspace/o07/legacy.yaml')+'kubectl rollout status deployment/legacy --timeout=180s\n',checks=[check('Saved file contains stable APIs and required fields','yaml_file',path='/workspace/o07/legacy.yaml',expected=scoped([dep,ing],'ckad-o07'),ignore_namespace=True),resource('Live Deployment matches requested spec','deployment','legacy',dep['spec'],['spec']),resource('Live Ingress uses the v1 backend structure','ingress','legacy',ing['spec'],['spec']),ready('deployment','legacy')],docs=['deprecation','deployment','ingress'],
      explanation='Changing only apiVersion is insufficient when the schema also changed. apps/v1 Deployments require an explicit selector; networking.k8s.io/v1 Ingress paths require pathType and the nested backend.service structure.'))

    secret=obj('Secret','api-token',type='Opaque',stringData={'token':'training-token-only'})
    dep=deployment('consumer',1,containers=[container('app',BUSYBOX,['sh','-c','test -n "$APP_TOKEN"; sleep 86400'],env=[{'name':'APP_TOKEN','valueFrom':{'secretKeyRef':{'name':'api-token','key':'value'}}}])])
    new=deepcopy(dep); new['spec']['template']['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']['key']='token'
    out.append(task('o08','Fix a failed Secret key reference','observability',[
      'Deployment `consumer` is stuck before its app container starts. Secret `api-token` already exists.',
      'Inspect the failure and correct `APP_TOKEN` to reference the existing key `token` in Secret `api-token`.',
      'Do not replace the reference with a literal, alter the Secret data, or remove the environment variable. Leave the one-replica Deployment available.'
    ],minutes=5,seeds=[secret,dep],final=[new],checks=[resource('Secret key reference corrected','deployment','consumer',[{'name':'APP_TOKEN','valueFrom':{'secretKeyRef':{'name':'api-token','key':'token'}}}],D('app')+['env']),resource('Secret value unchanged','secret','api-token',base64.b64encode(b'training-token-only').decode(),['data','token'],'equals'),resource('One desired replica','deployment','consumer',1,['spec','replicas'],'equals'),ready('deployment','consumer')],docs=['debug','secret'],explanation='CreateContainerConfigError can occur before a container starts, so there may be no application log to inspect. describe and events expose a missing Secret or missing key reference.'))
    return out
