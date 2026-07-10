from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

# Runs the caller's test command inside the prepared environment. The command and
# the per-leg test-arguments arrive as environment variables and are shlex-split
# into an argv list (shell=False), so nothing is interpolated into a shell body.
# The command's exit code is propagated verbatim: a nonzero exit fails the leg,
# and pytest's exit 5 (no tests collected) therefore fails too - no silent no-op.


def main() -> int:
    command = os.environ.get("TEST_COMMAND", "")
    arguments = os.environ.get("TEST_ARGUMENTS", "")
    working_directory = os.environ.get("TEST_WORKING_DIRECTORY", ".") or "."

    try:
        argv = shlex.split(command) + shlex.split(arguments)
    except ValueError as error:
        raise SystemExit(
            f"python-test: unable to parse test-command/test-arguments: {error}"
        ) from error
    if not argv:
        raise SystemExit("python-test: test-command must not be empty.")
    if not Path(working_directory).is_dir():
        raise SystemExit(f"python-test: test-working-directory does not exist: {working_directory}")

    printable = " ".join(shlex.quote(part) for part in argv)
    print(f"+ {printable}  (cwd={working_directory})", flush=True)
    completed = subprocess.run(argv, cwd=working_directory)  # noqa: PLW1510
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
