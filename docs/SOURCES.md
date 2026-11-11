# Research and source notes

Checked September 14, 2026. These are public preparation resources; none of the questions in this project are represented as actual exam questions.

## Exam blueprint and policies

**Linux Foundation — CKAD certification page**
https://training.linuxfoundation.org/certification/certified-kubernetes-application-developer-ckad/

Used for the current five domains and weights, the listed Kubernetes v1.35 target, and the two-hour practical format. The weights are 20% design/build, 20% deployment, 15% observability/maintenance, 25% environment/configuration/security, and 20% services/networking. The question bank's exact tasks, task count, equal-task mock rubric, fixtures, and solutions are our own design.

**Linux Foundation — CKA/CKAD/CKS FAQ**
https://docs.linuxfoundation.org/tc-docs/certification/faq-cka-ckad-cks

Cross-checked the currently listed Kubernetes version, duration, and CKAD pass reference of 66%. Simulator entitlements depend on the registration product; do not assume every purchase has identical inclusions. Check your candidate portal.

**Linux Foundation — exam tips**
https://docs.linuxfoundation.org/tc-docs/certification/tips-cka-and-ckad

Used to understand the published hands-on task format. This app's fixed 20-task mock is a practice choice, not a promise about your scheduled exam's count.

**Linux Foundation — allowed resources**
https://docs.linuxfoundation.org/tc-docs/certification/certification-resources-allowed

The authoritative place to check permitted documentation and restrictions. The app's study links are intentionally labeled as study references. Do not assume an external link is permitted in the actual exam.

**CNCF — curriculum repository**
https://github.com/cncf/curriculum

The certification page links here. The detailed official website competency text was used as the readable blueprint; this project does not claim an independent successful parse of the linked curriculum PDF.

## Implementation references

**K3s v1.35 release notes**
https://docs.k3s.io/release-notes/v1.35.X

The published table lists v1.35.8+k3s1 with Kubernetes v1.35.8, released August 27, 2026. That informed the pinned server and kubectl versions. The exact image/tool downloads could not be exercised in the creation environment.

**K3s networking services**
https://docs.k3s.io/networking/networking-services

Used for bundled DNS, Traefik, service routing and NetworkPolicy behavior. A policy API accepting YAML is insufficient evidence of enforcement; startup actually probes allowed, blocked, and restored traffic.

**Docker Engine 28 release notes**
https://docs.docker.com/engine/release-notes/28/

Docker 28.5.2 was chosen over 28.5.1 because the 28.5.2 notes identify container-runtime security fixes. The isolated builder is still a privileged training environment, not a hardened service or a claim of current security certification.

**Official Kubernetes documentation**
https://kubernetes.io/docs/

Every question has topic-specific official references. The catalog includes the complete per-task links. Particularly important: Service port/targetPort/nodePort behavior, NetworkPolicy peer selection and additivity, probe semantics, Secret projection, resource quantities, and stable API schemas.

**Official Helm documentation**
https://helm.sh/docs/

Used for local-chart installation, upgrades, rollback revisions, and release-state inspection. A local chart is bundled so practice does not depend on a changing third-party chart.

**Docker image build/save documentation**
https://docs.docker.com/build/concepts/dockerfile/
https://docs.docker.com/reference/cli/docker/image/save/

Used for the two real image-lifecycle exercises, including the distinction between saving an image and exporting a container filesystem.

**xterm.js documentation**
https://xtermjs.org/docs/guides/using-addons/

Used for the terminal frontend and fitting behavior. The locally bundled xterm/FitAddon build is distributed with its provenance and license notices in `app/static/vendor/`.

## Community preparation cross-check

https://github.com/dgkanatsios/CKAD-exercises

Reviewed as an example of hands-on preparation structure. Its README showed an older domain-weight breakdown during research, so those weights were not used as the current exam blueprint. No exercise bank was copied into this application.

## Focused 16 scenario objectives

https://github.com/aravind4799/CKAD-Practice-Questions

Reviewed September 25 and October 1, 2026. Credit to aravind4799 and the repository’s contributors for the ordered set of 16 public study questions. Flightdeck’s `s01`–`s16` now use the source questions’ resource names, stated values, and required outcomes in the same order; the prompts and working fixtures are independently written for this lab. A license file was not present in the reviewed repository listing. This distribution does not copy its README, solution blocks, or setup files. Obtain appropriate permission before separately redistributing upstream files.

Adaptations for this lab:

- Dedicated `ckad-sNN` namespaces and `/workspace/sNN` folders replace shared `default`, `audit`, `monitoring`, `network-demo`, `prod`, and `/root` paths. Several source questions reuse object names, so keeping them in their original namespaces would make concurrent mock questions conflict.
- Where the source requires `busybox:latest` or `nginx:latest`, those exact tags are used; otherwise the lab uses working starter images. The API-reader fixtures use `python:3.13.7-slim-bookworm`, with TLS verification against the cluster CA and no credential logging.
- The CronJob manual test Job is optional, as in the upstream solution. The image exercise uses the source’s documented Docker alternative in an isolated builder, not an emulated Podman command.
- Authorization errors come from actual Kubernetes API requests. Existing Pods must be recreated when changing their immutable ServiceAccount selection; the source’s ServiceAccount, Role, RoleBinding, and Pod names are retained.
- The readiness fixture really serves `/ready` on port 8080. The security-context fixture runs a BusyBox workload that can operate under UID 1000; NET_ADMIN is confined to this disposable exercise.
- Canary grading checks the source’s 8:2 endpoint pool, not a guaranteed request percentage. NetworkPolicy repair uses the source’s Pod/policy names and labels, with positive and negative traffic checks.
- Rollback grading checks the source’s `nginx:1.20` and `nginx:1.25` versions in owned ReplicaSet history and a later revision, as well as the final healthy image. It does not claim to reconstruct every intermediate shell command.
- The original `web.example.com` host is sent as a Host header to the installed Traefik controller. The NodePort question accepts any assigned port; the invalid-pathType question accepts Prefix, Exact, or ImplementationSpecific if `/api` routes successfully.
- The quota fixture uses the source’s example 2 CPU/4Gi budget. CPU/memory limits must equal half, while requests can be any valid quantities at or above the source’s minimums.

Focused mocks include all 16 scenarios with equal task weighting, not the official curriculum distribution. Source links and all other study aids are unavailable during active mocks.

## How to interpret accuracy

The prompts were authored to match the researched topic areas, not reverse-engineered from private exam content. Public facts such as Kubernetes version and permitted resources may change. Local fixture behavior depends on the actual container stack and host. Run the all-question live self-test, keep its report, and use current official resources alongside this bank. Passing this practice bank is not a certification pass guarantee.
