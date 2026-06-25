FROM jdxcode/mise:latest AS mise

FROM codercom/enterprise-base:ubuntu

USER root
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gnupg \
    gzip \
    python3 \
    tar \
    unzip \
    xz-utils \
  && rm -rf /var/lib/apt/lists/*

COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise
COPY --chown=coder:coder scripts /opt/coder-hapi/scripts
RUN chmod +x /opt/coder-hapi/scripts/*.sh /opt/coder-hapi/scripts/*.py

ENV PATH="/home/coder/.local/bin:/home/coder/.local/share/mise/shims:${PATH}"

USER coder
RUN mkdir -p /home/coder/project /home/coder/.local/bin /home/coder/.config/coder-hapi /home/coder/.hapi
WORKDIR /home/coder/project
