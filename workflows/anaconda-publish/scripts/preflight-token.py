"""Tokenless per-job credential preflight.

validate cannot check secrets (its env maps only inputs.*), so each credentialed
job asserts the publishing credential is present BEFORE it reaches any CLI step.
This step is deliberately tokenless: it receives only a boolean
``ANACONDA_TOKEN_PRESENT`` (``${{ secrets.anaconda-token != '' }}``), never the
token value, so the token stays confined to the single CLI step. The environment-
bound jobs are already gated to skip in dry-run, so PUBLISH_DRY_RUN_ENABLED is a
belt-and-suspenders guard.
"""

from __future__ import annotations

import os


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if _bool("PUBLISH_DRY_RUN_ENABLED"):
        return 0
    if not _bool("ANACONDA_TOKEN_PRESENT"):
        raise SystemExit(
            "The anaconda-token secret is empty. anaconda.org has no OIDC/trusted "
            "publishing, so a real publish needs a token. Store it as an environment "
            "secret on the bound environment and pass it with `secrets: inherit`, or "
            "run with publish-dry-run-enabled to rehearse without a credential."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
