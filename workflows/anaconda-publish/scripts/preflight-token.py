"""Tokenless per-job credential preflight.

Each credentialed job asserts the publishing credential is present before any CLI
step (validate cannot check secrets). Tokenless by design: it receives only the
boolean ANACONDA_TOKEN_PRESENT, never the token value.
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
