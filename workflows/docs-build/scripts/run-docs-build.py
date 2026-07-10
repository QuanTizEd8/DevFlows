from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

# Fixed micromamba environment name created by the setup-micromamba step in the
# generated workflow; `micromamba run -n <name>` must match it exactly.
MICROMAMBA_ENVIRONMENT_NAME = "docs-build"


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def _split(value: str, what: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError as error:
        raise SystemExit(f"Unable to parse {what}: {error}") from error


def _relative_to_workspace(workspace: Path, relative: str) -> str:
    """Workspace-relative POSIX path, rejecting anything that escapes the tree."""
    resolved = (workspace / relative).resolve()
    if workspace != resolved and workspace not in resolved.parents:
        raise SystemExit(f"path must stay inside GITHUB_WORKSPACE: {relative!r}")
    if resolved == workspace:
        return ""
    return resolved.relative_to(workspace).as_posix()


def render_path(workspace: Path, relative: str, environment: str) -> str:
    """Render a workspace-relative path as a host-absolute or /data container path."""
    posix = _relative_to_workspace(workspace, relative)
    if environment == "container":
        return "/data" if not posix else f"/data/{posix}"
    return str(workspace if not posix else workspace / posix)


def docs_build_argv(
    *,
    tool: str,
    builder: str,
    warnings_as_errors: bool,
    sphinx_arguments: list[str],
    mkdocs_arguments: list[str],
    source_path: str,
    output_path: str,
    config_path: str,
) -> list[str]:
    """Compose the sphinx-build / mkdocs build argv (paths already rendered)."""
    if tool == "sphinx":
        argv = ["sphinx-build", "-b", builder]
        if warnings_as_errors:
            argv += ["-W", "--keep-going"]
        argv += sphinx_arguments
        argv += [source_path, output_path]
        return argv
    if tool == "mkdocs":
        argv = ["mkdocs", "build", "--config-file", config_path, "--site-dir", output_path]
        if warnings_as_errors:
            argv.append("--strict")
        argv += mkdocs_arguments
        return argv
    raise SystemExit(f"Unsupported docs-tool: {tool!r}.")


def linkcheck_argv(*, sphinx_arguments: list[str], source_path: str, report_path: str) -> list[str]:
    return ["sphinx-build", "-b", "linkcheck", *sphinx_arguments, source_path, report_path]


def wrap_in_environment(
    inner: list[str],
    *,
    environment: str,
    workspace: Path,
    container_workdir: str,
    pixi_environment: str,
    pixi_manifest_path: str,
    image: str,
) -> list[str]:
    """Wrap the inner tool argv in the selected environment runner."""
    if environment == "pixi":
        command = ["pixi", "run", "--environment", pixi_environment]
        if pixi_manifest_path.strip():
            command += ["--manifest-path", str((workspace / pixi_manifest_path).resolve())]
        return [*command, "--", *inner]
    if environment == "uv":
        return ["uv", "run", "--no-sync", "--", *inner]
    if environment == "micromamba":
        return ["micromamba", "run", "-n", MICROMAMBA_ENVIRONMENT_NAME, *inner]
    if environment == "pip":
        return inner
    if environment == "container":
        return [
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
            *inner,
        ]
    raise SystemExit(f"Unsupported docs-environment: {environment!r}.")


def _trusted_command_inner(command: str) -> list[str]:
    return ["bash", "-euo", "pipefail", "-c", command]


def main() -> int:
    mode = os.environ.get("DOCS_BUILD_MODE", "build").strip()
    tool = os.environ.get("DOCS_TOOL", "").strip()
    environment = os.environ.get("DOCS_ENVIRONMENT", "").strip()
    build_command = os.environ.get("DOCS_BUILD_COMMAND", "").strip()
    warnings_as_errors = _bool("DOCS_WARNINGS_AS_ERRORS")

    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    working_directory = os.environ.get("DOCS_WORKING_DIRECTORY", "") or "."
    output_directory = os.environ.get("DOCS_OUTPUT_DIRECTORY", "").strip()

    source_path = render_path(
        workspace, os.environ.get("SPHINX_SOURCE_DIRECTORY", "docs"), environment
    )
    output_path = render_path(workspace, output_directory, environment)
    config_path = render_path(
        workspace, os.environ.get("MKDOCS_CONFIG_FILE", "mkdocs.yml"), environment
    )
    container_workdir = render_path(workspace, working_directory, environment)

    if mode == "linkcheck":
        report_path = render_path(workspace, f"{output_directory}-linkcheck", environment)
        inner = linkcheck_argv(
            sphinx_arguments=_split(os.environ.get("SPHINX_ARGUMENTS", ""), "sphinx-arguments"),
            source_path=source_path,
            report_path=report_path,
        )
    elif mode == "build":
        if build_command:
            inner = _trusted_command_inner(build_command)
        else:
            inner = docs_build_argv(
                tool=tool,
                builder=os.environ.get("SPHINX_BUILDER", "").strip(),
                warnings_as_errors=warnings_as_errors,
                sphinx_arguments=_split(os.environ.get("SPHINX_ARGUMENTS", ""), "sphinx-arguments"),
                mkdocs_arguments=_split(os.environ.get("MKDOCS_ARGUMENTS", ""), "mkdocs-arguments"),
                source_path=source_path,
                output_path=output_path,
                config_path=config_path,
            )
    else:
        raise SystemExit(f"Unknown DOCS_BUILD_MODE: {mode!r}.")

    command = wrap_in_environment(
        inner,
        environment=environment,
        workspace=workspace,
        container_workdir=container_workdir,
        pixi_environment=os.environ.get("PIXI_ENVIRONMENT", "default").strip() or "default",
        pixi_manifest_path=os.environ.get("PIXI_MANIFEST_PATH", ""),
        image=os.environ.get("CONTAINER_IMAGE", "").strip(),
    )
    subprocess.run(command, cwd=str((workspace / working_directory).resolve()), check=True)

    if mode == "build":
        _assert_non_empty(workspace / output_directory, output_directory)
    return 0


def _assert_non_empty(output_dir: Path, relative: str) -> None:
    """A build (generated or custom) that produced no output is a hard failure."""
    resolved = output_dir.resolve()
    if not resolved.is_dir():
        raise SystemExit(f"docs-output-directory was not created by the build: {relative!r}")
    if not any(resolved.iterdir()):
        raise SystemExit(f"docs-output-directory is empty after the build: {relative!r}")


if __name__ == "__main__":
    sys.exit(main())
