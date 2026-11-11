from bank_helpers import *
import base64

SOURCE = 'https://github.com/aravind4799/CKAD-Practice-Questions'
PYTHON = 'python:3.13.7-slim-bookworm'
API_READER = '''import os, ssl, time, urllib.request, urllib.error
from pathlib import Path
namespace = os.environ['NAMESPACE']
credentials = Path('/var/run/secrets/kubernetes.io/serviceaccount')
context = ssl.create_default_context(cafile=str(credentials / 'ca.crt'))
url = 'https://kubernetes.default.svc/api/v1/namespaces/' + namespace + '/pods'
while True:
    try:
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + (credentials / 'token').read_text().strip()})
        with urllib.request.urlopen(request, context=context, timeout=5) as response:
            status = str(response.status)
    except urllib.error.HTTPError as error:
        status = str(error.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        status = 'connection-error'
    Path('/tmp/access-status').write_text(status)
    print('list pods in namespace ' + namespace + ': HTTP ' + status, flush=True)
    time.sleep(3)
'''


def api_reader(name, account='default'):
    return pod(name, [container('reader', PYTHON, ['python', '-u', '-c', API_READER],
        env=[{'name': 'NAMESPACE', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.namespace'}}}])],
        serviceAccountName=account)


def role(name, verbs=('get', 'list', 'watch'), resources=('pods',)):
    return obj('Role', name, api='rbac.authorization.k8s.io/v1',
        rules=[{'apiGroups': [''], 'resources': list(resources), 'verbs': list(verbs)}])


def binding(name, role_name, account, ns):
    return obj('RoleBinding', name, api='rbac.authorization.k8s.io/v1',
        subjects=[{'kind': 'ServiceAccount', 'name': account, 'namespace': ns}],
        roleRef={'kind': 'Role', 'name': role_name, 'apiGroup': 'rbac.authorization.k8s.io'})


def ingress(name, host, service_name, port, path='/'):
    rule = {'http': {'paths': [{'path': path, 'pathType': 'Prefix',
        'backend': {'service': {'name': service_name, 'port': {'number': port}}}}]}}
    if host: rule['host'] = host
    return obj('Ingress', name, {'ingressClassName': 'traefik', 'rules': [rule]}, api='networking.k8s.io/v1')


def scenario(number, title, domain, requirements, guide, **kwargs):
    value = task(f's{number:02}', title, domain, requirements, **kwargs)
    value.update(set_id='focused', source_question=number, walkthrough=guide)
    value['docs'].append({'label': f'Source question {number}', 'url': f'{SOURCE}/blob/master/README.md#question-{number}'})
    return value


def tasks():
    out = []
    values = {'DB_USER': 'admin', 'DB_PASS': 'Secret123!'}
    old = deployment('api-server', 2, containers=[container(env=[{'name': k, 'value': v} for k, v in values.items()])])
    secret = obj('Secret', 'db-credentials', type='Opaque', stringData=values)
    final = deepcopy(old)
    env = [{'name': k, 'valueFrom': {'secretKeyRef': {'name': 'db-credentials', 'key': k}}} for k in values]
    final['spec']['template']['spec']['containers'][0]['env'] = env
    out.append(scenario(1, 'Create a Secret from hard-coded variables', 'configuration', [
        'Deployment `api-server` has the example credentials `DB_USER=admin` and `DB_PASS=Secret123!` in its environment.',
        'Create Secret `db-credentials` with both values. Replace the two literal environment entries with matching `valueFrom.secretKeyRef` references.',
        'Keep the Deployment named `api-server` in this question’s namespace, and verify its rollout.'
    ], (
        'Inspect the existing template before changing it. The application already expects two particular environment-variable names; moving their source must not change the interface seen by the process.',
        'Create the namespaced Secret using the fictional values, then replace each env entry with valueFrom.secretKeyRef. Remove the old value field rather than combining a literal with a reference.',
        'Wait for the Deployment rollout so replacement containers resolve the new references. Check the template structure and Secret key names without printing real credentials into logs or screenshots.',
        'A Secret in another namespace cannot satisfy this reference. Updating Secret data also does not refresh environment variables inside containers that are already running.',
        'kubectl rollout status deployment/api-server --timeout=180s\nkubectl get deployment api-server -o yaml\nkubectl describe secret db-credentials',
        'Two replicas are available, both environment entries use Secret references, and the Secret contains the two expected keys.'
    ), seeds=[old], final=[secret, final], checks=[
        resource('Secret retains the fictional application values', 'secret', 'db-credentials', {'type': 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}}),
        resource('Environment uses references without literal values', 'deployment', 'api-server', env, D()+['env'],'named_subset'),
        ready('deployment', 'api-server')
    ], docs=['secret', 'deployment'], minutes=6,
    hints=['Inspect spec.template.spec.containers before creating the Secret.', 'Each env entry needs valueFrom.secretKeyRef.name and key; it must not retain value.'],
    explanation='The application keeps the same environment interface while the values move into a namespaced Secret. A Pod-template change triggers a rollout; the Secret itself does not restart existing containers.'))

    cron = obj('CronJob', 'backup-job', {'schedule': '*/30 * * * *', 'successfulJobsHistoryLimit': 3, 'failedJobsHistoryLimit': 2,
        'jobTemplate': {'spec': {'activeDeadlineSeconds': 300, 'template': {'spec': {'restartPolicy': 'Never',
        'containers': [container('backup', 'busybox:latest', ['/bin/sh', '-c'], args=['echo Backup completed'])]}}}}}, api='batch/v1')
    out.append(scenario(2, 'Create a CronJob with schedule and history limits', 'design', [
        'Create CronJob `backup-job` with schedule `*/30 * * * *`, retaining three successful and two failed Jobs.',
        'Its container `backup` must use `busybox:latest` and run `echo Backup completed`. Use Pod restart policy `Never`.',
        'Give each Job created from the CronJob an active deadline of 300 seconds. A manual test Job is optional.'
    ], (
        'Separate scheduling from execution. The CronJob owns the schedule and history limits, while its jobTemplate describes each Job that will be created at a scheduled time.',
        'Place activeDeadlineSeconds under spec.jobTemplate.spec. The container and restartPolicy belong deeper, under the Job template’s Pod spec. Quote the schedule so YAML treats it as a string.',
        'Optionally create Job backup-job-test from the CronJob to test the template immediately. It is not needed to complete this question.',
        'Putting activeDeadlineSeconds on the CronJob spec is the wrong nesting. A container that sleeps forever never satisfies the successful-completion requirement.',
        'kubectl get cronjob backup-job -o yaml\nkubectl describe cronjob backup-job',
        'The CronJob has the half-hour schedule, history settings, backup command, and a 300-second Job deadline.'
    ), final=[cron], checks=[
        resource('Schedule and history limits', 'cronjob', 'backup-job', {k: cron['spec'][k] for k in ('schedule','successfulJobsHistoryLimit','failedJobsHistoryLimit')}, ['spec']),
        resource('Job deadline and restart policy', 'cronjob', 'backup-job', {'activeDeadlineSeconds':300,'template':{'spec':{'restartPolicy':'Never'}}}, ['spec','jobTemplate','spec']),
        resource('Backup container uses the requested image', 'cronjob', 'backup-job', 'busybox:latest', ['spec','jobTemplate','spec','template','spec','containers',{'name':'backup'},'image'],'equals'),
        resource('Backup command prints the requested message', 'cronjob', 'backup-job', 'Backup completed', ['spec','jobTemplate','spec','template','spec','containers',{'name':'backup'}],'echo_command')],
    docs=['cronjob', 'job'], minutes=7, explanation='History limits belong to the CronJob, the active deadline belongs to its Job template, and restartPolicy belongs to the nested Pod template.'))

    reader = api_reader('log-collector')
    account = obj('ServiceAccount', 'log-sa')
    rules = role('log-role')
    bound = binding('log-rb', 'log-role', 'log-sa', 'ckad-s03')
    fixed = api_reader('log-collector', 'log-sa')
    out.append(scenario(3, 'Diagnose a denied API request and grant read access', 'configuration', [
        'Pod `log-collector` repeatedly makes a real Kubernetes API request. Read container `reader` logs to identify the denied resource and namespace.',
        'Create ServiceAccount `log-sa`, Role `log-role`, and RoleBinding `log-rb`. Grant only get/list/watch on core Pods in this question’s namespace.',
        'Recreate the Pod with the new ServiceAccount, preserving its image, command, and environment. The request must return HTTP 200; do not grant Secret access or permission to create/delete Pods.'
    ], (
        'Use the reader container’s logs to distinguish HTTP 403 authorization failure from DNS or certificate failure. The fixture actually contacts the API and validates its TLS certificate; it does not print a fabricated success.',
        'Create a namespaced ServiceAccount, a Role for the empty core API group and pods resource, and a binding whose subject names that account in this namespace. Do not use a cluster-wide binding.',
        'ServiceAccount selection is immutable on an existing Pod. Recreate only log-collector with its unchanged application definition and the new identity, then inspect its latest request result and effective permissions.',
        'Creating the Role does nothing until a RoleBinding associates it with the identity actually used by the Pod. Editing the default ServiceAccount is not the requested repair.',
        'kubectl logs log-collector -c reader --tail=5\nkubectl exec log-collector -c reader -- cat /tmp/access-status\nkubectl auth can-i list pods --as=system:serviceaccount:ckad-s03:log-sa\nkubectl auth can-i get secrets --as=system:serviceaccount:ckad-s03:log-sa',
        'The running reader records 200, Pod read checks answer yes, and Secret access answers no. The intentional denied check exits nonzero.'
    ), seeds=[reader], final=[account, rules, bound, fixed],
    solution=apply_script([account, rules, bound], 'ckad-s03', '/workspace/s03/access.yaml')+'kubectl delete pod log-collector --wait=true\n'+apply_script([fixed], 'ckad-s03', '/workspace/s03/reader.yaml'),
    checks=[resource('Reader uses the requested identity and unchanged workload', 'pod', 'log-collector', fixed['spec'], ['spec']),
        check('Role grants exactly Pod read permissions', 'rbac_rules', name='log-role', rules=rules['rules']),
        resource('Binding targets the requested account', 'rolebinding', 'log-rb', {'subjects': bound['subjects'], 'roleRef': bound['roleRef']}),
        *[check(f'Identity can {verb} Pods', 'auth', sa='log-sa', verb=verb, resource='pods', allowed=True) for verb in ('get', 'list', 'watch')],
        *[check(f'Identity cannot {verb} {res}', 'auth', sa='log-sa', verb=verb, resource=res, allowed=False) for verb,res in [('get','secrets'),('create','pods'),('delete','pods')]],
        exec_check('Application request is authorized', 'log-collector', ['cat','/tmp/access-status'], '200', 'reader'), ready('pod','log-collector')],
    docs=['rbac','sa'], minutes=10, level='Advanced',
    hints=['An HTTP 403 means the API received the request but denied its identity.', 'Export the Pod before recreating it. Change serviceAccountName, not its application code.'],
    explanation='Authentication identifies the ServiceAccount; a namespaced RoleBinding authorizes its operations. This exercise checks both RBAC grants and the application’s real API response.'))

    accounts = [obj('ServiceAccount', name) for name in ('monitor-sa', 'wrong-sa', 'admin-sa')]
    narrow = role('metrics-reader')
    broad = role('full-access', ('get','list','watch','create','delete'), ('pods','secrets'))
    view = role('view-only', ('get',))
    bindings = [binding('monitor-binding','metrics-reader','monitor-sa','ckad-s04'), binding('admin-binding','full-access','admin-sa','ckad-s04')]
    old = api_reader('metrics-pod','wrong-sa')
    fixed = api_reader('metrics-pod','monitor-sa')
    out.append(scenario(4, 'Fix a Pod using the wrong ServiceAccount', 'configuration', [
        'Pod `metrics-pod` is using ServiceAccount `wrong-sa` and cannot list Pods. Inspect its logs and the existing ServiceAccounts `monitor-sa`, `wrong-sa`, and `admin-sa`.',
        'Trace Roles `metrics-reader`, `full-access`, and `view-only` through RoleBindings `monitor-binding` and `admin-binding` to find the account authorized to read Pods.',
        'Recreate `metrics-pod` with that existing ServiceAccount and confirm the authorization failure stops. Keep its application definition intact.'
    ], (
        'Trace each existing RoleBinding from its subject to its roleRef, then read the referenced Role. A name suggesting administrative access is not a reason to choose it; compare actual grants with the workload’s needs.',
        'Use impersonated can-i checks to confirm the narrow identity can list Pods but cannot read Secrets or delete Pods. The broad identity is a deliberate distractor and is not the least-privilege solution.',
        'Recreate the Pod with the selected ServiceAccount because that field cannot be patched in place. Preserve the actual API client so a changed success message cannot substitute for a working request.',
        'Do not repair the unused identity by adding a new binding. The task is to select an already configured account without changing authorization policy.',
        'kubectl get rolebindings -o yaml\nkubectl get roles -o yaml\nkubectl logs metrics-pod -c reader --tail=5\nkubectl exec metrics-pod -c reader -- cat /tmp/access-status',
        'metrics-pod uses monitor-sa, returns HTTP 200, and the existing RBAC grants stay intact.'
    ), seeds=[*accounts,narrow,broad,view,*bindings,old], final=[fixed],
    solution='kubectl get roles,rolebindings,serviceaccounts\nkubectl delete pod metrics-pod --wait=true\n'+apply_script([fixed],'ckad-s04','/workspace/s04/observer.yaml'),
    checks=[resource('Observer selects the narrow account', 'pod','metrics-pod',fixed['spec'],['spec']),
        check('Only the supplied Roles exist','inventory',resource='roles',names=['metrics-reader','full-access','view-only']),
        check('Only the supplied RoleBindings exist','inventory',resource='rolebindings',names=['monitor-binding','admin-binding']),
        check('ServiceAccounts are preserved','inventory',resource='serviceaccounts',names=['default','monitor-sa','wrong-sa','admin-sa']),
        *[resource(f'Role {r["metadata"]["name"]} is unchanged','role',r['metadata']['name'],r['rules'],['rules'],'equals') for r in (narrow,broad,view)],
        *[resource(f'Binding {b["metadata"]["name"]} is unchanged','rolebinding',b['metadata']['name'],{'subjects':b['subjects'],'roleRef':b['roleRef']}) for b in bindings],
        check('Narrow identity can list Pods','auth',sa='monitor-sa',verb='list',resource='pods',allowed=True),
        check('Narrow identity cannot read Secrets','auth',sa='monitor-sa',verb='get',resource='secrets',allowed=False),
        check('Narrow identity cannot delete Pods','auth',sa='monitor-sa',verb='delete',resource='pods',allowed=False),
        exec_check('Observer API request succeeds','metrics-pod',['cat','/tmp/access-status'],'200','reader'), ready('pod','metrics-pod')],
    docs=['sa','rbac'], minutes=8, explanation='Selecting an identity and creating permissions are different tasks. Existing grants stay intact; only the Pod’s selected ServiceAccount changes.'))

    dockerfile=f'FROM {NGINX}\nCOPY index.html /usr/share/nginx/html/index.html\n'
    out.append(scenario(5, 'Build an image and save it as a tarball', 'design', [
        'A valid Dockerfile is supplied in `/workspace/s05/app-source`. Build that directory as image `my-app:1.0` with the available Docker alternative to Podman.',
        'Save the image and its layers to `/workspace/s05/my-app.tar` using `docker image save`, not a container filesystem export.'
    ], (
        'Inspect the supplied Dockerfile and page, then choose the source directory as build context. COPY can only access files inside that context; your current shell directory alone does not determine it.',
        'Build the exact requested image tag with Docker. This lab uses the source scenario’s Docker alternative rather than a Podman alias; the isolated builder is a real separate image store.',
        'Use docker image save for the archive, then inspect its manifest and the built image ID. A nonempty tar file alone does not prove it contains the requested tag, metadata, and layers.',
        'docker export is not interchangeable with docker save. Building the image in this Docker daemon does not automatically make it available to Kubernetes containerd.',
        'docker image inspect my-app:1.0 --format \'{{.Id}}\'\ndocker run --rm --network none --entrypoint cat my-app:1.0 /usr/share/nginx/html/index.html\ntar -tf /workspace/s05/my-app.tar',
        'The built my-app:1.0 image exists, and its tarball contains that tag, its metadata, and its layers.'
    ), files={'app-source/Dockerfile':dockerfile,'app-source/index.html':'<h1>FOCUSED LAB READY</h1>\n'},
    solution='docker build -t my-app:1.0 /workspace/s05/app-source\ndocker image save -o /workspace/s05/my-app.tar my-app:1.0\n',
    checks=[check('Built image has the requested tag','image',image='my-app:1.0',path=['Id'],expected=True,op='nonempty'),
        check('Built image uses the supplied Dockerfile base','image_base',image='my-app:1.0',base=NGINX),
        check('Archive contains the built image and tag','image_archive',path='/workspace/s05/my-app.tar',tag='my-app:1.0')],
    docs=['docker','save'], minutes=7, explanation='This is a build-and-save exercise against the real isolated Docker daemon. Both the built image and exported archive are inspected.'))

    stable=deployment('web-app',5,labels={'app':'webapp','version':'v1'})
    canary=deployment('web-app-canary',2,'nginx:latest',labels={'app':'webapp','version':'v2'})
    scaled=deepcopy(stable); scaled['spec']['replicas']=8
    svc=service('web-service',{'app':'webapp'})
    out.append(scenario(6, 'Create a canary Deployment with an 8:2 split', 'deployment', [
        'Deployment `web-app` starts with five replicas and labels `app=webapp,version=v1`. Service `web-service` selects `app=webapp`.',
        'Scale `web-app` to eight replicas and create Deployment `web-app-canary` with two replicas, labels `app=webapp,version=v2`, and a working web container.',
        'Both Deployments must be selected by the same unchanged Service. Inspect its endpoints to confirm eight stable and two canary backends.'
    ], (
        'Keep separate selectors for version=v1 and version=v2 but share app=webapp, which the Service selects. Scaling the original Deployment does not change its Pod template.',
        'Give the canary a working web image and the version=v2 label. Leave the Service selector on app=webapp so both versions join the endpoint pool.',
        'Wait for both rollouts and inspect EndpointSlices. Ten healthy addresses establish the requested 8:2 backend composition, while separate workload checks confirm which image belongs to each track.',
        'An 8:2 endpoint ratio is not a guaranteed 80/20 request distribution. Connection reuse, session affinity, and readiness can change the observed distribution.',
        'kubectl rollout status deployment/web-app --timeout=180s\nkubectl rollout status deployment/web-app-canary --timeout=180s\nkubectl get pods -l app=webapp --show-labels\nkubectl get endpointslices -l kubernetes.io/service-name=web-service -o yaml',
        'Both controllers are healthy, the stable template is unchanged, and ten ready endpoints cover the eight stable and two canary Pods.'
    ), seeds=[stable,svc], final=[scaled,canary], checks=[
        resource('Stable has eight original-template replicas','deployment','web-app',scaled['spec'],['spec']),
        resource('Canary has two version-v2 replicas','deployment','web-app-canary',{'replicas':2,'selector':canary['spec']['selector'],'template':{'metadata':canary['spec']['template']['metadata']}},['spec']),
        resource('Shared Service remains unchanged','service','web-service',svc['spec'],['spec']),
        ready('deployment','web-app'),ready('deployment','web-app-canary'),check('Ten healthy backends','endpoints',name='web-service',count=10),check('Every stable and canary backend serves HTTP','http_endpoints',source='deployment/web-app',name='web-service',count=10,port=80)],
    docs=['deployment','service'], minutes=9, explanation='Replica-based canaries use a shared Service over separately controlled versions. The grader checks endpoint composition rather than a statistically unreliable sample of HTTP requests.'))

    frontend=sleeper('frontend',{'role':'wrong-frontend'})
    backend=http_pod('backend',{'role':'wrong-backend'},'BACKEND READY')
    database=http_pod('database',{'role':'wrong-db'},'DATABASE READY')
    deny=obj('NetworkPolicy','deny-all',{'podSelector':{},'policyTypes':['Ingress'],'ingress':[]},api='networking.k8s.io/v1')
    def allow(name,target,source):
        return obj('NetworkPolicy',name,{'podSelector':{'matchLabels':{'role':target}},'policyTypes':['Ingress'],
            'ingress':[{'from':[{'podSelector':{'matchLabels':{'role':source}}}],'ports':[{'port':8080,'protocol':'TCP'}]}]},api='networking.k8s.io/v1')
    policies=[deny,allow('allow-frontend-to-backend','backend','frontend'),allow('allow-backend-to-db','db','backend')]
    out.append(scenario(7, 'Fix NetworkPolicy connectivity by relabeling Pods', 'networking', [
        'Pods `frontend`, `backend`, and `database` currently have labels `role=wrong-frontend`, `role=wrong-backend`, and `role=wrong-db`.',
        'The existing policies `deny-all`, `allow-frontend-to-backend`, and `allow-backend-to-db` select `role=frontend`, `role=backend`, and `role=db`.',
        'Change only the Pod labels. Do not edit NetworkPolicies. Restore the frontend → backend → database communication chain.'
    ], (
        'Read each policy’s target selector and permitted source selector before changing anything. Deny-all continues to isolate Pods that do not match an allow rule.',
        'Use kubectl label --overwrite to set role=frontend, role=backend, and role=db on the three Pods. Keep their definitions and existing policy objects intact.',
        'Test both permitted links using Pod IPs, then confirm the frontend cannot bypass the backend and contact the database directly.',
        'Changing NetworkPolicies instead of labels dodges the task. An added allow-all policy would also defeat the intended isolation.',
        'kubectl get pods --show-labels\nkubectl get networkpolicies -o yaml\nBACKEND_IP=$(kubectl get pod backend -o jsonpath=\'{.status.podIP}\')\nDATABASE_IP=$(kubectl get pod database -o jsonpath=\'{.status.podIP}\')\nkubectl exec frontend -- wget -T 3 -q -O- "http://$BACKEND_IP:8080"\nkubectl exec backend -- wget -T 3 -q -O- "http://$DATABASE_IP:8080"\nkubectl exec frontend -- wget -T 3 -q -O- "http://$DATABASE_IP:8080"',
        'Both adjacent connections succeed; a direct frontend-to-database request remains blocked.'
    ), seeds=[frontend,backend,database,*policies],
    solution='kubectl label pod frontend role=frontend --overwrite\nkubectl label pod backend role=backend --overwrite\nkubectl label pod database role=db --overwrite\n',
    checks=[*[resource(f'{name} has its required role','pod',name,label,['metadata','labels','role'],'equals') for name,label in [('frontend','frontend'),('backend','backend'),('database','db')]],
        *[resource(f'Policy {p["metadata"]["name"]} is unchanged','networkpolicy',p['metadata']['name'],p['spec'],['spec'],'equals') for p in policies],
        *[resource(f'Pod {p["metadata"]["name"]} keeps its workload','pod',p['metadata']['name'],p['spec'],['spec']) for p in (frontend,backend,database)],
        check('No additional NetworkPolicies exist','inventory',resource='networkpolicies',names=[p['metadata']['name'] for p in policies]),
        traffic('Frontend reaches backend','frontend','backend'),traffic('Backend reaches database','backend','database'),
        traffic('Frontend cannot bypass backend','frontend','database',False)],
    docs=['networkpolicy'], minutes=10, level='Advanced', explanation='Selectors connect policy intent to the actual Pods. This task changes labels rather than policy definitions and tests both positive and negative paths.'))

    fixed=deployment('broken-app',2,labels={'app':'myapp'})
    broken=deepcopy(fixed); broken['apiVersion']='extensions/v1beta1'; broken['spec'].pop('selector')
    path='/workspace/s08/broken-deploy.yaml'
    out.append(scenario(8, 'Repair a broken Deployment manifest', 'deployment', [
        'The supplied `/workspace/s08/broken-deploy.yaml` defines Deployment `broken-app` using a removed API and no required selector.',
        'Edit that file to use `apps/v1` and `spec.selector.matchLabels.app: myapp`, matching its Pod-template labels. Keep the existing Deployment name and workload.',
        'Apply the repaired file and finish with a complete rollout. A separate corrected file is not a substitute for repairing the supplied one.'
    ], (
        'Inspect the saved file and compare its structure with the stable Deployment schema. A removed API version can hide additional schema problems until the API group is corrected.',
        'Set apps/v1 and add spec.selector.matchLabels matching the template metadata labels. Keep all application settings the question asks you to preserve, including the container identity and replicas.',
        'Apply the same file you edited and wait for the rollout. The grader checks the saved YAML and live Deployment so an unrelated manually created workload cannot replace the required repair.',
        'Changing only apiVersion leaves a missing selector. Deployment metadata labels alone do not satisfy the selector-to-Pod-template relationship.',
        'kubectl apply --dry-run=server -f /workspace/s08/broken-deploy.yaml\nkubectl rollout status deployment/broken-app --timeout=180s\nkubectl get deployment broken-app -o yaml',
        'The supplied file validates as apps/v1 and produces two available replicas with the requested selector and template.'
    ), files={'broken-deploy.yaml':yaml.safe_dump(broken,sort_keys=False)},final=[fixed],
    solution=apply_script([fixed],'ckad-s08',path)+'kubectl rollout status deployment/broken-app --timeout=180s\n',
    checks=[check('Required file contains the repaired Deployment','yaml_file',path=path,expected=scoped([fixed],'ckad-s08'),ignore_namespace=True),
        resource('Live Deployment retains the required settings','deployment','broken-app',fixed['spec'],['spec']),ready('deployment','broken-app')],
    docs=['deprecation','deployment'],minutes=7,explanation='API migration can require schema changes as well as a new apiVersion. Both the saved artifact and its running result matter.'))

    original=deployment('app-v1',2,'nginx:1.20')
    out.append(scenario(9, 'Perform a rolling update and rollback', 'deployment', [
        'Deployment `app-v1` initially uses image `nginx:1.20` in its `web` container.',
        'Update it to `nginx:1.25` and verify the rolling update completes. Roll back to the previous revision and verify the rollback.',
        'Preserve the Deployment and its revision history. Finish with two healthy original-image replicas and history containing both image versions. Do not delete and recreate the Deployment.'
    ], (
        'Wait for the initial healthy revision before updating the Pod template. The provided setup establishes this baseline so a previous revision exists for the rollback.',
        'Use kubectl set image to update web, then wait for rollout status before undoing the change. The controller creates a ReplicaSet for the new template and retains history when you return to the old one.',
        'Inspect the final image, availability, and owned ReplicaSets. The grader requires both image templates and a later Deployment revision, so doing nothing to an initially healthy workload cannot pass.',
        'Final-state checks cannot prove that every intermediate Pod became available at a particular time. Follow the requested waits; the grader checks retained history and final health, not your exact shell sequence.',
        'kubectl rollout history deployment/app-v1\nkubectl get replicasets -l app=app-v1 -o wide\nkubectl rollout status deployment/app-v1 --timeout=180s',
        'The final image is the original tag, both versions appear in owned history, and the Deployment revision is at least three.'
    ), seeds=[original], setup=[{'command':['kubectl','-n','ckad-s09','rollout','status','deployment/app-v1','--timeout=180s'],'timeout':190}],
    solution='kubectl set image deployment/app-v1 web=nginx:1.25\nkubectl rollout status deployment/app-v1 --timeout=180s\nkubectl rollout undo deployment/app-v1\nkubectl rollout status deployment/app-v1 --timeout=180s\n',
    checks=[resource('Original image and replicas restored','deployment','app-v1',original['spec'],['spec']),
        check('Owned revision history contains update and rollback','rollout_history',name='app-v1',container='web',images=['nginx:1.20','nginx:1.25'],min_revision=3),ready('deployment','app-v1')],
    docs=['deployment'],minutes=9,explanation='A rollback is another controller revision, not deletion of history. The untouched initial state is deliberately insufficient for this task.'))

    web=container('api',BUSYBOX,['sh','-c',"mkdir -p /www; printf 'ready-now\\n' > /www/ready; exec httpd -f -p 8080 -h /www"],ports=[{'containerPort':8080}])
    old=deployment('api-deploy',2,containers=[web]); final=deepcopy(old)
    final['spec']['template']['spec']['containers'][0]['readinessProbe']=probe(8080,'/ready',initialDelaySeconds=5,periodSeconds=10)
    out.append(scenario(10, 'Add a readiness check to a real health endpoint', 'observability', [
        'Deployment `api-deploy` has two replicas. Its `api` container already serves HTTP `/ready` on port 8080.',
        'Add an HTTP readiness probe using that path and port, with initial delay 5 seconds and period 10 seconds.',
        'Keep the existing image, command, labels, and replica count. Finish with both updated replicas Ready.'
    ], (
        'Inspect the existing container before editing. The fixture actually listens on 8080 and serves /ready, so the probe must describe the existing application rather than an imaginary nginx endpoint.',
        'Add readinessProbe to the api container inside spec.template.spec.containers. Keep the HTTP request, initial delay, and period together in the probe definition without changing the application command.',
        'Wait for the new Pods to satisfy readiness and for the Deployment rollout to finish. Readiness controls traffic eligibility; it is not a command to restart a failing process.',
        'A containerPort declaration does not make a process listen on that port. Placing the probe at Pod or Deployment level instead of container level is also incorrect.',
        'kubectl rollout status deployment/api-deploy --timeout=180s\nkubectl get deployment api-deploy -o yaml\nkubectl get pods -l app=api-deploy',
        'The stored readiness probe matches the requested HTTP endpoint and timing, and both replicas are available.'
    ), seeds=[old],final=[final],checks=[resource('HTTP readiness probe matches the endpoint','deployment','api-deploy',probe(8080,'/ready',initialDelaySeconds=5,periodSeconds=10),D('api')+['readinessProbe']),
        resource('Application template and replicas are preserved','deployment','api-deploy',old['spec'],['spec']),ready('deployment','api-deploy')],
    docs=['probes','deployment'],minutes=6,explanation='A readiness probe must target a real application listener. The fixture serves the requested endpoint instead of relying on a container-port declaration.'))

    old=deployment('secure-app',1,containers=[container('app',BUSYBOX,['sh','-c','id -u; sleep 86400'])])
    final=deepcopy(old); final['spec']['template']['spec']['securityContext']={'runAsUser':1000}
    final['spec']['template']['spec']['containers'][0]['securityContext']={'capabilities':{'add':['NET_ADMIN']}}
    out.append(scenario(11, 'Configure Pod and container security contexts', 'configuration', [
        'Deployment `secure-app` has a container named `app` and no security context.',
        'Set Pod-level `runAsUser: 1000`, and add capability `NET_ADMIN` to the `app` container—not the Pod.',
        'Apply the change and verify the rollout. The fixture uses a working non-root BusyBox process because this lab needs the Deployment to run.'
    ], (
        'Locate both security-context levels in the Deployment template. Pod-level settings establish defaults for the containers, while Linux capabilities are configured on a particular container.',
        'Set the Pod-level UID and add NET_ADMIN under the app container’s capabilities.add list. Keep the existing long-running command; it prints the actual startup UID before sleeping.',
        'Wait for replacement Pods and inspect both the template and current logs. Checking the logged UID helps distinguish the requested runtime identity from a manifest that merely looks correct.',
        'A container-level runAsUser can override the Pod default. NET_ADMIN grants additional authority; add it only because this isolated task explicitly asks for it.',
        'kubectl rollout status deployment/secure-app --timeout=180s\nkubectl logs deployment/secure-app -c app\nkubectl get deployment secure-app -o yaml',
        'The single replica is available, its log reports 1000, and the capability is configured at container level.'
    ), seeds=[old],final=[final],checks=[resource('UID is configured on the Pod template','deployment','secure-app',1000,['spec','template','spec','securityContext','runAsUser'],'equals'),
        resource('Requested container capability is present','deployment','secure-app','NET_ADMIN',D('app')+['securityContext','capabilities','add'],'contains'),
        ready('deployment','secure-app')],
    docs=['security'],minutes=6,explanation='Pod securityContext and container securityContext are related but distinct. A BusyBox process that supports a non-root UID avoids the unrelated filesystem restrictions of a default nginx image.'))

    dep=http_deployment('web-app',2,{'app':'webapp','tier':'frontend'},'WEB APP READY')
    old=service('web-svc',{'app':'wrongapp'},80,8080)
    final=service('web-svc',{'app':'webapp'},80,8080)
    out.append(scenario(12, 'Fix a Service selector', 'networking', [
        'Deployment `web-app` has Pods labeled `app=webapp,tier=frontend`. Service `web-svc` incorrectly selects `app=wrongapp`.',
        'Update only Service `web-svc` to select the Deployment’s Pods with `app=webapp`.',
        'Verify the Service has ready endpoints. The lab provides a client Pod if you want to check actual routing.'
    ], (
        'Compare the Service selector with the labels on running Pods. A Service routes by labels, not by its name or the name of a Deployment.',
        'Correct only the Service selector and preserve the port mapping. The controller will publish backend addresses when matching Pods are Ready; do not relabel the workload to accommodate the broken selector.',
        'Inspect EndpointSlices and request the Service from the provided client Pod. This verifies selection, backend readiness, and real routing rather than only the existence of a Service object.',
        'Labels on a Deployment’s metadata are not necessarily labels on its Pods. Always inspect the Pod template or the running Pods when debugging selectors.',
        'kubectl get pods -l app=webapp --show-labels\nkubectl get endpointslices -l kubernetes.io/service-name=web-svc -o yaml\nkubectl exec client -- wget -q -O- http://web-svc',
        'Two ready endpoints back web-svc and a client request returns WEB APP READY.'
    ), seeds=[dep,old,sleeper('client')],final=[final],checks=[resource('Service selector is repaired','service','web-svc',{'selector':{'app':'webapp'}},['spec']),
        resource('Deployment keeps its original Pod labels','deployment','web-app',dep['spec'],['spec']),check('Service has two ready backends','endpoints',name='web-svc',count=2),
        check('Service routes to the existing Pods','http',source='client',url='http://web-svc',expected='WEB APP READY')],
    docs=['service','debug'],minutes=5,explanation='Service routing follows selected, ready Pods. Correcting the selector fixes the relationship without changing the application.'))

    dep=deployment('api-server',2,containers=[http_container('API READY',9090)],labels={'app':'api'})
    svc=service('api-nodeport',{'app':'api'},80,9090,type='NodePort')
    out.append(scenario(13, 'Create a NodePort Service', 'networking', [
        'Deployment `api-server` has Pods labeled `app=api` listening on container port 9090.',
        'Create Service `api-nodeport` of type NodePort, selecting `app=api`, with port 80 and targetPort 9090.',
        'Inspect the assigned node port. The lab nodes should reach the existing API through that port.'
    ], (
        'Keep Service port 80 separate from targetPort 9090. Kubernetes chooses a nodePort if you do not request a particular one.',
        'Create Service api-nodeport with selector app=api. Do not change the existing Deployment to compensate for an incorrect selector or target port.',
        'Read the assigned nodePort from the Service, then send HTTP requests to both lab nodes at that port to check live forwarding.',
        'There is no required fixed nodePort in this question. Hard-coding one risks colliding with another lab.',
        'kubectl get service api-nodeport -o yaml\nNODE_PORT=$(kubectl get service api-nodeport -o jsonpath=\'{.spec.ports[0].nodePort}\')\ncurl --max-time 10 "http://cluster:$NODE_PORT"\ncurl --max-time 10 "http://worker:$NODE_PORT"',
        'The Service selects ready API Pods and its allocated NodePort routes requests to port 9090 on both nodes.'
    ), seeds=[dep],final=[svc],checks=[resource('NodePort selector and port mapping','service','api-nodeport',{'type':'NodePort','selector':{'app':'api'},'ports':[{'port':80,'targetPort':9090,'protocol':'TCP'}]},['spec']),
        resource('Application is unchanged','deployment','api-server',dep['spec'],['spec']),
        check('Control node forwards traffic on the assigned port','http_nodeport',service='api-nodeport',host='cluster',expected='API READY'),
        check('Worker node forwards traffic on the assigned port','http_nodeport',service='api-nodeport',host='worker',expected='API READY')],
    docs=['service'],minutes=6,explanation='NodePort exposes a selected backend pool through each lab node. Explicitly separate the three port fields and verify both paths.'))

    dep=http_deployment('web-deploy',2,labels={'app':'web'},body='WEB READY'); svc=service('web-svc',{'app':'web'},8080,8080)
    ing=ingress('web-ingress','web.example.com','web-svc',8080)
    out.append(scenario(14, 'Create an Ingress resource', 'networking', [
        'Deployment `web-deploy` and Service `web-svc` are provided; the Service selects `app=web` and exposes port 8080.',
        'Create Ingress `web-ingress` using `networking.k8s.io/v1`, with host `web.example.com`, Prefix path `/`, and backend `web-svc:8080`.',
        'Verify the Ingress is accepted and routes a request carrying that Host header to the existing application.'
    ], (
        'Check the provided Service port first. An Ingress backend points to a Service port, not directly to a container port.',
        'Set the host, Prefix path, and nested backend.service fields. The installed Traefik controller accepts an explicit ingressClassName if needed.',
        'Use a Host header when sending a request to the lab control node; no external DNS or hosts-file edits are necessary.',
        'A syntactically valid Ingress does not prove that the controller can reach the selected Service. Test the routed response.',
        'kubectl get ingress web-ingress -o yaml\ncurl --max-time 10 -H "Host: web.example.com" http://cluster/',
        'web.example.com with path / routes through web-svc to the running web application.'
    ), seeds=[dep,svc],final=[ing],checks=[resource('Ingress host, path, and backend','ingress','web-ingress',{'rules':ing['spec']['rules']},['spec']),
        resource('Backend Service is preserved','service','web-svc',svc['spec'],['spec']),
        resource('Backend Deployment is preserved','deployment','web-deploy',dep['spec'],['spec']),
        check('Real Ingress route succeeds','http_external',url='http://cluster/',host='web.example.com',expected='WEB READY')],
    docs=['ingress','service'],minutes=7,explanation='The lab’s Traefik controller turns the Ingress configuration into real hostname routing. The test uses a Host header rather than external DNS.'))

    route_web=container('web',BUSYBOX,['sh','-c',"mkdir -p /www; printf 'API ROUTE READY\\n' > /www/api; exec httpd -f -p 8080 -h /www"],ports=[{'containerPort':8080}])
    dep=deployment('api-svc',2,labels={'app':'api'},containers=[route_web]); svc=service('api-svc',{'app':'api'},8080,8080)
    ing=ingress('api-ingress',None,'api-svc',8080,'/api')
    broken=deepcopy(ing); broken['spec']['rules'][0]['http']['paths'][0]['pathType']='InvalidType'
    partial=deepcopy(ing); partial['spec'].pop('ingressClassName'); partial['spec']['rules'][0]['http']['paths'][0].pop('pathType')
    path='/workspace/s15/fix-ingress.yaml'
    valid_types=['Prefix','Exact','ImplementationSpecific']
    out.append(scenario(15, 'Fix an invalid Ingress path type', 'networking', [
        'The file `/workspace/s15/fix-ingress.yaml` contains Ingress `api-ingress` with an invalid pathType. Try applying it to observe the API error.',
        'Replace the pathType with a valid value: `Prefix`, `Exact`, or `ImplementationSpecific`. Route `/api` to Service `api-svc` on port 8080.',
        'Apply the corrected file and verify requests to `/api` reach the provided application.'
    ], (
        'Apply or dry-run the supplied manifest and inspect the rejected pathType. The API requires a supported enum value.',
        'Choose any of the three valid path types that routes /api through the installed controller. Keep the backend Service name and port unchanged.',
        'Edit the original answer file, apply it, and check the live Ingress. The fixture serves an exact /api file so Exact and Prefix can both work.',
        'Fixing only a different YAML file does not repair the supplied artifact. A valid API object with the wrong backend also misses the objective.',
        'kubectl apply --dry-run=server -f /workspace/s15/fix-ingress.yaml\nkubectl get ingress api-ingress -o yaml\ncurl --max-time 10 http://cluster/api',
        'The saved and live Ingress use a supported pathType and route /api to api-svc:8080.'
    ), seeds=[dep,svc],files={'fix-ingress.yaml':yaml.safe_dump(scoped([broken],'ckad-s15')[0],sort_keys=False)},final=[ing],
    solution=apply_script([ing],'ckad-s15',path), checks=[
        check('Supplied file repairs the Ingress path','yaml_file',path=path,expected=scoped([partial],'ckad-s15'),ignore_namespace=True,allowed_path_types=valid_types),
        resource('Live Ingress routes the requested backend','ingress','api-ingress',partial['spec'],['spec']),
        resource('Live pathType is valid','ingress','api-ingress',valid_types,['spec','rules',0,'http','paths',0,'pathType'],'one_of'),
        check('Route /api reaches the application','http_external',url='http://cluster/api',expected='API ROUTE READY')],
    docs=['ingress'],minutes=7,explanation='A supported pathType is required by the API. The grader accepts any of the three documented values when the saved file, live Ingress, and /api route all work.'))

    quota=obj('ResourceQuota','compute-budget',{'hard':{'limits.cpu':'2','limits.memory':'4Gi','pods':'4'}})
    p=pod('resource-pod',[container(image='nginx:latest',resources={'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'1','memory':'2Gi'}})])
    out.append(scenario(16, 'Create a Pod sized from ResourceQuota', 'configuration', [
        'Inspect the existing ResourceQuota in this question’s namespace to discover its CPU and memory limits.',
        'Create Pod `resource-pod` with image `nginx:latest`, setting CPU and memory limits to half of the corresponding quota values.',
        'Set CPU request to at least 100m and memory request to at least 128Mi. Keep the Pod within its limits and ensure it starts.'
    ], (
        'Read the quota’s hard limits before constructing the Pod. Quota limits describe aggregate namespace usage, so calculate the requested per-container share rather than copying the full budget.',
        'The supplied quota permits 2 CPU and 4Gi memory, so half is 1 CPU and 2Gi. Put those in container limits; use requests no smaller than 100m and 128Mi.',
        'Inspect the admitted Pod and quota usage, then wait for readiness. A configuration can satisfy the arithmetic yet remain Pending if its requests cannot fit on a node.',
        'CPU millicores and binary memory units use different arithmetic. Do not halve the requests instead of the limits or raise the quota to make an oversized Pod pass.',
        'kubectl describe resourcequota compute-budget\nkubectl get pod resource-pod -o yaml\nkubectl wait --for=condition=Ready pod/resource-pod --timeout=120s',
        'resource-pod runs nginx:latest with 1 CPU/2Gi limits and requests of at least 100m/128Mi.'
    ), seeds=[quota],final=[p],checks=[resource('Quota remains unchanged','resourcequota','compute-budget',quota['spec'],['spec']),
        resource('Pod uses the requested image','pod','resource-pod','nginx:latest',['image'],'equals',items_path=['spec','containers']),
        *[resource(f'Limit {key} is half the namespace budget','pod','resource-pod',value,['resources','limits',key],'quantity',items_path=['spec','containers']) for key,value in p['spec']['containers'][0]['resources']['limits'].items()],
        *[resource(f'Request {key} meets its minimum','pod','resource-pod',value,['resources','requests',key],'at_least_quantity',items_path=['spec','containers']) for key,value in p['spec']['containers'][0]['resources']['requests'].items()],ready('pod','resource-pod')],
    docs=['quota','resources'],minutes=7,explanation='ResourceQuota constrains aggregate namespace consumption, while a container’s requests and limits describe its own scheduling and runtime budget. Equivalent quantity representations are accepted.'))
    return out
