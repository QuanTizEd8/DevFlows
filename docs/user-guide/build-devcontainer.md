# Build Devcontainer

Use `build-devcontainer` to build one or more platform-specific devcontainer
images and optionally merge them into a multi-arch image tag.

## Basic Call

```yaml
permissions:
  # build-devcontainer declares actions: read, contents: read, and
  # packages: write at the workflow level; GitHub validates these nested
  # permissions before the run starts, so the caller must grant the full union.
  actions: read
  contents: read
  packages: write

jobs:
  build-devcontainer:
    # Replace build-devcontainer/v0.1.0 with the latest released tag; moving
    # major tags (build-devcontainer/v1) do not exist during the 0.x series.
    uses: QuanTizEd8/DevFlows/.github/workflows/build-devcontainer.yaml@build-devcontainer/v0.1.0
    with:
      image-name: ghcr.io/owner/project-devcontainer
      image-tag: latest
      image-sha-tag-enabled: true
      build-matrix: |
        [
          {
            "runner": "ubuntu-latest",
            "platform": "linux/amd64",
            "platform_tag": "linux-amd64"
          }
        ]
    secrets:
      docker-password: ${{ secrets.GITHUB_TOKEN }}
```

## Build Matrix

`build-matrix` is JSON because GitHub reusable workflow inputs do not support
arrays or objects. Each entry must include:

- `runner`: GitHub Actions runner label.
- `platform`: Docker platform passed to `devcontainers/ci`.
- `platform_tag`: suffix used for the per-platform image tag.

For example, `image-tag: latest` and `platform_tag: linux-amd64` produces a
platform image tag ending in `latest-linux-amd64`. The merge job then publishes
the multi-arch `latest` tag from those per-platform images.

## Build-Only Mode

For validation runs that should not push images, set both:

```yaml
with:
  devcontainer-push: never
  merge-enabled: false
```

The merge job requires pushed platform images. If `merge-enabled` is true and
`devcontainer-push` does not publish the platform tags, the merge job cannot
create the multi-arch manifest.

## Prepare Command

Use `prepare-command` for trusted repository-specific setup after checkout and
artifact download:

```yaml
with:
  prepare-command: |
    ./scripts/prepare-devcontainer-build.sh
```

This replaces project-specific setup that older copied workflows hardcoded.
