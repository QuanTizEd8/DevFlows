"""Fail-fast validation for the python-lint reusable workflow.

Runs before any tool. Every caller string reaches this script through an env var
(never interpolated into a run: body) and is validated here so a misconfigured
call fails loudly with a single-line reason instead of surfacing as an opaque
tool crash later. All checks are pure Python; nothing is shelled out.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

TYPECHECK_TOOLS = ("mypy", "pyright", "ty")
UV_CACHE_MODES = ("auto", "true", "false")
# Bare PEP 440-ish version: starts with a digit, no whitespace, no version
# specifier operators (== >= <= ~= != < > * ,). Enough to reject a specifier or
# an accidental range while accepting 0.14.2, 1.11.0, 1.2.0rc1, 2.0.0.post1.
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+-]*$")
_TARGET_PYTHON = re.compile(r"^3\.[0-9]+$")
# ruff arguments the workflow owns. --output-format is always rejected (the
# workflow captures JSON for reporting). The mutating flags are rejected only in
# the read-only default; lint-fix mode legitimately fixes in place, so it accepts
# a caller-supplied --fix/--fix-only/--unsafe-fixes.
_FIX_RUFF_CHECK = ("--fix", "--fix-only", "--unsafe-fixes")
_FORBIDDEN_RUFF_CHECK_ALWAYS = ("--output-format",)
# per-version flags the workflow owns via typecheck-python-versions.
_FORBIDDEN_TYPECHECK = ("--python-version", "--pythonversion")


def main() -> int:
    workspace = _workspace()
    working_directory = _validate_working_directory(workspace)
    _validate_report_directory(workspace)
    _validate_lint_paths(working_directory, workspace)
    _validate_uv_cache_mode()
    _validate_tool_selection()
    _validate_uv_sync(working_directory)
    _validate_ruff_check_arguments()
    _validate_shlex("LINT_RUFF_FORMAT_ARGUMENTS", "ruff-format-arguments")
    _validate_typecheck()
    return 0


def _validate_working_directory(workspace: Path) -> Path:
    relative = _get("LINT_WORKING_DIRECTORY") or "."
    working_directory = (workspace / relative).resolve()
    if workspace != working_directory and workspace not in working_directory.parents:
        raise SystemExit("lint-working-directory must stay inside GITHUB_WORKSPACE.")
    if not working_directory.is_dir():
        raise SystemExit(f"lint-working-directory does not exist: {relative}")
    return working_directory


def _validate_report_directory(workspace: Path) -> None:
    relative = _get("LINT_REPORT_DIRECTORY")
    if not relative:
        return
    report_directory = (workspace / relative).resolve()
    if workspace != report_directory and workspace not in report_directory.parents:
        raise SystemExit("lint-report-directory must stay inside GITHUB_WORKSPACE.")


def _validate_lint_paths(working_directory: Path, workspace: Path) -> None:
    paths = _split_lines(_get("LINT_PATHS"))
    if not paths:
        raise SystemExit("lint-paths must not be empty.")
    for raw in paths:
        if Path(raw).is_absolute():
            raise SystemExit(f"lint-paths entries must be relative: {raw}")
        resolved = (working_directory / raw).resolve()
        if workspace != resolved and workspace not in resolved.parents:
            raise SystemExit(f"lint-paths entry escapes the workspace: {raw}")
        if not resolved.exists():
            raise SystemExit(f"lint-paths entry does not exist: {raw}")


def _validate_uv_cache_mode() -> None:
    mode = _get("LINT_UV_CACHE_MODE") or "auto"
    if mode not in UV_CACHE_MODES:
        raise SystemExit(f"uv-cache-mode must be one of {UV_CACHE_MODES}, got {mode!r}.")


def _validate_tool_selection() -> None:
    if not any(
        _truthy(_get(name))
        for name in (
            "LINT_RUFF_CHECK_ENABLED",
            "LINT_RUFF_FORMAT_ENABLED",
            "LINT_TYPECHECK_ENABLED",
        )
    ):
        raise SystemExit(
            "At least one of ruff-check-enabled, ruff-format-enabled, or typecheck-enabled "
            "must be true; a call that lints nothing is rejected."
        )
    if _truthy(_get("LINT_RUFF_CHECK_ENABLED")) or _get("LINT_RUFF_VERSION"):
        _validate_version("LINT_RUFF_VERSION", "ruff-version")


def _validate_uv_sync(working_directory: Path) -> None:
    sync_enabled = _truthy(_get("LINT_UV_SYNC_ENABLED"))
    if not sync_enabled:
        if _get("LINT_UV_SYNC_ARGUMENTS"):
            raise SystemExit("uv-sync-arguments is set but uv-sync-enabled is false.")
        return
    if not (working_directory / "pyproject.toml").is_file():
        raise SystemExit(
            "uv-sync-enabled is true but no pyproject.toml exists in lint-working-directory; "
            "uv sync requires a uv project."
        )
    _validate_shlex("LINT_UV_SYNC_ARGUMENTS", "uv-sync-arguments")


def _validate_ruff_check_arguments() -> None:
    tokens = _validate_shlex("LINT_RUFF_CHECK_ARGUMENTS", "ruff-check-arguments")
    fix_mode = _truthy(_get("LINT_FIX"))
    for token in tokens:
        head = token.split("=", 1)[0]
        if head in _FORBIDDEN_RUFF_CHECK_ALWAYS:
            raise SystemExit(
                f"ruff-check-arguments must not contain {head!r}; this workflow owns output "
                "capture for reporting."
            )
        if head in _FIX_RUFF_CHECK and not fix_mode:
            raise SystemExit(
                f"ruff-check-arguments must not contain {head!r}; this workflow is read-only "
                "unless lint-fix is true."
            )


def _validate_typecheck() -> None:
    # typecheck-python-versions is a newline-separated list (list-input convention),
    # not a JSON array. Each non-empty line must be a bare 3.<minor> target.
    for entry in _split_lines(_get("LINT_TYPECHECK_PYTHON_VERSIONS")):
        if not _TARGET_PYTHON.match(entry):
            raise SystemExit(
                f"typecheck-python-versions entries must match 3.<minor>, got {entry!r}."
            )
    if not _truthy(_get("LINT_TYPECHECK_ENABLED")):
        return
    tool = _get("LINT_TYPECHECK_TOOL") or "mypy"
    if tool not in TYPECHECK_TOOLS:
        raise SystemExit(f"typecheck-tool must be one of {TYPECHECK_TOOLS}, got {tool!r}.")
    _validate_version("LINT_TYPECHECK_VERSION", "typecheck-version")
    tokens = _validate_shlex("LINT_TYPECHECK_ARGUMENTS", "typecheck-arguments")
    for token in tokens:
        head = token.split("=", 1)[0]
        if head in _FORBIDDEN_TYPECHECK:
            raise SystemExit(
                f"typecheck-arguments must not contain {head!r}; target Python versions are "
                "controlled by typecheck-python-versions."
            )
    for requirement in _split_lines(_get("LINT_TYPECHECK_WITH")):
        if requirement != "." and requirement.startswith("-"):
            raise SystemExit(
                "typecheck-with entries must be requirement specifiers, not flags: "
                f"{requirement!r}."
            )


def _validate_version(env_name: str, input_name: str) -> None:
    value = _get(env_name)
    if value and not _VERSION.match(value):
        raise SystemExit(
            f"{input_name} must be a bare version string (no specifiers or whitespace): {value!r}."
        )


def _validate_shlex(env_name: str, input_name: str) -> list[str]:
    value = _get(env_name)
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError as error:
        raise SystemExit(f"Unable to parse {input_name}: {error}") from error


def _workspace() -> Path:
    # GITHUB_WORKSPACE is always set on a runner; fail fast with a clear message
    # (not a raw KeyError) when it is absent, e.g. a misconfigured local harness.
    raw = os.environ.get("GITHUB_WORKSPACE")
    if not raw:
        raise SystemExit("GITHUB_WORKSPACE is not set.")
    return Path(raw).resolve()


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _get(name: str) -> str:
    return os.environ.get(name, "").strip()


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
