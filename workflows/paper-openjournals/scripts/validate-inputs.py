"""Fail-fast input validation for paper-openjournals (validate job).

Env maps ONLY inputs.* so the expect: validation-failure scenario harness can
reconstruct this step's environment from the scenario inputs and workflow
defaults. All validation logic lives in the sibling common module, so the
validate job and the build job agree exactly on what is legal. This job runs
before checkout, so it never checks source-file existence (that is the build
job's require_source_exists path).
"""

from __future__ import annotations

import os
import sys

import common


def main() -> int:
    config = common.parse_and_validate(os.environ, require_source_exists=False)
    print(
        "paper-openjournals inputs are valid: "
        f"journal={config.journal_env}, "
        f"flavors={','.join(config.flavors)}, "
        f"source={config.source_relative}, "
        f"output-directory={config.output_relative}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
