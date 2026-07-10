"""Credential-free repo2docker build (build-binder job).

Runs jupyter-repo2docker (pinned via uvx) with --no-run --image-name into the local
Docker daemon, building the caller's UNTRUSTED repository contents. Holds no registry
credential and no id-token. Writes a build-only proof (the local image config digest)
so a vacuous/no-op build fails the job, and -- only when NOT dry-run -- saves the image
to an OCI archive for the isolated push job to load byte-identically.

The repo2docker argv is built from the environment only (never shell-interpolated) and
repo2docker-arguments is re-parsed through the SAME strict allowlist the validate job
used, so no owned flag can slip into the build.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import parsing


def main() -> int:
    image_name = parsing.validate_image_name(os.environ["IMAGE_NAME"])
    version = parsing.validate_version(
        os.environ["REPO2DOCKER_VERSION"], field="repo2docker-version"
    )
    relative_source = parsing.validate_source_path(
        os.environ["REPO2DOCKER_SOURCE_PATH"], field="repo2docker-source-path"
    )
    extra_args = parsing.parse_repo2docker_arguments(
        os.environ.get("REPO2DOCKER_ARGUMENTS", ""), field="repo2docker-arguments"
    )

    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    source = (workspace / relative_source).resolve()
    if source != workspace and workspace not in source.parents:
        raise SystemExit("repo2docker-source-path must stay inside GITHUB_WORKSPACE.")
    if not source.is_dir():
        raise SystemExit(f"repo2docker-source-path does not exist: {relative_source}")

    local_ref = f"{image_name}:{parsing.INTERNAL_BUILD_TAG}"
    command = [
        "uvx",
        "--from",
        f"jupyter-repo2docker=={version}",
        "jupyter-repo2docker",
        "--no-run",
        "--image-name",
        local_ref,
        *extra_args,
        str(source),
    ]
    print("Building Binder image with:", " ".join(command))
    subprocess.run(command, check=True)

    _write_proof(local_ref)
    if not _bool("PUBLISH_DRY_RUN_ENABLED"):
        _save_archive(local_ref)
    return 0


def _write_proof(local_ref: str) -> None:
    """Record the locally-built image config digest so a no-op build cannot pass."""
    image_id = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", local_ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not image_id.startswith("sha256:"):
        raise SystemExit(f"Unexpected image id from docker inspect: {image_id!r}.")
    proof_dir = Path(os.environ["PROOF_DIR"])
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / "image-id").write_text(image_id + "\n", encoding="utf-8")
    print(f"Built {local_ref} with config digest {image_id}.")


def _save_archive(local_ref: str) -> None:
    archive_dir = Path(os.environ["ARCHIVE_DIR"])
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / "image.tar"
    subprocess.run(["docker", "save", "-o", str(archive), local_ref], check=True)
    print(f"Saved {local_ref} to {archive} for the push job.")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
