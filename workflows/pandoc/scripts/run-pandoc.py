from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def main() -> int:
    image = os.environ["PANDOC_IMAGE"]
    arguments = os.environ["PANDOC_ARGUMENTS"]
    relative_workdir = os.environ["PANDOC_WORKING_DIRECTORY"]
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    host_workdir = (workspace / relative_workdir).resolve()

    if not image.startswith("pandoc/"):
        raise SystemExit("pandoc-image must start with 'pandoc/'.")
    if workspace != host_workdir and workspace not in host_workdir.parents:
        raise SystemExit("pandoc-working-directory must stay inside GITHUB_WORKSPACE.")
    if not host_workdir.is_dir():
        raise SystemExit(f"pandoc-working-directory does not exist: {relative_workdir}")

    try:
        pandoc_args = shlex.split(arguments)
    except ValueError as error:
        raise SystemExit(f"Unable to parse pandoc-arguments: {error}") from error

    container_workdir = "/data"
    if host_workdir != workspace:
        container_workdir = f"/data/{host_workdir.relative_to(workspace).as_posix()}"

    command = [
        "docker",
        "run",
        "--rm",
        "--volume",
        f"{workspace}:/data",
        "--workdir",
        container_workdir,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        image,
        *pandoc_args,
    ]
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
