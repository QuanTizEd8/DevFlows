from __future__ import annotations

import json
import os
import re

# A single Docker tag token; matches binder-build's tag grammar so the two
# workflows accept exactly the same set of tags for the shared image-tags input.
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def main() -> int:
    _validate_matrix(json.loads(_required("BUILD_MATRIX")))
    _validate_token_scope()
    _emit_primary_tag(_resolve_primary_tag())
    return 0


def _resolve_primary_tag() -> str:
    """Validate the image-tags newline list and return its first (primary) tag.

    image-tags is a newline-separated list; every line is applied to the merged
    multi-arch manifest, and the first (primary) tag also names the per-platform
    staging images and the image-ref output. Validate it here, in the pre-build
    validate job, so a malformed tag fails fast before any image is built.
    """
    raw = os.environ.get("IMAGE_TAGS", "")
    tags = [line.strip() for line in raw.splitlines() if line.strip()]
    if not tags:
        raise SystemExit("image-tags must resolve to a non-empty newline-separated list of tags.")
    for tag in tags:
        if not _TAG_RE.match(tag):
            raise SystemExit(f"image-tags contains an invalid Docker tag {tag!r}.")
    return tags[0]


def _emit_primary_tag(primary_tag: str) -> None:
    """Expose the primary tag as a job output for the build and merge jobs.

    The build step's per-platform staging tag, the digest artifact name, and the
    merge job's digest download pattern all need the single primary tag, but a
    GitHub Actions expression cannot split the newline list; the validate job
    computes it once and hands it downstream via steps.validate.outputs.primary-tag.
    """
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as output:
        output.write(f"primary-tag={primary_tag}\n")


def _validate_matrix(matrix: object) -> None:
    """Validate the build matrix BEFORE any image is built or pushed.

    Doing this in a dedicated pre-build job means a malformed matrix entry
    fails fast instead of pushing some per-platform tags and only erroring in
    the merge job.
    """
    if not isinstance(matrix, list) or not matrix:
        raise SystemExit("build-matrix must be a nonempty JSON array.")
    seen: set[str] = set()
    for index, entry in enumerate(matrix):
        if not isinstance(entry, dict):
            raise SystemExit(f"build-matrix[{index}] must be an object.")
        for field in ("runner", "platform", "platform_tag"):
            value = str(entry.get(field) or "").strip()
            if not value:
                raise SystemExit(f"build-matrix[{index}].{field} is required.")
        platform_tag = str(entry["platform_tag"]).strip()
        if platform_tag in seen:
            raise SystemExit(f"build-matrix has a duplicate platform_tag: {platform_tag!r}")
        seen.add(platform_tag)


def _validate_token_scope() -> None:
    """Refuse to send github.token to a registry other than ghcr.io.

    The docker login password falls back to github.token only for ghcr.io. Any
    other registry must supply an explicit docker-password secret, otherwise the
    caller could silently leak github.token to a third-party registry.
    """
    if not _truthy(os.environ.get("DOCKER_LOGIN_ENABLED", "")):
        return
    if _truthy(os.environ.get("DOCKER_PASSWORD_SET", "")):
        return
    registry = os.environ.get("DOCKER_REGISTRY", "").strip().lower()
    if registry != "ghcr.io":
        target = registry or "docker hub"
        raise SystemExit(
            f"docker-login-enabled is true for registry {target!r} but no docker-password "
            "secret was provided. The github.token login fallback is restricted to ghcr.io; "
            "pass docker-password to authenticate to any other registry."
        )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
