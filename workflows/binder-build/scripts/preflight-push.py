"""Tokenless registry-credential preflight (push-image job).

Runs before the docker/login-action step. The validate job maps only inputs.* and
cannot inspect secret presence, so the "non-ghcr registry without docker-password"
rejection lives here. Tokenless by design: it receives only the boolean
DOCKER_PASSWORD_SET, never the password value. ghcr.io is exempt because
docker/login-action falls back to github.token there.
"""

from __future__ import annotations

import os


def main() -> int:
    if not _bool("DOCKER_LOGIN_ENABLED"):
        # Login disabled: the caller is responsible for any ambient registry auth.
        return 0
    registry = os.environ.get("DOCKER_REGISTRY", "").strip().lower()
    if registry != "ghcr.io" and not _bool("DOCKER_PASSWORD_SET"):
        raise SystemExit(
            f"docker-login-enabled is true for registry {registry or '(docker hub)'!r} but the "
            "docker-password secret is empty. Only ghcr.io falls back to github.token; every "
            "other registry needs docker-password. Store it as an environment secret on the "
            "push environment and pass it with `secrets: inherit`, or run with "
            "publish-dry-run-enabled to build without pushing."
        )
    return 0


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
