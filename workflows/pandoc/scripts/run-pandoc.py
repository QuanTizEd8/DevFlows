from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Practical subset of the distribution/reference image-reference grammar
# (docker.io/pandoc/core, ghcr.io/org/pandoc-filter:1.2, registry:5000/x@sha256:...).
# Validation is syntactic only: any well-formed reference is accepted, so callers
# may run official images, GHCR mirrors, or derived pandoc-filter images.
_ALNUM = r"[a-z0-9]+"
_SEPARATOR = r"(?:[._]|__|[-]+)"
_PATH_COMPONENT = rf"{_ALNUM}(?:{_SEPARATOR}{_ALNUM})*"
_NAME = rf"{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_DOMAIN = rf"{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*(?::[0-9]+)?"
_TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
_DIGEST = r"[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9A-Fa-f]{32,}"
_IMAGE_REFERENCE = re.compile(rf"^(?:{_DOMAIN}/)?{_NAME}(?::{_TAG})?(?:@{_DIGEST})?$")


def main() -> int:
    image = os.environ["PANDOC_IMAGE"]
    arguments = os.environ["PANDOC_ARGUMENTS"]
    relative_workdir = os.environ["PANDOC_WORKING_DIRECTORY"]
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    host_workdir = (workspace / relative_workdir).resolve()

    if not _IMAGE_REFERENCE.match(image):
        raise SystemExit(
            f"pandoc-image is not a valid image reference: {image!r}. "
            "Expected [registry/]name[:tag][@digest]."
        )
    if not arguments.strip():
        raise SystemExit("pandoc-arguments must not be empty.")
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
