from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

# devcontainers/ci exports a single-platform build to an OCI archive at this
# fixed path (buildxOutput = 'type=oci,dest=/tmp/output.tar' whenever a platform
# is set and useNativeRunner is false) instead of loading it into the local
# Docker daemon. The path is hard-coded in the pinned action
# (devcontainers/ci@513af61f4de4f75d37e4438f184ba4358f0fc1ca); revisit this
# default if that pin changes. The workflow passes DIGEST_OCI_ARCHIVE explicitly
# so the coupling is visible at the call site.
DEFAULT_OCI_ARCHIVE = "/tmp/output.tar"


def main() -> int:
    image = _required("IMAGE_NAME")
    tag = _required("IMAGE_TAG")
    platform_tag = _required("MATRIX_PLATFORM_TAG")
    digest_dir = Path(_required("DIGEST_DIR"))
    source = os.environ.get("DIGEST_SOURCE", "registry").strip().lower()

    ref = f"{image}:{tag}-{platform_tag}"
    if source == "oci":
        archive = os.environ.get("DIGEST_OCI_ARCHIVE", "").strip() or DEFAULT_OCI_ARCHIVE
        digest = _oci_archive_digest(Path(archive))
    else:
        digest = _inspect_digest(ref)

    digest_dir.mkdir(parents=True, exist_ok=True)
    # File name is the platform_tag so the merge job can pair each digest with
    # its expected matrix entry; the content is the immutable manifest digest.
    (digest_dir / platform_tag).write_text(digest + "\n", encoding="utf-8")
    print(f"{ref} -> {image}@{digest}")
    return 0


def _oci_archive_digest(archive: Path) -> str:
    """Return the image manifest digest from an exported OCI archive.

    Build-only validation never pushes, so there is no registry manifest to read,
    and with push=never devcontainers/ci exports the build to an OCI archive
    rather than loading it into the local Docker daemon (``docker image inspect``
    therefore fails outright). We read the manifest digest straight out of the
    archive's ``index.json`` -- credential-free, hosted-runner safe, and exactly
    the value BuildKit reports as ``exporting manifest sha256:...``.

    The archive only exists when a build actually produced an image, so a missing
    archive is a hard error: a silently no-op build (e.g. devcontainers/ci
    warning that skopeo is missing and returning without building) leaves nothing
    to read here, and the scenario asserting on this digest must fail rather than
    pass vacuously.
    """
    if not archive.is_file():
        raise SystemExit(
            f"OCI archive not found at {archive}: the devcontainer build produced no "
            "image (a silent no-op build, e.g. devcontainers/ci warning that skopeo "
            "is missing)."
        )
    index = _read_oci_index(archive)
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        raise SystemExit(f"OCI archive {archive} index.json lists no manifests.")
    image_manifests = [m for m in manifests if _is_image_manifest(m)]
    if len(image_manifests) != 1:
        raise SystemExit(
            f"expected exactly one image manifest in {archive}, found {len(image_manifests)}."
        )
    digest = str(image_manifests[0].get("digest", "")).strip()
    if not digest.startswith("sha256:"):
        raise SystemExit(f"unexpected manifest digest in {archive}: {digest!r}")
    return digest


def _read_oci_index(archive: Path) -> dict[str, Any]:
    with tarfile.open(archive, mode="r:*") as tar:
        member = next(
            (
                m
                for m in tar.getmembers()
                if m.isfile() and m.name in ("index.json", "./index.json")
            ),
            None,
        )
        if member is None:
            raise SystemExit(f"OCI archive {archive} is missing index.json.")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise SystemExit(f"OCI archive {archive} index.json is not a regular file.")
        with extracted:
            return json.loads(extracted.read().decode("utf-8"))


def _is_image_manifest(manifest: Any) -> bool:
    """Skip attestation/provenance manifests BuildKit may add beside the image."""
    if not isinstance(manifest, dict):
        return False
    annotations = manifest.get("annotations") or {}
    if annotations.get("vnd.docker.reference.type") == "attestation-manifest":
        return False
    platform = manifest.get("platform") or {}
    return platform.get("architecture") != "unknown" and platform.get("os") != "unknown"


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
