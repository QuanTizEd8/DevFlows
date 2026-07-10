# Base image is digest-pinned for a reproducible toolchain root. The digest is the
# multi-arch manifest-list digest for ubuntu:26.04, so it still resolves to the
# correct per-architecture image on amd64 and arm64.
FROM ubuntu:26.04@sha256:b7f48194d4d8b763a478a621cdc81c27be222ba2206ca3ca6bc42b49685f3d9e

# gitleaks is DevFlows' one lint tool that pixi cannot provide (no conda-forge and
# no real PyPI distribution — it is a standalone Go release). Install it here as
# pinned devcontainer infrastructure so the secret scan in `task lint` and the
# pre-commit hook run in CI and inside the container. Everything else comes from
# pixi (see pixi.toml).
ARG GITLEAKS_VERSION=8.18.4
RUN set -eux; \
  apt-get update; \
  apt-get install -y --no-install-recommends ca-certificates curl; \
  rm -rf /var/lib/apt/lists/*; \
  arch="$(dpkg --print-architecture)"; \
  case "$arch" in \
  amd64) gl_arch=x64; gl_sha=ba6dbb656933921c775ee5a2d1c13a91046e7952e9d919f9bac4cec61d628e7d ;; \
  arm64) gl_arch=arm64; gl_sha=bf5f7f466ebfade1296c8bd32cf7d3f592c2aa78836aa9980ffbe2cadca7a861 ;; \
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac; \
  curl -fsSL -o /tmp/gitleaks.tar.gz \
  "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gl_arch}.tar.gz"; \
  echo "${gl_sha}  /tmp/gitleaks.tar.gz" | sha256sum -c -; \
  tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks; \
  rm -f /tmp/gitleaks.tar.gz; \
  chmod +x /usr/local/bin/gitleaks; \
  gitleaks version
