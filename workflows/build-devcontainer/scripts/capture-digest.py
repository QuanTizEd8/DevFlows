from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def main() -> int:
    image = _required("IMAGE_NAME")
    tag = _required("IMAGE_TAG")
    platform_tag = _required("MATRIX_PLATFORM_TAG")
    digest_dir = Path(_required("DIGEST_DIR"))
    source = os.environ.get("DIGEST_SOURCE", "registry").strip().lower()

    ref = f"{image}:{tag}-{platform_tag}"
    digest = _inspect_local_digest(ref) if source == "local" else _inspect_digest(ref)

    digest_dir.mkdir(parents=True, exist_ok=True)
    # File name is the platform_tag so the merge job can pair each digest with
    # its expected matrix entry; the content is the immutable manifest digest.
    (digest_dir / platform_tag).write_text(digest + "\n", encoding="utf-8")
    print(f"{ref} -> {image}@{digest}")
    return 0


def _inspect_local_digest(ref: str) -> str:
    """Return the config digest of a locally-built (unpushed) image.

    Build-only validation never pushes, so there is no registry manifest to read.
    ``docker image inspect`` reads the image the build loaded into the local
    daemon and fails outright if it does not exist — which is exactly the signal
    a build-only scenario needs: a silently no-op build (e.g. devcontainers/ci
    warning that skopeo is missing) leaves nothing to inspect, so this fails
    rather than letting a vacuous scenario pass.
    """
    result = subprocess.run(
        ["docker", "image", "inspect", ref, "--format", "{{.Id}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    digest = result.stdout.strip()
    if not digest.startswith("sha256:"):
        raise SystemExit(f"unexpected local image id for {ref}: {digest!r}")
    return digest


def _inspect_digest(ref: str) -> str:
    """Return the manifest digest of the just-pushed per-platform image.

    Merging the multi-arch manifest from immutable digests (rather than the
    mutable per-platform tag re-read at merge time) prevents concurrent runs
    from publishing mixed-commit or stale manifests.
    """
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        manifest = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"could not parse imagetools output for {ref}: {error}") from error
    digest = str(manifest.get("digest", "")).strip()
    if not digest.startswith("sha256:"):
        raise SystemExit(f"unexpected manifest digest for {ref}: {digest!r}")
    return digest


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
