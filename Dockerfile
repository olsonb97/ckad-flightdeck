# syntax=docker/dockerfile:1
FROM docker:28.5.2-cli AS docker-tools
FROM python:3.13-slim-bookworm
ARG TARGETARCH
ARG KUBECTL_VERSION=v1.35.8
ARG HELM_VERSION=v3.19.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EDITOR=vim KUBE_EDITOR=vim TERM=xterm-256color
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash bash-completion ca-certificates curl git jq less nano procps tini vim wget \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker-tools /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-tools /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
RUN set -eux; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in amd64|arm64) ;; *) echo "This image supports amd64 and arm64 only" >&2; exit 1;; esac; \
    cd /tmp; \
    curl --retry 4 -fsSLo kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"; \
    curl --retry 4 -fsSLo kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${arch}/kubectl.sha256"; \
    printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum -c -; \
    install -m 0755 kubectl /usr/local/bin/kubectl; \
    archive="helm-${HELM_VERSION}-linux-${arch}.tar.gz"; \
    curl --retry 4 -fsSLO "https://get.helm.sh/${archive}"; \
    curl --retry 4 -fsSLo helm.sha256 "https://get.helm.sh/${archive}.sha256sum"; \
    sha256sum -c helm.sha256; \
    tar -xzf "$archive"; \
    install -m 0755 "linux-${arch}/helm" /usr/local/bin/helm; \
    rm -rf /tmp/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/
COPY tests/ /app/tests/
RUN mkdir -p /workspace /data && kubectl completion bash > /etc/bash_completion.d/kubectl \
    && printf 'set number\nset expandtab\nset tabstop=2\nset shiftwidth=2\nset autoindent\n' > /etc/vim/vimrc.local
EXPOSE 8080
CMD ["python", "/app/server.py"]
