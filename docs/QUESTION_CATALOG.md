# Question catalog

Two visible sets: Core 20 and Focused 16. Both display ordinary question numbers starting at 1. Core research date: September 14, 2026; focused-set review: September 25, 2026. Target Kubernetes: 1.35.

This catalog contains prompts, not the worked solutions. Opening a question automatically prepares its fixtures and starter files before its prompt and scoped terminal become ready. The terminal is already connected to the lab. Use `-n` with the question’s namespace; file paths are specified where needed. See the [README validation guidance](../README.md#validate-the-entire-bank-before-studying) before relying on the bank.

## Set 1: Core 20

The visible order is:

- 1–4 · Design: d01, d02, d03, d06 — Pods, init containers, sidecars, and persistent storage.
- 5–8 · Deployment: p01, p06, p09, p10 — scaling, Helm, Kustomize, and autoscaling.
- 9–11 · Observability: o01, o03, o06 — probes, logs, and metrics.
- 12–16 · Configuration: c01, c04, c06, c09, c11 — ConfigMaps, Secret volumes, RBAC, security, and custom APIs.
- 17–20 · Networking: n01, n08, n09, n10 — Services and ingress/egress policy selectors.

Internal IDs are retained for stored data and maintainer commands; the UI shows 1–20, not these letter codes.

## Set 2: Focused 16

The source questions are credited in [SOURCES.md](SOURCES.md#focused-16-scenario-objectives). These lab implementations retain their resource names and technical requirements, but use fresh wording and isolated fixtures rather than copying upstream prompts or setup files. Full requirements, reference solutions, and per-step feedback are in the app.

Each task ID maps to namespace `ckad-<id>` and workspace `/workspace/<id>`; for example S03 uses `ckad-s03` and `/workspace/s03`.

| ID / source question | Scenario | Domain |
|---|---|---|
| S01 / 1 | Create a Secret from hard-coded variables | Configuration |
| S02 / 2 | Create a CronJob with schedule and history limits | Design |
| S03 / 3 | Diagnose a denied API request and grant read access | Configuration |
| S04 / 4 | Fix a Pod using the wrong ServiceAccount | Configuration |
| S05 / 5 | Build an image and save it as a tarball | Design |
| S06 / 6 | Create a canary Deployment with an 8:2 split | Deployment |
| S07 / 7 | Fix NetworkPolicy connectivity by relabeling Pods | Networking |
| S08 / 8 | Repair a broken Deployment manifest | Deployment |
| S09 / 9 | Perform a rolling update and rollback | Deployment |
| S10 / 10 | Add a readiness check to a real health endpoint | Observability |
| S11 / 11 | Configure Pod and container security contexts | Configuration |
| S12 / 12 | Fix a Service selector | Networking |
| S13 / 13 | Create a NodePort Service | Networking |
| S14 / 14 | Create an Ingress resource | Networking |
| S15 / 15 | Fix an invalid Ingress path type | Networking |
| S16 / 16 | Create a Pod sized from ResourceQuota | Configuration |

## Legacy core reference

The following sections retain the original definitions for reference and old reports. Only the 20 IDs listed above appear in the active core question list.

## Application Design and Build — 20%

### D01 · Create a precisely configured Pod

**Foundation · Practice target ~4 minutes · 4 criteria**

Namespace: `ckad-d01` · Workspace: `/workspace/d01`

1. Create a standalone Pod named `catalog` using `nginx:1.27.5-alpine`. Name its container `web`.
2. Set Pod labels `app=catalog` and `tier=frontend`, declare container port `80`, and set the environment variable `MODE=production`.
3. Leave the Pod running and Ready. Do not create a Deployment instead.

References: [Pod](https://kubernetes.io/docs/concepts/workloads/pods/)

### D02 · Prepare shared content with an init container

**Intermediate · Practice target ~7 minutes · 5 criteria**

Namespace: `ckad-d02` · Workspace: `/workspace/d02`

1. Create Pod `landing` with a regular container `web` using `nginx:1.27.5-alpine` and an init container `prepare` using `busybox:1.37.0`.
2. Use an `emptyDir` volume named `content`. Mount it at `/work` in `prepare` and `/usr/share/nginx/html` in `web`.
3. The init container must write the line `prepared by init` to `/work/index.html` and exit successfully. Leave the web container Ready and serving that file.

References: [Init](https://kubernetes.io/docs/concepts/workloads/pods/init-containers/) · [Volume](https://kubernetes.io/docs/concepts/storage/volumes/)

### D03 · Run a shared-volume logging sidecar

**Intermediate · Practice target ~8 minutes · 4 criteria**

Namespace: `ckad-d03` · Workspace: `/workspace/d03`

1. Create Pod `audit` with two regular containers named `writer` and `reader`, both using `busybox:1.37.0`.
2. Mount the same `emptyDir` volume named `logs` at `/logs` in both containers.
3. The writer must append `heartbeat` to `/logs/app.log` repeatedly. The reader must continuously send new lines from that file to its standard output.
4. Both containers must remain running. For this exercise use two regular containers, not a native restartable-init sidecar.

References: [Pod](https://kubernetes.io/docs/concepts/workloads/pods/) · [Volume](https://kubernetes.io/docs/concepts/storage/volumes/) · [Sidecar](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)

### D04 · Run a parallel batch Job

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-d04` · Workspace: `/workspace/d04`

1. Create Job `importer` with `completions: 4`, `parallelism: 2`, and `backoffLimit: 2`.
2. Use a container named `worker` with image `busybox:1.37.0`. It must print `processed`, sleep for two seconds, and exit successfully.
3. Set the Pod template restart policy to `Never`. Leave the Job in a successfully completed state.

References: [Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/)

### D05 · Schedule a CronJob and trigger it manually

**Intermediate · Practice target ~7 minutes · 4 criteria**

Namespace: `ckad-d05` · Workspace: `/workspace/d05`

1. Create CronJob `report` with schedule `*/5 * * * *`, concurrency policy `Forbid`, and successful job history limit `2`.
2. Its Pod template must use restart policy `OnFailure` and container `report` with `busybox:1.37.0`, printing `report-ready` and exiting successfully.
3. Create a one-off Job named `report-now` from that CronJob without waiting for the next scheduled run. Leave it completed. Cluster time is UTC.

References: [Cronjob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/) · [Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/)

### D06 · Attach persistent storage to an application

**Intermediate · Practice target ~8 minutes · 6 criteria**

Namespace: `ckad-d06` · Workspace: `/workspace/d06`

1. Create PVC `data` requesting `1Gi`, access mode `ReadWriteOnce`, and storage class `local-path`.
2. Create Pod `archive` with container `writer` using `busybox:1.37.0`. Mount that claim through a volume named `data` at `/data`.
3. Write the line `durable` to `/data/marker.txt`, then keep the container running. The claim must be Bound and the Pod Ready.

References: [Pvc](https://kubernetes.io/docs/concepts/storage/persistent-volumes/) · [Volume](https://kubernetes.io/docs/concepts/storage/volumes/)

### D07 · Run one agent on each Linux node

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-d07` · Workspace: `/workspace/d07`

1. Create DaemonSet `node-agent` with selector and Pod label `app=node-agent`.
2. Use container `agent`, image `busybox:1.37.0`, and a long-running sleep command. Select Linux nodes with `kubernetes.io/os=linux`.
3. Leave one healthy DaemonSet Pod on each of the two lab nodes. Do not use a Deployment with a fixed replica count.

References: [Daemonset](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/)

### D08 · Deploy stable identities with per-Pod storage

**Advanced · Practice target ~10 minutes · 9 criteria**

Namespace: `ckad-d08` · Workspace: `/workspace/d08`

1. Create headless Service `store` selecting `app=store`, port `80`, target port `80`.
2. Create StatefulSet `store` with `serviceName: store`, two replicas, matching selector/Pod labels `app=store`, and container `web` using `nginx:1.27.5-alpine`.
3. Add a volumeClaimTemplate named `data`: `128Mi`, `ReadWriteOnce`, storage class `local-path`. Mount it at `/data` in the web container.
4. Leave Pods `store-0` and `store-1` Ready and both generated claims Bound.

References: [Statefulset](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/) · [Pvc](https://kubernetes.io/docs/concepts/storage/persistent-volumes/) · [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### D09 · Build and verify a container image

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-d09` · Workspace: `/workspace/d09`

1. The starter file `/workspace/d09/index.html` contains the required web page. Create `/workspace/d09/Dockerfile` based on `nginx:1.27.5-alpine`.
2. Copy that page to `/usr/share/nginx/html/index.html` in the image, and add OCI label `org.opencontainers.image.title=ckad-site`.
3. Build image `ckad-site:1.0`. Its installed page must contain `CKAD READY`. Use the provided isolated Docker builder; no Kubernetes Deployment is required.

Starter files: `index.html`.

References: [Docker](https://docs.docker.com/build/concepts/dockerfile/)

### D10 · Retag and export an image archive

**Foundation · Practice target ~5 minutes · 2 criteria**

Namespace: `ckad-d10` · Workspace: `/workspace/d10`

1. The builder has a prepared image named `ckad-tools:v1` based on `busybox:1.37.0`.
2. Add the tag `ckad-tools:release` to that exact same image. Do not rebuild a different image.
3. Export `ckad-tools:release` with `docker image save` to `/workspace/d10/ckad-tools.tar`. This must be an image archive, not a container filesystem export.

References: [Save](https://docs.docker.com/reference/cli/docker/image/save/) · [Docker](https://docs.docker.com/build/concepts/dockerfile/)

## Application Deployment — 20%

### P01 · Create and scale a Deployment

**Foundation · Practice target ~5 minutes · 2 criteria**

Namespace: `ckad-p01` · Workspace: `/workspace/p01`

1. Create Deployment `api` with exactly three replicas and container `web` using `nginx:1.27.5-alpine`.
2. Use `app=api` and `tier=backend` in both the Deployment selector and the Pod template labels.
3. Leave the rollout complete, with three updated, available replicas.

References: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### P02 · Perform a zero-unavailable rolling update

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-p02` · Workspace: `/workspace/p02`

1. Deployment `checkout` already exists with three replicas. Update its `web` image to `nginx:1.28.0-alpine`.
2. Use strategy `RollingUpdate`, with integer `maxSurge: 1` and integer `maxUnavailable: 0`. Keep three desired replicas.
3. Wait for the rollout to complete. Do not replace it with a differently named Deployment.

References: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### P03 · Recover a failed Deployment rollout

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-p03` · Workspace: `/workspace/p03`

1. A bad image update has stalled Deployment `ledger`. Inspect its rollout history and restore the known-good image `nginx:1.27.5-alpine`.
2. Keep the Deployment named `ledger`, container named `web`, and replica count `2`.
3. Leave both replicas updated and available. Prefer a rollout rollback rather than deleting the Deployment.

References: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) · [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/)

### P04 · Switch a blue-green deployment

**Intermediate · Practice target ~6 minutes · 7 criteria**

Namespace: `ckad-p04` · Workspace: `/workspace/p04`

1. The `checkout-blue` and `checkout-green` Deployments already exist, each with two replicas. Their pages return BLUE and GREEN respectively.
2. Switch Service `checkout` to select only Pods with `app=checkout,version=green`. Keep Service port `80` and target port `8080`.
3. Keep both Deployments running with two replicas. Verify that a request from Pod `client` to `http://checkout` returns GREEN.

References: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) · [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### P05 · Add a replica-based canary

**Advanced · Practice target ~8 minutes · 7 criteria**

Namespace: `ckad-p05` · Workspace: `/workspace/p05`

1. Deployment `public-stable` already has four replicas using `nginx:1.27.5-alpine` and labels `app=public,track=stable`.
2. Create Deployment `public-canary` with one replica, container `web`, image `nginx:1.28.0-alpine`, and selector/Pod labels `app=public,track=canary`.
3. Change Service `public` to select exactly `app=public`, so all five healthy Pods are eligible. Keep Service port and target port at `80`.
4. Leave the stable Deployment unchanged. This is a 4:1 endpoint split, not an exact per-request traffic percentage guarantee.

References: [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) · [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### P06 · Install an existing Helm chart

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-p06` · Workspace: `/workspace/p06`

1. A complete local chart is available at `/workspace/p06/chart`. Install it as release `notes-web` in this task namespace.
2. Set the chart value `replicaCount=2`. Keep its default nginx image and Service settings.
3. The release must be deployed and Deployment `notes-web` must have two available replicas. Do not apply manually rendered YAML in place of a Helm release.

Starter files: `chart/Chart.yaml`, `chart/values.yaml`, `chart/templates/deployment.yaml`, `chart/templates/service.yaml`.

References: [Helm](https://helm.sh/docs/intro/using_helm/)

### P07 · Upgrade a Helm-managed application

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-p07` · Workspace: `/workspace/p07`

1. Helm release `catalog` is already installed from `/workspace/p07/chart` with its default values.
2. Upgrade that release, setting `replicaCount=3` and `image.tag=1.28.0-alpine`. Keep release name `catalog` and image repository `nginx`.
3. Leave the Helm release deployed and all three new replicas available.

Starter files: `chart/Chart.yaml`, `chart/values.yaml`, `chart/templates/deployment.yaml`, `chart/templates/service.yaml`.

References: [Helm](https://helm.sh/docs/intro/using_helm/) · [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### P08 · Roll back a broken Helm release

**Intermediate · Practice target ~7 minutes · 3 criteria**

Namespace: `ckad-p08` · Workspace: `/workspace/p08`

1. Release `orders` has a healthy first revision and a broken second revision. Inspect `helm history orders`.
2. Roll the release back to revision `1`, restoring two replicas and image `nginx:1.27.5-alpine`.
3. Keep the release installed. Its latest revision must be deployed and the Deployment healthy.

Starter files: `chart/Chart.yaml`, `chart/values.yaml`, `chart/templates/deployment.yaml`, `chart/templates/service.yaml`.

References: [Helm](https://helm.sh/docs/intro/using_helm/)

### P09 · Build and apply a Kustomize production overlay

**Advanced · Practice target ~9 minutes · 5 criteria**

Namespace: `ckad-p09` · Workspace: `/workspace/p09`

1. The base at `/workspace/p09/base` defines a one-replica Deployment `frontend`. Do not modify the base files.
2. Complete `/workspace/p09/overlays/prod/kustomization.yaml`: set this task namespace, prefix names with `prod-`, use three replicas, and change the nginx image tag to `1.28.0-alpine`.
3. Add label `environment=production` to the Deployment, its selector, and its Pod template using the overlay.
4. Apply the overlay with kubectl. Leave Deployment `prod-frontend` healthy and preserve the working overlay on disk.

Starter files: `base/deployment.yaml`, `base/kustomization.yaml`, `overlays/prod/kustomization.yaml`.

References: [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/) · [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### P10 · Configure CPU-based horizontal scaling

**Intermediate · Practice target ~7 minutes · 3 criteria**

Namespace: `ckad-p10` · Workspace: `/workspace/p10`

1. Deployment `autoscale` exists. Give its `web` container a CPU request of `100m`.
2. Create an `autoscaling/v2` HorizontalPodAutoscaler named `autoscale`, targeting that Deployment, with minimum `2`, maximum `5`, and average CPU utilization target `50%`.
3. Leave the Deployment healthy. You do not need to generate load or force a scale-up; utilization is measured relative to CPU requests.

References: [Hpa](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) · [Resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)

## Application Observability and Maintenance — 15%

### O01 · Add readiness and liveness health checks

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-o01` · Workspace: `/workspace/o01`

1. Deployment `healthy` exists with two nginx replicas. Add HTTP readiness and liveness probes to container `web`, using path `/` and port `80`.
2. Readiness: initial delay `3` seconds and period `5` seconds. Liveness: initial delay `5` seconds and period `10` seconds.
3. Keep the existing image and two replicas. Leave the rollout complete and the application Ready.

References: [Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

### O02 · Protect startup without weakening ongoing checks

**Intermediate · Practice target ~6 minutes · 3 criteria**

Namespace: `ckad-o02` · Workspace: `/workspace/o02`

1. Deployment `startup` has one nginx replica. Configure three HTTP probes on container `web`, all using `/` on port `80`.
2. Startup probe: `periodSeconds: 2`, `failureThreshold: 30`. Readiness probe: period `3`. Liveness probe: period `5`.
3. Keep the current image and replica count. Leave the updated Pod Ready. The task specifies the probe budget, not an exact startup delay.

References: [Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

### O03 · Extract the correct container logs

**Foundation · Practice target ~4 minutes · 2 criteria**

Namespace: `ckad-o03` · Workspace: `/workspace/o03`

1. Pod `audit` has containers `app` and `metrics`. Inspect logs from `app` only.
2. Save all lines beginning with `ERROR` from the app container to `/workspace/o03/errors.txt`, in their original order.
3. Do not include INFO messages or the metrics container’s error. Do not modify or delete the Pod.

References: [Logs](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_logs/) · [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/)

### O04 · Diagnose an image-pull failure

**Intermediate · Practice target ~5 minutes · 2 criteria**

Namespace: `ckad-o04` · Workspace: `/workspace/o04`

1. Deployment `broken-image` is not becoming available. Inspect its Pods and events to identify the image-pull problem.
2. Correct the `web` container image to `nginx:1.27.5-alpine` without changing the Deployment name or replica count `2`.
3. Leave two updated replicas available. Do not mask the problem by reducing replicas to zero.

References: [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/) · [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### O05 · Repair readiness and restore Service traffic

**Intermediate · Practice target ~6 minutes · 5 criteria**

Namespace: `ckad-o05` · Workspace: `/workspace/o05`

1. Deployment `unready` is running nginx, but its readiness checks fail and Service `unready` has no ready backends.
2. Fix the existing HTTP readiness probe on container `web` to use path `/` on port `80`. Keep period `3`, both replicas, and the existing image.
3. Do not remove the readiness probe. Confirm that Pod `client` can get the nginx page from `http://unready`.

References: [Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/) · [Service](https://kubernetes.io/docs/concepts/services-networking/service/) · [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/)

### O06 · Capture live application resource usage

**Intermediate · Practice target ~5 minutes · 3 criteria**

Namespace: `ckad-o06` · Workspace: `/workspace/o06`

1. Pods `cpu-worker` and `idle` are already running. Use the resource metrics API through `kubectl top pods`.
2. Save their current Pod-level CPU and memory usage, without a header, to `/workspace/o06/usage.txt`. Include one row for each Pod and no other Pods.
3. Leave the Pods unchanged. Metrics may take a short interval to appear after first creation; missing metrics are not an invitation to invent values.

References: [Top](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_top/)

### O07 · Migrate removed API versions

**Advanced · Practice target ~9 minutes · 4 criteria**

Namespace: `ckad-o07` · Workspace: `/workspace/o07`

1. The starter file `/workspace/o07/legacy.yaml` uses removed Deployment and Ingress APIs. Edit that file; do not submit a second corrected file instead.
2. Migrate Deployment `legacy` to `apps/v1`, with an explicit selector `app=legacy` matching its Pod labels. Keep two replicas and nginx image `nginx:1.27.5-alpine`.
3. Migrate Ingress `legacy` to `networking.k8s.io/v1`, class `traefik`, host `legacy.ckad.test`, path `/`, path type `Prefix`, and backend Service `legacy` port `80`.
4. Apply the corrected file. The Service is already present. Leave the Deployment Ready.

Starter files: `legacy.yaml`.

References: [Deprecation](https://kubernetes.io/docs/reference/using-api/deprecation-guide/) · [Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) · [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)

### O08 · Fix a failed Secret key reference

**Intermediate · Practice target ~5 minutes · 4 criteria**

Namespace: `ckad-o08` · Workspace: `/workspace/o08`

1. Deployment `consumer` is stuck before its app container starts. Secret `api-token` already exists.
2. Inspect the failure and correct `APP_TOKEN` to reference the existing key `token` in Secret `api-token`.
3. Do not replace the reference with a literal, alter the Secret data, or remove the environment variable. Leave the one-replica Deployment available.

References: [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/) · [Secret](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/)

## Application Environment, Configuration and Security — 25%

### C01 · Inject ConfigMap values as environment variables

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-c01` · Workspace: `/workspace/c01`

1. Create ConfigMap `app-settings` with keys `APP_ENV=production` and `REGION=us-central`.
2. Create Pod `configured`, container `app`, image `busybox:1.37.0`, and a long-running sleep command.
3. Populate environment variables `APP_ENV` and `REGION` using individual `configMapKeyRef` entries referring to the corresponding keys. Do not use literal values or envFrom in this task.
4. Leave the Pod Ready, with both values available inside its container.

References: [Configmap](https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/)

### C02 · Project a ConfigMap key to a named file

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-c02` · Workspace: `/workspace/c02`

1. Create ConfigMap `file-settings` with key `app.json` containing `{"port":8080,"mode":"production"}`.
2. Create Pod `file-app`, container `app`, image `busybox:1.37.0`, kept running.
3. Mount a ConfigMap volume named `settings` read-only at `/etc/app`. Project key `app.json` specifically to filename `config.json`.
4. The file `/etc/app/config.json` inside the container must contain the supplied JSON.

References: [Configmap](https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/) · [Volume](https://kubernetes.io/docs/concepts/storage/volumes/)

### C03 · Create and consume a Secret

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-c03` · Workspace: `/workspace/c03`

1. Create an Opaque Secret named `credentials` with `username=ckad` and `password=practice-only-42`. These are fictional lab values.
2. Create Pod `secret-app`, container `app`, image `busybox:1.37.0`, kept running.
3. Use Secret key references to expose username as `DB_USER` and password as `DB_PASSWORD`. Do not put the literal credentials in the Pod spec.
4. Leave the Pod Ready and verify that the values are available to the process.

References: [Secret](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/)

### C04 · Mount a Secret with restrictive file permissions

**Intermediate · Practice target ~6 minutes · 6 criteria**

Namespace: `ckad-c04` · Workspace: `/workspace/c04`

1. Create Opaque Secret `db-auth` with key `password=mount-only-42`.
2. Create Pod `secret-file`, container `app`, image `busybox:1.37.0`, kept running as its default user.
3. Mount Secret volume `auth` read-only at `/run/auth`, with default file mode `0400` (decimal `256`).
4. Verify the projected `/run/auth/password` file is readable by the container and contains the supplied value.

References: [Secret](https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/)

### C05 · Assign a ServiceAccount without mounting its token

**Intermediate · Practice target ~5 minutes · 4 criteria**

Namespace: `ckad-c05` · Workspace: `/workspace/c05`

1. Create ServiceAccount `auditor`.
2. Create Pod `agent` with container `agent`, image `busybox:1.37.0`, and a long-running sleep command.
3. Set `serviceAccountName: auditor` and explicitly set Pod-level `automountServiceAccountToken: false`.
4. Leave the Pod Ready without a token file at `/var/run/secrets/kubernetes.io/serviceaccount/token`.

References: [Sa](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)

### C06 · Grant narrowly scoped application permissions

**Advanced · Practice target ~9 minutes · 11 criteria**

Namespace: `ckad-c06` · Workspace: `/workspace/c06`

1. Create ServiceAccount `reporter`, Role `pod-reader`, and RoleBinding `read-pods` in this task namespace.
2. The Role must allow get/list/watch of core API Pods and get of the core `pods/log` subresource.
3. Bind the Role to this namespace’s reporter ServiceAccount. Do not grant access to Secrets, permission to create/delete Pods, or Pod-reading privileges in namespace `default`.
4. Use impersonation with kubectl auth can-i to verify both allowed and denied operations.

References: [Rbac](https://kubernetes.io/docs/reference/access-authn-authz/rbac/) · [Sa](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)

### C07 · Set container resource requests and limits

**Intermediate · Practice target ~5 minutes · 6 criteria**

Namespace: `ckad-c07` · Workspace: `/workspace/c07`

1. Deployment `sized` already exists. Set resource requests on container `web` to CPU `100m` and memory `64Mi`.
2. Set resource limits to CPU `500m` and memory `128Mi`.
3. Keep two replicas and the existing image. Leave the rollout complete. Equivalent valid Kubernetes quantity representations are accepted.

References: [Resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)

### C08 · Apply namespace defaults and a resource budget

**Advanced · Practice target ~9 minutes · 15 criteria**

Namespace: `ckad-c08` · Workspace: `/workspace/c08`

1. Create LimitRange `container-defaults` for type `Container`: default requests CPU `100m`, memory `64Mi`; default limits CPU `500m`, memory `128Mi`.
2. Create ResourceQuota `namespace-budget` with hard limits: `requests.cpu=1`, `requests.memory=512Mi`, `limits.cpu=2`, `limits.memory=1Gi`, and `pods=5`.
3. After those policies exist, create Pod `defaults`, container `client`, image `busybox:1.37.0`, sleeping for a long time. Do not specify resources in your submitted Pod manifest.
4. Verify that admission filled in its requests and limits, and leave the Pod Ready.

References: [Limitrange](https://kubernetes.io/docs/concepts/policy/limit-range/) · [Quota](https://kubernetes.io/docs/concepts/policy/resource-quotas/) · [Resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)

### C09 · Harden a container while preserving writable scratch space

**Advanced · Practice target ~9 minutes · 6 criteria**

Namespace: `ckad-c09` · Workspace: `/workspace/c09`

1. Create Pod `hardened`, container `app`, image `busybox:1.37.0`, kept running.
2. At Pod level set runAsNonRoot true, UID `1000`, primary GID `3000`, fsGroup `2000`, and seccomp profile `RuntimeDefault`.
3. At container level disallow privilege escalation, drop all Linux capabilities, and make the root filesystem read-only.
4. Mount emptyDir `tmp` at `/tmp`. Write `writable` to `/tmp/check` and keep the application running with the requested identity.

References: [Security](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) · [Volume](https://kubernetes.io/docs/concepts/storage/volumes/)

### C10 · Meet a restricted Pod Security admission policy

**Advanced · Practice target ~8 minutes · 4 criteria**

Namespace: `ckad-c10` · Workspace: `/workspace/c10`

1. Label this namespace to enforce Pod Security level `restricted` at policy version `v1.35`.
2. Create Pod `restricted-app`, container `app`, image `busybox:1.37.0`, and a long-running sleep command.
3. Use non-root UID `1000`, runAsNonRoot true, RuntimeDefault seccomp, allowPrivilegeEscalation false, and drop ALL capabilities so the Pod is admitted.
4. Leave the namespace policy active and the Pod Ready. Do not weaken the policy to make the Pod run.

References: [Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/) · [Security](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)

### C11 · Discover a custom API and drive its operator

**Intermediate · Practice target ~7 minutes · 4 criteria**

Namespace: `ckad-c11` · Workspace: `/workspace/c11`

1. A namespaced custom API `widgets.practice.ckad.local` is installed, with version `v1`. Discover it with kubectl api-resources and kubectl explain.
2. Create a `Widget` named `gallery` with `spec.replicas: 2` and `spec.image: nginx:1.27.5-alpine`.
3. The provided lab operator reconciles each Widget into Deployment `widget-<name>`. Leave `widget-gallery` with two available replicas.
4. Manage the Widget, not the generated Deployment. Do not alter or delete the cluster-wide CRD. This is a deliberately small, real training controller, not a production operator.

References: [Crd](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/) · [Operator](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/)

### C12 · Expose Pod identity with the Downward API

**Intermediate · Practice target ~6 minutes · 5 criteria**

Namespace: `ckad-c12` · Workspace: `/workspace/c12`

1. Create Pod `identity`, container `app`, image `busybox:1.37.0`, kept running.
2. Populate `MY_POD_NAME` through a fieldRef to `metadata.name`, not a literal string.
3. Use a downwardAPI volume named `meta` with an item named `namespace` referencing `metadata.namespace`. Mount it read-only at `/meta`.
4. Verify that the process sees MY_POD_NAME=identity and that `/meta/namespace` contains this task namespace.

References: [Downward](https://kubernetes.io/docs/tasks/inject-data-application/downward-api-volume-expose-pod-information/)

## Services and Networking — 20%

### N01 · Expose an application with ClusterIP

**Intermediate · Practice target ~5 minutes · 3 criteria**

Namespace: `ckad-n01` · Workspace: `/workspace/n01`

1. Deployment `web` runs two Pods listening on container port `8080`, with Pod label `app=web`.
2. Create Service `web` of type `ClusterIP`, selecting `app=web`, with TCP Service port `80` and target port `8080`.
3. Keep the Deployment unchanged. From Pod `client`, verify that `http://web` returns CLUSTERIP OK.

References: [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### N02 · Expose a NodePort on both nodes

**Intermediate · Practice target ~6 minutes · 4 criteria**

Namespace: `ckad-n02` · Workspace: `/workspace/n02`

1. Deployment `gateway` listens on `8080` and has label `app=gateway`.
2. Create Service `gateway` with `type: NodePort`, TCP `port: 80`, `targetPort: 8080`, and `nodePort: 30080`. Select `app=gateway`.
3. Verify `curl http://cluster:30080` and `curl http://worker:30080` from this terminal. Both should return NODEPORT OK.
4. Do not try to create a second ClusterIP Service. The NodePort Service receives its own ClusterIP automatically.

References: [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### N03 · Resolve a named targetPort

**Intermediate · Practice target ~5 minutes · 3 criteria**

Namespace: `ckad-n03` · Workspace: `/workspace/n03`

1. Deployment `named-web` declares a container port named `http` with numeric port `8080`.
2. Create ClusterIP Service `named-web` selecting `app=named-web`, exposing Service port `9090`, with the literal named targetPort `http`.
3. Keep the workload unchanged. Verify from Pod `client` that `http://named-web:9090` returns NAMED PORT OK.

References: [Service](https://kubernetes.io/docs/concepts/services-networking/service/)

### N04 · Troubleshoot an empty Service endpoint set

**Intermediate · Practice target ~5 minutes · 4 criteria**

Namespace: `ckad-n04` · Workspace: `/workspace/n04`

1. Deployment `catalog` is healthy but Service `catalog` has no working backends. Inspect labels, the Service selector, and EndpointSlices.
2. Fix the Service selector to exactly `app=catalog`, leaving Service port `80` and target port `8080`.
3. Do not modify the Deployment. Verify from Pod `client` that `http://catalog` returns CATALOG OK.

References: [Service](https://kubernetes.io/docs/concepts/services-networking/service/) · [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/)

### N05 · Repair a Service target port

**Intermediate · Practice target ~5 minutes · 3 criteria**

Namespace: `ckad-n05` · Workspace: `/workspace/n05`

1. Service `payments` selects the correct Pods, but requests fail. The application is listening on `8080`.
2. Fix only the Service targetPort to `8080`; preserve type ClusterIP, selector `app=payments`, and Service port `80`.
3. Keep the Deployment unchanged. Verify `http://payments` from Pod `client` returns PAYMENTS OK.

References: [Service](https://kubernetes.io/docs/concepts/services-networking/service/) · [Debug](https://kubernetes.io/docs/tasks/debug/debug-application/)

### N06 · Route an HTTP hostname through Ingress

**Intermediate · Practice target ~7 minutes · 2 criteria**

Namespace: `ckad-n06` · Workspace: `/workspace/n06`

1. Deployment and Service `portal` are ready. The Service exposes port `80`. The lab has a real Traefik Ingress controller and IngressClass `traefik`.
2. Create networking.k8s.io/v1 Ingress `portal`, class `traefik`, host `portal.ckad.test`, and path `/` with pathType `Prefix`.
3. Route to Service `portal` port `80`. Verify from the terminal with `curl -H "Host: portal.ckad.test" http://cluster/` and expect PORTAL OK.

References: [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)

### N07 · Route different paths to different applications

**Advanced · Practice target ~8 minutes · 3 criteria**

Namespace: `ckad-n07` · Workspace: `/workspace/n07`

1. Services `red` and `blue` expose their corresponding applications on port `80`. They already serve pages under `/red/` and `/blue/` respectively.
2. Create Ingress `colors`, class `traefik`, host `colors.ckad.test`.
3. Use Prefix path `/red` to Service `red:80` and Prefix path `/blue` to Service `blue:80`. Do not add rewrite annotations or change the applications.
4. Verify both paths using a Host header from the terminal. Expect RED ROUTE and BLUE ROUTE respectively.

References: [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)

### N08 · Deny inbound traffic and allow one application tier

**Advanced · Practice target ~9 minutes · 7 criteria**

Namespace: `ckad-n08` · Workspace: `/workspace/n08`

1. Pods `backend`, `frontend`, and `outsider` are provided. Do not modify their labels, images, commands, or security settings.
2. Create NetworkPolicy `default-deny` selecting all Pods and denying all ingress in this namespace. Do not restrict egress.
3. Create NetworkPolicy `allow-frontend` selecting `app=backend`. Permit ingress only from Pods labeled `role=frontend` in this same namespace, on TCP `8080`.
4. Verify frontend can reach backend’s Pod IP on 8080 while outsider cannot. The lab actually enforces NetworkPolicies.

References: [Networkpolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

### N09 · Combine namespace and Pod selectors with AND

**Advanced · Practice target ~10 minutes · 10 criteria**

Namespace: `ckad-n09` · Workspace: `/workspace/n09`

1. The backend Pod in this task namespace listens on 8080. Namespace `ckad-n09-trusted` is labeled `team=finance`; namespace `ckad-n09-foreign` is labeled `team=engineering`.
2. Create NetworkPolicy `finance-clients` selecting `app=backend`. Allow only TCP `8080` from Pods labeled `role=client` in namespaces labeled `team=finance`.
3. Both selectors must apply to the same source peer (AND), not separate peers (OR). Preserve all fixture Pods and namespace labels.
4. The trusted good-client must connect. The trusted wrong-role Pod and foreign foreign-client Pod must both be blocked.

References: [Networkpolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)

### N10 · Restrict egress without breaking cluster DNS

**Advanced · Practice target ~10 minutes · 6 criteria**

Namespace: `ckad-n10` · Workspace: `/workspace/n10`

1. Pods `client`, `backend`, and `unrelated`, plus Service `backend:8080`, are provided. Preserve these fixtures.
2. Create NetworkPolicy `restrict-client` selecting `role=client` and isolating its egress only.
3. Allow TCP 8080 to Pods labeled `app=backend` in this namespace. Also allow UDP and TCP port 53 to Pods labeled `k8s-app=kube-dns` in namespace `kube-system`, selected with `kubernetes.io/metadata.name=kube-system`.
4. Permit no other egress. The client must resolve and fetch `http://backend:8080`, but must not reach unrelated’s Pod IP on 8080.

References: [Networkpolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/) · [Service](https://kubernetes.io/docs/concepts/services-networking/service/)
