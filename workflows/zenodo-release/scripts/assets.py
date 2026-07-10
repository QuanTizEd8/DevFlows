"""Asset glob resolution for zenodo-release (prepare job only).

Resolves newline-separated shell globs relative to a workspace-contained source
directory, applying the -if-no-files-found policy (error/warn/ignore). Never used
by the credentialed jobs, so it is inlined into prepare alone.
"""

from __future__ import annotations

import os
from pathlib import Path


class AssetError(ValueError):
    """An asset path, glob, or if-no-files-found policy failed."""


IF_NO_FILES_FOUND = ("error", "warn", "ignore")


def parse_lines(raw: str) -> list[str]:
    """Split a newline-separated input into stripped, non-empty lines."""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def workspace_root() -> Path:
    return Path(os.environ.get("GITHUB_WORKSPACE") or Path.cwd()).resolve()


def contained_dir(rel: str, *, field: str) -> Path:
    """Resolve a workspace-relative directory and refuse any escape."""
    rel = rel.strip()
    if os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        raise AssetError(f"{field} must be a workspace-relative path without '..': got {rel!r}.")
    root = workspace_root()
    target = (root / rel).resolve() if rel else root
    if target != root and root not in target.parents:
        raise AssetError(f"{field} must stay inside the workspace: {rel!r}.")
    return target


def resolve_globs(base_dir: Path, globs: list[str], *, policy: str, field: str) -> list[Path]:
    """Resolve globs under ``base_dir`` and apply the no-match policy.

    Returns a de-duplicated, sorted list of matched regular files. Each glob is
    resolved with ``Path.glob`` (no absolute patterns, no '..'). A glob that
    matches nothing is an error/warning/ignored per ``policy``.
    """
    if policy not in IF_NO_FILES_FOUND:
        raise AssetError(
            f"{field}-if-no-files-found must be one of {', '.join(IF_NO_FILES_FOUND)}; "
            f"got {policy!r}."
        )
    if not base_dir.is_dir():
        raise AssetError(f"{field} source directory does not exist: {base_dir}.")
    matched: dict[str, Path] = {}
    for pattern in globs:
        if os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/"):
            raise AssetError(
                f"{field} entry must be a relative glob without '..': got {pattern!r}."
            )
        hits = [path for path in sorted(base_dir.glob(pattern)) if path.is_file()]
        if not hits:
            message = f"{field} glob {pattern!r} matched no files under {base_dir}."
            if policy == "error":
                raise AssetError(message)
            if policy == "warn":
                print(f"::warning::{message}")
            continue
        for path in hits:
            matched[str(path.resolve())] = path
    return [matched[key] for key in sorted(matched)]
