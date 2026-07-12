"""Registry-auth preflight for devcontainer-run (validate job, second step).

Refuses to fall back to github.token for any registry other than ghcr.io when
docker-login-enabled and no docker-password secret was provided (verbatim from
devcontainer-build). This is a separate step from validate-inputs.py because it
reads DOCKER_PASSWORD_SET (a `secrets.docker-password != ''` expression), which
the inputs-only validation-failure scenario harness cannot reconstruct.
"""

from __future__ import annotations

import os
import sys

import dcrun


def main() -> int:
    dcrun.validate_registry_auth(os.environ)
    print("devcontainer-run registry auth is consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
