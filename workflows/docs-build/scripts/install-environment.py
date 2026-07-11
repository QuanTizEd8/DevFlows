from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def _split_lines(value: str) -> list[str]:
    """Split a newline-separated list input into stripped, non-empty tokens."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def _working_directory() -> Path:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    relative = os.environ.get("DOCS_WORKING_DIRECTORY", "") or "."
    working_dir = (workspace / relative).resolve()
    if workspace != working_dir and workspace not in working_dir.parents:
        raise SystemExit("docs-working-directory must stay inside GITHUB_WORKSPACE.")
    if not working_dir.is_dir():
        raise SystemExit(f"docs-working-directory does not exist: {relative!r}")
    return working_dir


def _uv_sync(working_dir: Path) -> list[str]:
    command = ["uv", "sync"]
    if _bool("UV_SYNC_LOCKED"):
        command.append("--locked")
    for group in _split_lines(os.environ.get("UV_SYNC_GROUPS", "")):
        command += ["--group", group]
    for extra in _split_lines(os.environ.get("UV_SYNC_EXTRAS", "")):
        command += ["--extra", extra]
    try:
        command += shlex.split(os.environ.get("UV_SYNC_ARGUMENTS", ""))
    except ValueError as error:
        raise SystemExit(f"Unable to parse uv-sync-arguments: {error}") from error
    return command


def _pip_install(working_dir: Path) -> list[str]:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    requirements_file = os.environ.get("PIP_REQUIREMENTS_FILE", "").strip()
    targets = _split_lines(os.environ.get("PIP_INSTALL_TARGETS", ""))
    if not requirements_file and not targets:
        # validate-inputs.py already rejects this; guard the script directly too.
        raise SystemExit("pip mode requires pip-requirements-file and/or pip-install-targets.")
    command = [sys.executable, "-m", "pip", "install"]
    if requirements_file:
        resolved = (workspace / requirements_file).resolve()
        if workspace != resolved and workspace not in resolved.parents:
            raise SystemExit("pip-requirements-file must stay inside GITHUB_WORKSPACE.")
        command += ["-r", str(resolved)]
    command += targets
    return command


def main() -> int:
    environment = os.environ.get("DOCS_ENV_MANAGER", "").strip()
    working_dir = _working_directory()
    if environment == "uv":
        command = _uv_sync(working_dir)
    elif environment == "pip":
        command = _pip_install(working_dir)
    else:
        # pixi/micromamba install through their setup actions; container has no
        # host-side dependency install. This step should only run for uv/pip.
        raise SystemExit(f"install-environment.py is only valid for uv/pip, got {environment!r}.")
    subprocess.run(command, cwd=working_dir, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
