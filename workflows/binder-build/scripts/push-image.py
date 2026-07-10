"""Environment-gated push, digest capture, and reproducibility Dockerfile (push job).

Loads the byte-identical OCI archive the build job produced (no rebuild, no TOCTOU:
the pushed image is the built image), tags it with each image-tags entry (plus an
optional commit-SHA tag), pushes them, and captures the immutable registry manifest
digest from RepoDigests. Emits image-ref and image-digest, and -- when enabled --
writes a one-line Dockerfile pinning the exact pushed image by digest.

Self-contained (no shared-module import) so the credentialed job's inlined footprint
stays lean. The registry credential never reaches this script: docker/login-action
authenticated the daemon on its own isolated step before this runs.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path


def main() -> int:
    image_name = os.environ["IMAGE_NAME"].strip()
    build_tag = os.environ["IMAGE_BUILD_TAG"].strip()
    tags = [line.strip() for line in os.environ["IMAGE_TAGS"].splitlines() if line.strip()]
    if not tags:
        raise SystemExit("image-tags resolved to an empty list; nothing to push.")

    archive = os.environ["IMAGE_ARCHIVE"]
    subprocess.run(["docker", "load", "-i", archive], check=True)

    local_ref = f"{image_name}:{build_tag}"
    pushed_refs: list[str] = []
    for tag in tags:
        pushed_refs.append(_tag_and_push(local_ref, f"{image_name}:{tag}"))
    if _bool("IMAGE_SHA_TAG_ENABLED"):
        prefix = os.environ["IMAGE_SHA_TAG_PREFIX"].strip()
        _tag_and_push(local_ref, f"{image_name}:{prefix}{os.environ['GITHUB_SHA'].strip()}")

    digest = _capture_digest(local_ref, image_name)
    image_ref = pushed_refs[0]
    _emit_output("image-ref", image_ref)
    _emit_output("image-digest", digest)
    print(f"Pushed {image_ref} at digest {digest}.")

    if _bool("DOCKERFILE_ARTIFACT_ENABLED"):
        dockerfile = Path(os.environ["DOCKERFILE_PATH"])
        dockerfile.parent.mkdir(parents=True, exist_ok=True)
        dockerfile.write_text(f"FROM {image_name}@{digest}\n", encoding="utf-8")
        print(f"Wrote reproducibility Dockerfile pinning {image_name}@{digest}.")
    return 0


def _tag_and_push(local_ref: str, ref: str) -> str:
    subprocess.run(["docker", "tag", local_ref, ref], check=True)
    subprocess.run(["docker", "push", ref], check=True)
    return ref


def _capture_digest(local_ref: str, image_name: str) -> str:
    """Immutable registry manifest digest (sha256:...) from RepoDigests after push."""
    raw = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", local_ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    repo_digests = json.loads(raw) if raw else []
    for entry in repo_digests:
        name, _, digest = str(entry).partition("@")
        if name == image_name and digest.startswith("sha256:"):
            return digest
    # Fallback: any sha256 digest present (all pushed tags share one manifest).
    for entry in repo_digests:
        _, _, digest = str(entry).partition("@")
        if digest.startswith("sha256:"):
            return digest
    raise SystemExit(
        f"Could not read a registry manifest digest for {image_name} from RepoDigests {raw!r}; "
        "the push may not have completed."
    )


def _emit_output(name: str, value: str) -> None:
    # Random-delimiter heredoc so a value can never inject additional GITHUB_OUTPUT keys.
    delimiter = f"devflows_{secrets.token_hex(16)}"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
