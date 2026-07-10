from __future__ import annotations

import json
import os


def main() -> int:
    _validate_matrix(json.loads(_required("BUILD_MATRIX")))
    _validate_token_scope()
    return 0


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
