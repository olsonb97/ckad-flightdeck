from bank_helpers import *

def tasks():
    out=[]
    p=pod('catalog',[container(ports=[{'containerPort':80}],env=[{'name':'MODE','value':'production'}])],labels={'app':'catalog','tier':'frontend'})
    out.append(task('d01','Create a precisely configured Pod','design',[
        'Create a standalone Pod named `catalog` using `nginx:1.27.5-alpine`. Name its container `web`.',
        'Set Pod labels `app=catalog` and `tier=frontend`, declare container port `80`, and set the environment variable `MODE=production`.',
        'Leave the Pod running and Ready. Do not create a Deployment instead.'
    ],level='Foundation',minutes=4,final=[p],checks=[
        resource('Correct image and container port','pod','catalog',{'image':NGINX,'ports':[{'containerPort':80}]},C()),
        resource('Both required labels','pod','catalog',p['metadata']['labels'],['metadata','labels']),
        resource('MODE is production','pod','catalog',[{'name':'MODE','value':'production'}],C()+['env']),ready('pod','catalog')
    ],docs=['pod'],hints=['kubectl run can generate a Pod manifest with --dry-run=client -o yaml.',
        'Use --labels, --env and --port, then inspect the generated container name before applying.'],
        explanation='kubectl run creates a Pod, not a ReplicaSet or Deployment. The containerPort declaration documents a port; it does not configure nginx or publish a Service.'))

    p=pod('landing',[container(volumeMounts=[{'name':'content','mountPath':'/usr/share/nginx/html'}])],
        initContainers=[container('prepare',BUSYBOX,['sh','-c',"printf 'prepared by init\\n' > /work/index.html"],volumeMounts=[{'name':'content','mountPath':'/work'}])],
        volumes=[{'name':'content','emptyDir':{}}])
    out.append(task('d02','Prepare shared content with an init container','design',[
        'Create Pod `landing` with a regular container `web` using `nginx:1.27.5-alpine` and an init container `prepare` using `busybox:1.37.0`.',
        'Use an `emptyDir` volume named `content`. Mount it at `/work` in `prepare` and `/usr/share/nginx/html` in `web`.',
        'The init container must write the line `prepared by init` to `/work/index.html` and exit successfully. Leave the web container Ready and serving that file.'
    ],minutes=7,final=[p],checks=[
        resource('Init container, image and shared mount','pod','landing',{'name':'prepare','image':BUSYBOX,'volumeMounts':[{'name':'content','mountPath':'/work'}]},['spec','initContainers',{'name':'prepare'}]),
        resource('emptyDir and web volume mount','pod','landing',{'volumes':[{'name':'content','emptyDir':{}}],'containers':[{'name':'web','image':NGINX,'volumeMounts':[{'name':'content','mountPath':'/usr/share/nginx/html'}]}]},['spec']),
        exec_check('Shared content exists in web container','landing',['cat','/usr/share/nginx/html/index.html'],'prepared by init',container_name='web'),exec_check('Web container actually serves the prepared page','landing',['wget','-q','-O-','http://127.0.0.1/'],'prepared by init',container_name='web'),ready('pod','landing')
    ],docs=['init','volume'],hints=['Regular init containers belong in spec.initContainers, not spec.containers.',
        'Both containers reference the same volume name. The mount paths may differ.'],
        explanation='A regular init container finishes before application containers start. emptyDir survives a container restart, but is deleted when its Pod is removed.'))

    p=pod('audit',[container('writer',BUSYBOX,['sh','-c',"while true; do echo heartbeat >> /logs/app.log; sleep 2; done"],volumeMounts=[{'name':'logs','mountPath':'/logs'}]),
        container('reader',BUSYBOX,['sh','-c','touch /logs/app.log; tail -F /logs/app.log'],volumeMounts=[{'name':'logs','mountPath':'/logs'}])],volumes=[{'name':'logs','emptyDir':{}}])
    out.append(task('d03','Run a shared-volume logging sidecar','design',[
        'Create Pod `audit` with two regular containers named `writer` and `reader`, both using `busybox:1.37.0`.',
        'Mount the same `emptyDir` volume named `logs` at `/logs` in both containers.',
        'The writer must append `heartbeat` to `/logs/app.log` repeatedly. The reader must continuously send new lines from that file to its standard output.',
        'Both containers must remain running. For this exercise use two regular containers, not a native restartable-init sidecar.'
    ],minutes=8,final=[p],checks=[
        resource('Both regular containers use busybox and mount logs','pod','audit',{'containers':[{'name':'writer','image':BUSYBOX,'volumeMounts':[{'name':'logs','mountPath':'/logs'}]},{'name':'reader','image':BUSYBOX,'volumeMounts':[{'name':'logs','mountPath':'/logs'}]}],'volumes':[{'name':'logs','emptyDir':{}}]},['spec']),
        check('Exactly two regular containers','resource',resource='pod',name='audit',path=['spec','containers'],op='length',expected=2),
        check('Reader emits heartbeat logs','logs',resource='pod/audit',container='reader',expected='heartbeat',op='contains'),ready('pod','audit')
    ],docs=['pod','volume','sidecar'],explanation='This is the classic two-regular-container sidecar pattern. Kubernetes also supports native sidecars as initContainers with restartPolicy: Always; the task intentionally specifies the classic form so the requested object shape is unambiguous.'))

    job=obj('Job','importer',{'completions':4,'parallelism':2,'backoffLimit':2,'template':{'spec':{'restartPolicy':'Never','containers':[container('worker',BUSYBOX,['sh','-c','echo processed; sleep 2'])]}}},api='batch/v1')
    out.append(task('d04','Run a parallel batch Job','design',[
        'Create Job `importer` with `completions: 4`, `parallelism: 2`, and `backoffLimit: 2`.',
        'Use a container named `worker` with image `busybox:1.37.0`. It must print `processed`, sleep for two seconds, and exit successfully.',
        'Set the Pod template restart policy to `Never`. Leave the Job in a successfully completed state.'
    ],minutes=6,final=[job],checks=[
        resource('Four completions, parallelism two, retry limit two','job','importer',{'completions':4,'parallelism':2,'backoffLimit':2},['spec']),
        resource('Correct image and Never restart policy','job','importer',{'restartPolicy':'Never','containers':[{'name':'worker','image':BUSYBOX}]},['spec','template','spec']),
        check('Job has four successful completions','job_complete',name='importer',completions=4),
        check('Worker prints processed','logs',resource='job/importer',expected='processed',op='contains')
    ],docs=['job'],after='kubectl wait --for=condition=complete job/importer --timeout=180s\n',
        explanation='completions is the required number of successful Pod executions; parallelism limits concurrent Pods. restartPolicy controls container restarts inside a Pod, not repetition of a completed Job.'))

    js={'template':{'spec':{'restartPolicy':'OnFailure','containers':[container('report',BUSYBOX,['sh','-c','echo report-ready'])]}}}
    cron=obj('CronJob','report',{'schedule':'*/5 * * * *','concurrencyPolicy':'Forbid','successfulJobsHistoryLimit':2,'jobTemplate':{'spec':js}},api='batch/v1')
    out.append(task('d05','Schedule a CronJob and trigger it manually','design',[
        'Create CronJob `report` with schedule `*/5 * * * *`, concurrency policy `Forbid`, and successful job history limit `2`.',
        'Its Pod template must use restart policy `OnFailure` and container `report` with `busybox:1.37.0`, printing `report-ready` and exiting successfully.',
        'Create a one-off Job named `report-now` from that CronJob without waiting for the next scheduled run. Leave it completed. Cluster time is UTC.'
    ],minutes=7,final=[cron],after='kubectl create job report-now --from=cronjob/report\nkubectl wait --for=condition=complete job/report-now --timeout=180s\n',checks=[
        resource('Schedule and concurrency settings','cronjob','report',{'schedule':'*/5 * * * *','concurrencyPolicy':'Forbid','successfulJobsHistoryLimit':2},['spec']),
        resource('CronJob template','cronjob','report',{'restartPolicy':'OnFailure','containers':[{'name':'report','image':BUSYBOX}]},['spec','jobTemplate','spec','template','spec']),
        resource('One-off Job uses the report template','job','report-now',js['template']['spec'],['spec','template','spec']),
        check('One-off Job completed','job_complete',name='report-now',completions=1)
    ],docs=['cronjob','job'],explanation='The CronJob controls scheduling; its jobTemplate is a Job specification containing a Pod template. kubectl create job --from=cronjob/... produces an immediate, independent Job.'))

    pvc=obj('PersistentVolumeClaim','data',{'accessModes':['ReadWriteOnce'],'storageClassName':'local-path','resources':{'requests':{'storage':'1Gi'}}})
    p=pod('archive',[container('writer',BUSYBOX,['sh','-c','echo durable > /data/marker.txt; sleep 86400'],volumeMounts=[{'name':'data','mountPath':'/data'}])],volumes=[{'name':'data','persistentVolumeClaim':{'claimName':'data'}}])
    out.append(task('d06','Attach persistent storage to an application','design',[
        'Create PVC `data` requesting `1Gi`, access mode `ReadWriteOnce`, and storage class `local-path`.',
        'Create Pod `archive` with container `writer` using `busybox:1.37.0`. Mount that claim through a volume named `data` at `/data`.',
        'Write the line `durable` to `/data/marker.txt`, then keep the container running. The claim must be Bound and the Pod Ready.'
    ],minutes=8,final=[pvc,p],checks=[
        resource('Correct access mode and storage class','pvc','data',{'accessModes':['ReadWriteOnce'],'storageClassName':'local-path'},['spec']),
        quantity('One GiB storage requested','pvc','data',['spec','resources','requests','storage'],'1Gi'),
        resource('PVC is Bound','pvc','data','Bound',['status','phase'],'equals'),
        resource('Pod mounts the named PVC','pod','archive',{'volumes':[{'name':'data','persistentVolumeClaim':{'claimName':'data'}}],'containers':[{'name':'writer','image':BUSYBOX,'volumeMounts':[{'name':'data','mountPath':'/data'}]}]},['spec']),
        exec_check('Marker exists on the mounted filesystem','archive',['cat','/data/marker.txt'],'durable','writer'),ready('pod','archive')
    ],docs=['pvc','volume'],explanation='The local-path StorageClass uses delayed binding: the PVC can remain Pending until a consumer Pod is scheduled. Do not treat that initial Pending state as a broken claim. Storage here is node-local, not a production network storage system.'))

    ds=obj('DaemonSet','node-agent',{'selector':{'matchLabels':{'app':'node-agent'}},'template':{'metadata':{'labels':{'app':'node-agent'}},'spec':{'nodeSelector':{'kubernetes.io/os':'linux'},'containers':[container('agent',BUSYBOX,['sh','-c','sleep 86400'])]}}},api='apps/v1')
    out.append(task('d07','Run one agent on each Linux node','design',[
        'Create DaemonSet `node-agent` with selector and Pod label `app=node-agent`.',
        'Use container `agent`, image `busybox:1.37.0`, and a long-running sleep command. Select Linux nodes with `kubernetes.io/os=linux`.',
        'Leave one healthy DaemonSet Pod on each of the two lab nodes. Do not use a Deployment with a fixed replica count.'
    ],minutes=6,final=[ds],checks=[resource('DaemonSet selector, Linux node selection and container','daemonset','node-agent',ds['spec'],['spec']),ready('daemonset','node-agent'),
        resource('Both nodes are covered','daemonset','node-agent',2,['status','desiredNumberScheduled'],'at_least')],docs=['daemonset'],
        explanation='A DaemonSet follows eligible nodes, rather than an arbitrary replica count. This lab has two schedulable Linux nodes; the task does not involve modifying node taints.'))

    svc=service('store',{'app':'store'},clusterIP='None')
    st=obj('StatefulSet','store',{'serviceName':'store','replicas':2,'selector':{'matchLabels':{'app':'store'}},'template':{'metadata':{'labels':{'app':'store'}},'spec':{'containers':[container(volumeMounts=[{'name':'data','mountPath':'/data'}])]}},'volumeClaimTemplates':[obj('PersistentVolumeClaim','data',{'accessModes':['ReadWriteOnce'],'storageClassName':'local-path','resources':{'requests':{'storage':'128Mi'}}})]},api='apps/v1')
    out.append(task('d08','Deploy stable identities with per-Pod storage','design',[
        'Create headless Service `store` selecting `app=store`, port `80`, target port `80`.',
        'Create StatefulSet `store` with `serviceName: store`, two replicas, matching selector/Pod labels `app=store`, and container `web` using `nginx:1.27.5-alpine`.',
        'Add a volumeClaimTemplate named `data`: `128Mi`, `ReadWriteOnce`, storage class `local-path`. Mount it at `/data` in the web container.',
        'Leave Pods `store-0` and `store-1` Ready and both generated claims Bound.'
    ],level='Advanced',minutes=10,final=[svc,st],checks=[
        resource('Headless Service selects store Pods','service','store',{'clusterIP':'None','selector':{'app':'store'},'ports':[{'port':80,'targetPort':80}]},['spec']),
        resource('StatefulSet identity, replicas and data mount','statefulset','store',{'serviceName':'store','replicas':2,'selector':{'matchLabels':{'app':'store'}},'template':st['spec']['template']},['spec']),
        resource('ReadWriteOnce local claim template','statefulset','store',{'accessModes':['ReadWriteOnce'],'storageClassName':'local-path'},['spec','volumeClaimTemplates',{'metadata.name':'data'},'spec']),
        quantity('128 MiB per-Pod claim request','statefulset','store',['spec','volumeClaimTemplates',{'metadata.name':'data'},'spec','resources','requests','storage'],'128Mi'),
        ready('pod','store-0'),ready('pod','store-1'),check('Headless Service has two ready endpoints','endpoints',name='store',count=2),
        resource('First claim Bound','pvc','data-store-0','Bound',['status','phase'],'equals'),resource('Second claim Bound','pvc','data-store-1','Bound',['status','phase'],'equals')
    ],docs=['statefulset','pvc','service'],explanation='A headless Service has clusterIP: None. Each StatefulSet Pod receives its own claim from volumeClaimTemplates; the workload also has stable ordinal names.'))

    out.append(task('d09','Build and verify a container image','design',[
        'The starter file `/workspace/d09/index.html` contains the required web page. Create `/workspace/d09/Dockerfile` based on `nginx:1.27.5-alpine`.',
        'Copy that page to `/usr/share/nginx/html/index.html` in the image, and add OCI label `org.opencontainers.image.title=ckad-site`.',
        'Build image `ckad-site:1.0`. Its installed page must contain `CKAD READY`. Use the provided isolated Docker builder; no Kubernetes Deployment is required.'
    ],minutes=6,files={'index.html':'<!doctype html><html><body><h1>CKAD READY</h1></body></html>\n'},solution="cat > /workspace/d09/Dockerfile <<'DOCKERFILE'\nFROM nginx:1.27.5-alpine\nLABEL org.opencontainers.image.title=\"ckad-site\"\nCOPY index.html /usr/share/nginx/html/index.html\nDOCKERFILE\ndocker build -t ckad-site:1.0 /workspace/d09\ndocker run --rm --entrypoint cat ckad-site:1.0 /usr/share/nginx/html/index.html\n",checks=[
        filecheck('Dockerfile is saved','/workspace/d09/Dockerfile','','nonempty'),
        check('Built image uses the supplied nginx base','image_base',image='ckad-site:1.0',base=NGINX),
        check('Built image has the required OCI label','image',image='ckad-site:1.0',path=['Config','Labels','org.opencontainers.image.title'],expected='ckad-site'),
        check('Image contains the required page','image_file',image='ckad-site:1.0',file='/usr/share/nginx/html/index.html',expected='CKAD READY',op='contains')
    ],docs=['docker'],hints=['The docker CLI connects to a separate lab-only Docker daemon. docker build and docker run are real commands.',
        'Use FROM, LABEL and COPY. An image built here is not automatically present in the Kubernetes containerd runtime.'],
        explanation='This task tests a real OCI image build. The Docker builder and Kubernetes containerd are deliberately separate image stores. The grader reads the built image, not just the Dockerfile text.'))

    out.append(task('d10','Retag and export an image archive','design',[
        'The builder has a prepared image named `ckad-tools:v1` based on `busybox:1.37.0`.',
        'Add the tag `ckad-tools:release` to that exact same image. Do not rebuild a different image.',
        'Export `ckad-tools:release` with `docker image save` to `/workspace/d10/ckad-tools.tar`. This must be an image archive, not a container filesystem export.'
    ],level='Foundation',minutes=5,setup=[{'command':['docker','pull',BUSYBOX],'timeout':240},{'command':['docker','tag',BUSYBOX,'ckad-tools:v1']}],
    solution='docker tag ckad-tools:v1 ckad-tools:release\ndocker image save -o /workspace/d10/ckad-tools.tar ckad-tools:release\n',checks=[
        check('Release tag points to the prepared image','image_same',image='ckad-tools:release',other='ckad-tools:v1'),
        check('Valid docker-save archive with the release tag','image_archive',path='/workspace/d10/ckad-tools.tar',tag='ckad-tools:release')
    ],docs=['save','docker'],explanation='docker save preserves image metadata and layers. docker export exports a container filesystem and is not interchangeable with docker save.'))
    return out
