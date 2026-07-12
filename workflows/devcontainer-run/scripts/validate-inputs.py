"""Fail-fast input validation for devcontainer-run (validate job).

Env maps ONLY inputs.* so the expect: validation-failure scenario harness can
reconstruct this step's environment from the scenario inputs and workflow
defaults. All validation logic lives in the sibling dcrun module, so the
validate job and the run job agree exactly on what is legal. The registry-auth
preflight (which reads a secret-presence expression) lives in the separate
check-registry-auth.py step, keeping this step inputs-only.
"""

from __future__ import annotations

import os
import sys

import dcrun


def main() -> int:
    config = dcrun.parse_and_validate(os.environ, require_workspace=True)
    image = config.image or "(from devcontainer-config-file)"
    config_file = config.config_file or "(none)"
    print(
        "devcontainer-run inputs are valid: "
        f"image={image}, config-file={config_file}, shell={config.run_shell}, "
        f"cli-version={config.cli_version}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
