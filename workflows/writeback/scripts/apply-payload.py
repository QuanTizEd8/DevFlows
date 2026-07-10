from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

INTERNAL_PATH_NAMES = {".devflows-writeback", ".git"}


def main() -> int:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    payload_dir = Path(os.environ["WRITEBACK_PAYLOAD_DIR"]).resolve()
    manifest = _load_manifest(payload_dir)
    expected_base_sha = os.environ.get("WRITEBACK_EXPECTED_BASE_SHA", "").strip()

    if expected_base_sha:
        actual_sha = _git_stdout("rev-parse", "HEAD")
        if actual_sha != expected_base_sha:
            raise SystemExit(f"Target checkout is at {actual_sha}, expected {expected_base_sha}.")

    stage_paths: set[str] = set()
    for item in manifest.get("replace_paths", []):
        relative = _validated_relative_path(str(item["path"]))
        target = _contained_target(workspace, relative)
        _remove(target)
        stage_paths.add(relative.as_posix())

    for item in manifest.get("deletions", []):
        relative = _validated_relative_path(str(item["path"]))
        target = _contained_target(workspace, relative)
        _remove(target)
        stage_paths.add(relative.as_posix())

    for item in manifest.get("files", []):
        relative = _validated_relative_path(str(item["path"]))
        source = payload_dir / "files" / relative
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"Payload file is missing or invalid: {relative.as_posix()}")
        expected_sha = str(item["sha256"])
        actual_sha = _sha256(source)
        if actual_sha != expected_sha:
            raise SystemExit(
                f"Payload digest mismatch for {relative.as_posix()}: "
                f"expected {expected_sha}, got {actual_sha}."
            )

        target = _contained_target(workspace, relative)
        if target.is_symlink():
            raise SystemExit(f"refusing to write through a symlink target: {relative.as_posix()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        mode = 0o755 if item.get("executable") else 0o644
        target.chmod(mode)
        stage_paths.add(relative.as_posix())

    if not stage_paths:
        raise SystemExit("Writeback payload did not contain files or deletions.")

    _git("config", "user.name", os.environ["COMMIT_AUTHOR_NAME"])
    _git("config", "user.email", os.environ["COMMIT_AUTHOR_EMAIL"])
    _stage(workspace, stage_paths)

    if _git_quiet("diff", "--cached", "--quiet"):
        print("No changes to commit.")
        return 0

    _git("commit", "-m", os.environ["COMMIT_MESSAGE"])
    if os.environ["COMMIT_PUSH"].lower() == "true":
        _git("push", "origin", f"HEAD:{os.environ['COMMIT_BRANCH']}")
    return 0


def _load_manifest(payload_dir: Path) -> dict[str, Any]:
    manifest_path = payload_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Writeback manifest was not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise SystemExit("Unsupported writeback manifest version.")
    if not isinstance(manifest.get("files"), list):
        raise SystemExit("Writeback manifest must contain a files list.")
    return manifest


def _validated_relative_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise SystemExit(f"path must be relative: {raw_path}")
    if str(path) in {"", "."}:
        raise SystemExit("path must not be empty or '.'.")
    if ".." in path.parts:
        raise SystemExit(f"path must not contain '..': {raw_path}")
    if any(part in INTERNAL_PATH_NAMES for part in path.parts):
        raise SystemExit(f"path must not include internal workflow paths: {raw_path}")
    return path


def _contained_target(workspace: Path, relative: Path) -> Path:
    """Return the absolute target for a lexically-validated relative path.

    Lexical validation (``_validated_relative_path``) already rejects absolute
    paths, ``..`` traversal, and internal names, but it cannot see symlinks in
    the target checkout. A symlinked parent directory (or a symlinked leaf) can
    still redirect a write or delete outside GITHUB_WORKSPACE. Resolve the real
    parent chain and refuse to traverse any symlinked component before touching
    the filesystem.
    """
    target = workspace / relative
    current = workspace
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SystemExit(
                f"refusing to traverse a symlinked parent directory: {relative.as_posix()}"
            )
    real_parent = target.parent.resolve()
    if real_parent != workspace and workspace not in real_parent.parents:
        raise SystemExit(
            f"path escapes GITHUB_WORKSPACE after resolving symlinks: {relative.as_posix()}"
        )
    return target


def _stage(workspace: Path, stage_paths: set[str]) -> None:
    """Stage writes and deletions idempotently.

    Paths that exist on disk (new/updated files, replacement directories) are
    staged with ``git add -A``, which also records deletions of tracked files
    that vanished from a replaced directory. Paths that no longer exist
    (explicit deletions, or replacement directories that became empty) are
    unstaged with ``git rm --cached --ignore-unmatch`` so that deleting a
    path already absent from the target branch is a no-op rather than a fatal
    ``pathspec did not match`` error.
    """
    existing = sorted(p for p in stage_paths if (workspace / p).exists())
    missing = sorted(p for p in stage_paths if not (workspace / p).exists())
    if existing:
        _git("add", "-A", "--", *existing)
    for relative in missing:
        _git("rm", "-r", "--cached", "--ignore-unmatch", "-q", "--", relative)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def _git_quiet(*args: str) -> bool:
    return subprocess.run(["git", *args], check=False).returncode == 0


def _git_stdout(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
