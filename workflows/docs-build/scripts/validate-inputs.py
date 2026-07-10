from __future__ import annotations

import os
import re
from pathlib import Path

# Practical subset of the distribution/reference image-reference grammar shared
# with pandoc's run-pandoc.py (docker.io/org/name:tag, ghcr.io/org/img@sha256:...).
# Validation is syntactic only: any well-formed reference is accepted, so callers
# may run official images, GHCR mirrors, or their own docs toolchain images.
_ALNUM = r"[a-z0-9]+"
_SEPARATOR = r"(?:[._]|__|[-]+)"
_PATH_COMPONENT = rf"{_ALNUM}(?:{_SEPARATOR}{_ALNUM})*"
_NAME = rf"{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_DOMAIN = rf"{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*(?::[0-9]+)?"
_TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
_DIGEST = r"[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9A-Fa-f]{32,}"
_IMAGE_REFERENCE = re.compile(rf"^(?:{_DOMAIN}/)?{_NAME}(?::{_TAG})?(?:@{_DIGEST})?$")

_TOOLS = {"sphinx", "mkdocs"}
_ENVIRONMENTS = {"pixi", "uv", "pip", "container", "micromamba"}
_UV_CACHE_MODES = {"auto", "true", "false"}


def _bool(name: str) -> bool:
    """Parse a GitHub Actions boolean input passed through an env var."""
    return os.environ.get(name, "").strip().lower() == "true"


def _text(name: str) -> str:
    return os.environ.get(name, "")


def _inside_workspace(workspace: Path, relative: str) -> Path:
    """Resolve a workspace-relative path and confirm it does not escape."""
    resolved = (workspace / relative).resolve()
    if workspace != resolved and workspace not in resolved.parents:
        raise SystemExit(f"path must stay inside GITHUB_WORKSPACE: {relative!r}")
    return resolved


def _emit_outputs(**outputs: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(f"{name}={value}\n")


def main() -> int:
    tool = _text("DOCS_TOOL").strip()
    environment = _text("DOCS_ENVIRONMENT").strip()
    build_command = _text("DOCS_BUILD_COMMAND").strip()
    working_directory = _text("DOCS_WORKING_DIRECTORY")
    output_directory = _text("DOCS_OUTPUT_DIRECTORY").strip()
    warnings_as_errors_ignored = _bool("DOCS_WARNINGS_AS_ERRORS")  # noqa: F841
    linkcheck = _bool("DOCS_LINKCHECK_ENABLED")
    sphinx_builder = _text("SPHINX_BUILDER").strip()
    sphinx_arguments = _text("SPHINX_ARGUMENTS").strip()
    mkdocs_arguments = _text("MKDOCS_ARGUMENTS").strip()
    pages_enabled = _bool("PAGES_ARTIFACT_ENABLED")
    pages_name = _text("PAGES_ARTIFACT_NAME")

    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()

    # -- tool / environment enums (always validated) --------------------------
    if tool not in _TOOLS:
        raise SystemExit(f"docs-tool must be one of {sorted(_TOOLS)}, got {tool!r}.")
    if environment not in _ENVIRONMENTS:
        raise SystemExit(
            f"docs-environment must be one of {sorted(_ENVIRONMENTS)}, got {environment!r}."
        )

    # -- output directory is required and must not be empty or escape ---------
    if not output_directory:
        raise SystemExit("docs-output-directory must not be empty.")
    _inside_workspace(workspace, output_directory)

    # -- working directory must exist and stay inside the workspace -----------
    working_dir = _inside_workspace(workspace, working_directory or ".")
    if not working_dir.is_dir():
        raise SystemExit(f"docs-working-directory does not exist: {working_directory!r}")

    # -- build-command / tool-argument mutual exclusivity (always) ------------
    if build_command and sphinx_arguments:
        raise SystemExit("sphinx-arguments must be empty when docs-build-command is set.")
    if build_command and mkdocs_arguments:
        raise SystemExit("mkdocs-arguments must be empty when docs-build-command is set.")
    if tool == "mkdocs" and sphinx_arguments:
        raise SystemExit("sphinx-arguments must be empty when docs-tool is mkdocs.")
    if tool == "sphinx" and mkdocs_arguments:
        raise SystemExit("mkdocs-arguments must be empty when docs-tool is sphinx.")
    if tool == "sphinx" and not build_command and not sphinx_builder:
        raise SystemExit(
            "sphinx-builder must be non-empty when docs-tool is sphinx and "
            "docs-build-command is unset."
        )

    # -- link check is a Sphinx-only builder ----------------------------------
    if linkcheck and tool == "mkdocs":
        raise SystemExit(
            "docs-linkcheck-enabled requires docs-tool sphinx; MkDocs has no built-in link checker."
        )

    # -- per-environment consistency (non-selected groups are ignored) --------
    if environment == "uv":
        uv_cache_mode = _text("UV_CACHE_MODE").strip()
        if uv_cache_mode not in _UV_CACHE_MODES:
            raise SystemExit(
                f"uv-cache-mode must be one of {sorted(_UV_CACHE_MODES)}, got {uv_cache_mode!r}."
            )
    elif environment == "pip":
        requirements_file = _text("PIP_REQUIREMENTS_FILE").strip()
        install_targets = _text("PIP_INSTALL_TARGETS").strip()
        if not requirements_file and not install_targets:
            raise SystemExit(
                "pip mode requires pip-requirements-file and/or pip-install-targets; "
                "both are empty."
            )
    elif environment == "pixi":
        if _bool("PIXI_LOCKED") and _bool("PIXI_FROZEN"):
            raise SystemExit("pixi-locked and pixi-frozen are mutually exclusive; set at most one.")
    elif environment == "micromamba":
        if not _text("MICROMAMBA_ENVIRONMENT_FILE").strip():
            raise SystemExit("micromamba mode requires micromamba-environment-file.")
    elif environment == "container":
        image = _text("CONTAINER_IMAGE").strip()
        if not image:
            raise SystemExit("container mode requires container-image; it is empty.")
        if not _IMAGE_REFERENCE.match(image):
            raise SystemExit(
                f"container-image is not a valid image reference: {image!r}. "
                "Expected [registry/]name[:tag][@digest]."
            )
        if _bool("CONTAINER_LOGIN_ENABLED") and not _bool("CONTAINER_PASSWORD_SET"):
            raise SystemExit(
                "container-login-enabled requires the container-password secret; it is unset."
            )

    _emit_outputs(
        **{
            "docs-output-directory": output_directory,
            "docs-linkcheck-report-directory": (
                f"{output_directory}-linkcheck" if linkcheck else ""
            ),
            "pages-artifact-name": pages_name if pages_enabled else "",
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
