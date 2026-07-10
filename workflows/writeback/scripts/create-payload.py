from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

INTERNAL_PATH_NAMES = {".devflows-writeback", ".git"}

# Payload layout produced under WRITEBACK_PAYLOAD_DIR:
#   manifest.json            -- version, source, replace_paths, deletions, files
#   files/<repo-relative>    -- one regular file per manifest "files" entry
# Selected paths keep their repo-relative layout under files/, so the subtree can
# contain dotfiles and dot-directories (e.g. .github/**). apply-payload.py reads
# each file back from files/<path> and verifies its sha256 against the manifest.
# CONTRACT: whatever uploads this directory as an artifact MUST preserve hidden
# files (actions/upload-artifact include-hidden-files: true). upload-artifact v4+
# excludes hidden paths by default, which would drop those files while leaving the
# manifest that references them -- apply-payload.py then aborts with
# "Payload file is missing or invalid".


def main() -> int:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    payload_dir = Path(os.environ["WRITEBACK_PAYLOAD_DIR"]).resolve()
    files_dir = payload_dir / "files"
    selected_paths = _split_lines(os.environ.get("WRITEBACK_PATHS", ""))
    delete_paths = _split_lines(os.environ.get("WRITEBACK_DELETE_PATHS", ""))

    if workspace != payload_dir and workspace not in payload_dir.parents:
        raise SystemExit("WRITEBACK_PAYLOAD_DIR must stay inside GITHUB_WORKSPACE.")
    if not selected_paths and not delete_paths:
        raise SystemExit("At least one writeback path or deletion path is required.")

    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    files_dir.mkdir(parents=True)

    manifest: dict[str, Any] = {
        "version": 1,
        "source": {
            "repository": os.environ.get("WRITEBACK_SOURCE_REPOSITORY", ""),
            "ref": os.environ.get("WRITEBACK_SOURCE_REF", ""),
            "sha": os.environ.get("WRITEBACK_SOURCE_SHA", ""),
        },
        "replace_paths": [],
        "deletions": [],
        "files": [],
    }
    seen_files: set[str] = set()

    for raw_path in selected_paths:
        path = _resolve_workspace_path(workspace, raw_path)
        if not path.exists():
            raise SystemExit(f"writeback path does not exist: {raw_path}")
        if path.is_symlink():
            raise SystemExit(f"writeback path must not be a symlink: {raw_path}")
        if path.is_dir():
            relative = path.relative_to(workspace).as_posix()
            manifest["replace_paths"].append({"path": relative})
            for file_path in sorted(path.rglob("*")):
                if _contains_internal_part(file_path.relative_to(workspace)):
                    continue
                if file_path.is_symlink() or not file_path.is_file():
                    raise SystemExit(f"writeback files must be regular files: {file_path}")
                _add_file(workspace, files_dir, manifest, seen_files, file_path)
        elif path.is_file():
            _add_file(workspace, files_dir, manifest, seen_files, path)
        else:
            raise SystemExit(f"writeback path must be a regular file or directory: {raw_path}")

    for raw_path in delete_paths:
        relative = _validated_relative_path(raw_path)
        manifest["deletions"].append({"path": relative.as_posix()})

    manifest_path = payload_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    relative = _validated_relative_path(raw_path)
    path = (workspace / relative).resolve()
    if workspace != path and workspace not in path.parents:
        raise SystemExit(f"path must stay inside GITHUB_WORKSPACE: {raw_path}")
    return path


def _validated_relative_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise SystemExit(f"path must be relative: {raw_path}")
    if str(path) in {"", "."}:
        raise SystemExit("path must not be empty or '.'.")
    if ".." in path.parts:
        raise SystemExit(f"path must not contain '..': {raw_path}")
    if _contains_internal_part(path):
        raise SystemExit(f"path must not include internal workflow paths: {raw_path}")
    return path


def _contains_internal_part(path: Path) -> bool:
    return any(part in INTERNAL_PATH_NAMES for part in path.parts)


def _add_file(
    workspace: Path,
    files_dir: Path,
    manifest: dict[str, Any],
    seen_files: set[str],
    file_path: Path,
) -> None:
    relative = file_path.relative_to(workspace)
    relative_posix = relative.as_posix()
    if relative_posix in seen_files:
        return
    seen_files.add(relative_posix)

    target = files_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, target)
    mode = stat.S_IMODE(file_path.stat().st_mode)
    manifest["files"].append(
        {
            "path": relative_posix,
            "sha256": _sha256(file_path),
            "size": file_path.stat().st_size,
            "executable": bool(mode & stat.S_IXUSR),
        }
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
