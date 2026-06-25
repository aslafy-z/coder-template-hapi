FROM jdxcode/mise:latest AS mise

FROM codercom/enterprise-base:ubuntu

USER root
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gzip \
    tar \
    unzip \
    xz-utils \
  && rm -rf /var/lib/apt/lists/*

COPY --from=mise /usr/local/bin/mise /usr/local/bin/mise

ENV PATH="/home/coder/.local/bin:/home/coder/.local/share/mise/shims:${PATH}"

USER coder
RUN mkdir -p /home/coder/project /home/coder/.local/bin /home/coder/.config/coder-hapi /home/coder/.hapi
WORKDIR /home/coder/project
