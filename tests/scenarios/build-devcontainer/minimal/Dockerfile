# Minimal devcontainer for the build-devcontainer build-only e2e scenario.
# Alpine keeps the hosted-runner build fast and needs no registry credentials.
#
# Flake mode: this base image is pulled anonymously from docker.io, which applies
# a per-IP pull rate limit on shared hosted-runner egress. A burst of scenario
# runs can therefore flake with a "toomanyrequests" pull error. Mirroring the
# base image to GHCR (authenticated, unthrottled) would remove this; that is
# future work and is intentionally NOT implemented here.
FROM alpine:3.20
