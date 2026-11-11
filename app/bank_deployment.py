from bank_helpers import *

def chart_files():
    return {
      'chart/Chart.yaml': 'apiVersion: v2\nname: practice-web\ndescription: A small local CKAD practice chart\ntype: application\nversion: 0.1.0\nappVersion: "1.27.5"\n',
      'chart/values.yaml': f'replicaCount: 1\nimage:\n  repository: nginx\n  tag: "1.27.5-alpine"\nservice:\n  port: 80\n',
      'chart/templates/deployment.yaml': '''apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  labels:
    app.kubernetes.io/instance: {{ .Release.Name }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/instance: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/instance: {{ .Release.Name }}
    spec:
      containers:
        - name: web
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          ports:
            - name: http
              containerPort: 80
''',
      'chart/templates/service.yaml': '''apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/instance: {{ .Release.Name }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: http
'''
    }

def tasks():
    out=[]
    dep=deployment('api',3,labels={'app':'api','tier':'backend'})
    out.append(task('p01','Create and scale a Deployment','deployment',[
      'Create Deployment `api` with exactly three replicas and container `web` using `nginx:1.27.5-alpine`.',
      'Use `app=api` and `tier=backend` in both the Deployment selector and the Pod template labels.',
      'Leave the rollout complete, with three updated, available replicas.'
    ],level='Foundation',minutes=5,final=[dep],checks=[resource('Three replicas and correct Pod template','deployment','api',dep['spec'],['spec']),ready('deployment','api')],docs=['deployment'],
    explanation='A Deployment owns ReplicaSets; ReplicaSets maintain Pods. Match the immutable Deployment selector to labels on its Pod template, not merely labels on the Deployment object.'))

    old=deployment('checkout',3)
    new=deployment('checkout',3,NGINX_NEW)
    new['spec']['strategy']={'type':'RollingUpdate','rollingUpdate':{'maxSurge':1,'maxUnavailable':0}}
    out.append(task('p02','Perform a zero-unavailable rolling update','deployment',[
      'Deployment `checkout` already exists with three replicas. Update its `web` image to `nginx:1.28.0-alpine`.',
      'Use strategy `RollingUpdate`, with integer `maxSurge: 1` and integer `maxUnavailable: 0`. Keep three desired replicas.',
      'Wait for the rollout to complete. Do not replace it with a differently named Deployment.'
    ],minutes=6,seeds=[old],final=[new],checks=[resource('New image','deployment','checkout',NGINX_NEW,D()+['image'],'equals'),resource('Requested rolling strategy and replica count','deployment','checkout',{'replicas':3,'strategy':new['spec']['strategy']},['spec']),ready('deployment','checkout')],
      docs=['deployment'],after='kubectl rollout status deployment/checkout --timeout=180s\n',
      explanation='maxUnavailable: 0 keeps old available replicas during the update while maxSurge permits one extra Pod. Real availability still depends on application readiness; this setting is not a universal guarantee of zero downtime.'))

    old=deployment('ledger',2)
    out.append(task('p03','Recover a failed Deployment rollout','deployment',[
      'A bad image update has stalled Deployment `ledger`. Inspect its rollout history and restore the known-good image `nginx:1.27.5-alpine`.',
      'Keep the Deployment named `ledger`, container named `web`, and replica count `2`.',
      'Leave both replicas updated and available. Prefer a rollout rollback rather than deleting the Deployment.'
    ],minutes=6,seeds=[old],setup=[{'command':['kubectl','-n','ckad-p03','rollout','status','deployment/ledger','--timeout=240s'],'timeout':250},{'command':['kubectl','-n','ckad-p03','set','image','deployment/ledger','web=nginx:does-not-exist-ckad']}],
      solution='kubectl rollout history deployment/ledger\nkubectl rollout undo deployment/ledger\nkubectl rollout status deployment/ledger --timeout=180s\n',checks=[resource('Known-good image restored','deployment','ledger',NGINX,D()+['image'],'equals'),resource('Two desired replicas remain','deployment','ledger',2,['spec','replicas'],'equals'),ready('deployment','ledger')],docs=['deployment','debug'],
      explanation='The seeded rollout has a completed earlier revision and a broken current revision. Grading checks the restored running state, not whether you typed a particular recovery command.'))

    blue=http_deployment('checkout-blue',2,{'app':'checkout','version':'blue'},'BLUE')
    green=http_deployment('checkout-green',2,{'app':'checkout','version':'green'},'GREEN')
    svc=service('checkout',{'app':'checkout','version':'blue'},80,8080)
    new=service('checkout',{'app':'checkout','version':'green'},80,8080)
    out.append(task('p04','Switch a blue-green deployment','deployment',[
      'The `checkout-blue` and `checkout-green` Deployments already exist, each with two replicas. Their pages return BLUE and GREEN respectively.',
      'Switch Service `checkout` to select only Pods with `app=checkout,version=green`. Keep Service port `80` and target port `8080`.',
      'Keep both Deployments running with two replicas. Verify that a request from Pod `client` to `http://checkout` returns GREEN.'
    ],minutes=6,seeds=[blue,green,svc,sleeper('client')],final=[new],checks=[resource('Service selects green only','service','checkout',{'app':'checkout','version':'green'},['spec','selector'],'equals'),
      resource('Service ports preserved','service','checkout',[{'port':80,'targetPort':8080}],['spec','ports']),
      resource('Blue replica count preserved','deployment','checkout-blue',2,['spec','replicas'],'equals'),resource('Green replica count preserved','deployment','checkout-green',2,['spec','replicas'],'equals'),
      ready('deployment','checkout-blue'),ready('deployment','checkout-green'),check('Live Service response is GREEN','http',source='client',url='http://checkout',expected='GREEN')],docs=['deployment','service'],
      explanation='Blue-green switching changes a Service selector after the green workload is ready. It is not a new Service type. The blue workload remains available for a quick traffic switch-back.'))

    stable=deployment('public-stable',4,labels={'app':'public','track':'stable'})
    canary=deployment('public-canary',1,NGINX_NEW,labels={'app':'public','track':'canary'})
    svc=service('public',{'app':'public','track':'stable'})
    new=service('public',{'app':'public'})
    out.append(task('p05','Add a replica-based canary','deployment',[
      'Deployment `public-stable` already has four replicas using `nginx:1.27.5-alpine` and labels `app=public,track=stable`.',
      'Create Deployment `public-canary` with one replica, container `web`, image `nginx:1.28.0-alpine`, and selector/Pod labels `app=public,track=canary`.',
      'Change Service `public` to select exactly `app=public`, so all five healthy Pods are eligible. Keep Service port and target port at `80`.',
      'Leave the stable Deployment unchanged. This is a 4:1 endpoint split, not an exact per-request traffic percentage guarantee.'
    ],level='Advanced',minutes=8,seeds=[stable,svc],final=[canary,new],checks=[resource('Canary is configured correctly','deployment','public-canary',canary['spec'],['spec']),resource('Stable retains four old-image replicas','deployment','public-stable',{'replicas':4,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),resource('Service selects both tracks','service','public',{'app':'public'},['spec','selector'],'equals'),resource('Service port mapping','service','public',[{'port':80,'targetPort':80}],['spec','ports']),
      ready('deployment','public-canary'),ready('deployment','public-stable'),check('Five ready Service endpoints','endpoints',name='public',count=5)],docs=['deployment','service'],
      explanation='Selecting four stable Pods and one canary Pod creates a 4:1 pool of endpoints. Session affinity, connection reuse, readiness, and the data plane can affect observed request distribution.'))

    out.append(task('p06','Install an existing Helm chart','deployment',[
      'A complete local chart is available at `/workspace/p06/chart`. Install it as release `notes-web` in this task namespace.',
      'Set the chart value `replicaCount=2`. Keep its default nginx image and Service settings.',
      'The release must be deployed and Deployment `notes-web` must have two available replicas. Do not apply manually rendered YAML in place of a Helm release.'
    ],minutes=6,files=chart_files(),solution='helm install notes-web /workspace/p06/chart --set replicaCount=2 --wait --timeout 240s\nhelm list\n',checks=[check('Helm release is deployed with the requested values','helm',release='notes-web',values={'replicaCount':2}),resource('Two nginx replicas','deployment','notes-web',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','notes-web')],docs=['helm'],explanation='Helm stores release information as well as applying resources. The chart is supplied locally so practice does not depend on a changing third-party chart repository.'))

    out.append(task('p07','Upgrade a Helm-managed application','deployment',[
      'Helm release `catalog` is already installed from `/workspace/p07/chart` with its default values.',
      'Upgrade that release, setting `replicaCount=3` and `image.tag=1.28.0-alpine`. Keep release name `catalog` and image repository `nginx`.',
      'Leave the Helm release deployed and all three new replicas available.'
    ],minutes=6,files=chart_files(),setup=[{'command':['helm','install','catalog','/workspace/p07/chart','-n','ckad-p07','--wait','--timeout','240s'],'timeout':250}],solution='helm get values catalog\nhelm upgrade catalog /workspace/p07/chart --set replicaCount=3 --set image.tag=1.28.0-alpine --wait --timeout 240s\n',checks=[check('Helm revision and upgraded values','helm',release='catalog',values={'replicaCount':3,'image':{'tag':'1.28.0-alpine'}},min_revision=2),resource('New image and replica count','deployment','catalog',{'replicas':3,'template':{'spec':{'containers':[{'name':'web','image':NGINX_NEW}]}}},['spec']),ready('deployment','catalog')],docs=['helm','deployment'],explanation='Changing live Kubernetes objects directly would create drift from the Helm release. This task checks Helm values and revision information as well as the running Deployment.'))

    out.append(task('p08','Roll back a broken Helm release','deployment',[
      'Release `orders` has a healthy first revision and a broken second revision. Inspect `helm history orders`.',
      'Roll the release back to revision `1`, restoring two replicas and image `nginx:1.27.5-alpine`.',
      'Keep the release installed. Its latest revision must be deployed and the Deployment healthy.'
    ],minutes=7,files=chart_files(),setup=[{'command':['helm','install','orders','/workspace/p08/chart','-n','ckad-p08','--set','replicaCount=2','--wait','--timeout','240s'],'timeout':250},{'command':['helm','upgrade','orders','/workspace/p08/chart','-n','ckad-p08','--set','replicaCount=3','--set','image.tag=does-not-exist-ckad']}],solution='helm history orders\nhelm rollback orders 1 --wait --timeout 240s\n',checks=[check('New Helm revision restores old values','helm',release='orders',values={'replicaCount':2,'image':{'tag':'1.27.5-alpine'}},min_revision=3),resource('Original image and replica count restored','deployment','orders',{'replicas':2,'template':{'spec':{'containers':[{'name':'web','image':NGINX}]}}},['spec']),ready('deployment','orders')],docs=['helm'],explanation='A Helm rollback creates a new release revision containing the selected older configuration. It is different from rolling back only the Deployment controller.'))

    base=deployment('frontend',1)
    expected=deployment('prod-frontend',3,NGINX_NEW,labels={'app':'frontend','environment':'production'})
    expected['metadata']['labels']={'environment':'production'}
    overlay={'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','namespace':'ckad-p09','resources':['../../base'],'namePrefix':'prod-','labels':[{'pairs':{'environment':'production'},'includeSelectors':True,'includeTemplates':True}], 'replicas':[{'name':'frontend','count':3}], 'images':[{'name':'nginx','newTag':'1.28.0-alpine'}]}
    files={'base/deployment.yaml':yaml.safe_dump(base,sort_keys=False),'base/kustomization.yaml':'resources:\n  - deployment.yaml\n','overlays/prod/kustomization.yaml':'resources:\n  - ../../base\n'}
    solution="cat > /workspace/p09/overlays/prod/kustomization.yaml <<'YAML'\n"+yaml.safe_dump(overlay,sort_keys=False)+"YAML\nkubectl kustomize /workspace/p09/overlays/prod\nkubectl apply -k /workspace/p09/overlays/prod\nkubectl rollout status deployment/prod-frontend --timeout=180s\n"
    out.append(task('p09','Build and apply a Kustomize production overlay','deployment',[
      'The base at `/workspace/p09/base` defines a one-replica Deployment `frontend`. Do not modify the base files.',
      'Complete `/workspace/p09/overlays/prod/kustomization.yaml`: set this task namespace, prefix names with `prod-`, use three replicas, and change the nginx image tag to `1.28.0-alpine`.',
      'Add label `environment=production` to the Deployment, its selector, and its Pod template using the overlay.',
      'Apply the overlay with kubectl. Leave Deployment `prod-frontend` healthy and preserve the working overlay on disk.'
    ],level='Advanced',minutes=9,files=files,solution=solution,checks=[
      filecheck('Base deployment has not changed','/workspace/p09/base/deployment.yaml',files['base/deployment.yaml'],'equals'),
      filecheck('Base kustomization has not changed','/workspace/p09/base/kustomization.yaml',files['base/kustomization.yaml'],'equals'),
      check('Saved overlay renders required Deployment','render',path='/workspace/p09/overlays/prod',expected=scoped([expected],'ckad-p09')),
      resource('Live production Deployment has correct configuration','deployment','prod-frontend',expected['spec'],['spec']),ready('deployment','prod-frontend')],docs=['kustomize','deployment'],explanation='Kustomize transforms reusable base manifests without using Helm templates. The grader builds the saved overlay and also checks live resources; manually creating only the final Deployment does not satisfy the complete task.'))

    dep=deployment('autoscale',2)
    final=deepcopy(dep); final['spec']['template']['spec']['containers'][0]['resources']={'requests':{'cpu':'100m'}}
    hpa=obj('HorizontalPodAutoscaler','autoscale',{'scaleTargetRef':{'apiVersion':'apps/v1','kind':'Deployment','name':'autoscale'},'minReplicas':2,'maxReplicas':5,'metrics':[{'type':'Resource','resource':{'name':'cpu','target':{'type':'Utilization','averageUtilization':50}}}]},api='autoscaling/v2')
    out.append(task('p10','Configure CPU-based horizontal scaling','deployment',[
      'Deployment `autoscale` exists. Give its `web` container a CPU request of `100m`.',
      'Create an `autoscaling/v2` HorizontalPodAutoscaler named `autoscale`, targeting that Deployment, with minimum `2`, maximum `5`, and average CPU utilization target `50%`.',
      'Leave the Deployment healthy. You do not need to generate load or force a scale-up; utilization is measured relative to CPU requests.'
    ],minutes=7,seeds=[dep],final=[final,hpa],checks=[quantity('CPU request set on target container','deployment','autoscale',D()+['resources','requests','cpu'],'100m'),resource('HPA target, bounds and CPU metric','hpa','autoscale',hpa['spec'],['spec']),ready('deployment','autoscale')],docs=['hpa','resources'],explanation='An HPA resource-utilization target depends on resource requests and available metrics. This lab includes metrics-server. The grader does not demand a particular momentary replica count above the minimum, because measured load changes over time.'))
    return out
