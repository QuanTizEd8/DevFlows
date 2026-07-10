"""Tokenless credential preflight for the zenodo-deposit job.

validate maps only inputs.* and cannot inspect secrets, so the credentialed job
asserts the correct Zenodo token is present before the deposit step. Tokenless by
design: it receives only the boolean presence of each token, never the value, and
requires the sandbox token for a sandbox run and the production token otherwise.
"""

from __future__ import annotations

import os


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    if _bool("PUBLISH_DRY_RUN_ENABLED"):
        return 0
    sandbox = _bool("ZENODO_SANDBOX_ENABLED")
    present = _bool("ZENODO_SANDBOX_TOKEN_PRESENT" if sandbox else "ZENODO_TOKEN_PRESENT")
    if present:
        return 0
    which = "zenodo-sandbox-token" if sandbox else "zenodo-token"
    target = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    raise SystemExit(
        f"The {which} secret is empty, but a real deposit to {target} needs it. "
        "Store it as an environment secret on the bound zenodo-environment-name and "
        "pass it with `secrets: inherit`, or run with publish-dry-run-enabled to "
        "rehearse without a credential."
    )


if __name__ == "__main__":
    raise SystemExit(main())
