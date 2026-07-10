from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CREATE_PAYLOAD = Path("workflows/writeback/scripts/create-payload.py")
APPLY_PAYLOAD = Path("workflows/writeback/scripts/apply-payload.py")


def test_create_payload_records_files_replacements_and_deletions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    generated = workspace / "docs/generated"
    generated.mkdir(parents=True)
    source = generated / "index.html"
    source.write_text("<h1>Generated</h1>\n", encoding="utf-8")
    source.chmod(0o755)

    payload = workspace / ".devflows-writeback/payload"
    _run_script(
        CREATE_PAYLOAD,
        cwd=Path.cwd(),
        env={
            "GITHUB_WORKSPACE": str(workspace),
            "WRITEBACK_PAYLOAD_DIR": str(payload),
            "WRITEBACK_PATHS": "docs/generated",
            "WRITEBACK_DELETE_PATHS": "docs/old.html",
            "WRITEBACK_SOURCE_REPOSITORY": "owner/repo",
            "WRITEBACK_SOURCE_REF": "refs/heads/main",
            "WRITEBACK_SOURCE_SHA": "abc123",
        },
    )

    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["repository"] == "owner/repo"
    assert manifest["replace_paths"] == [{"path": "docs/generated"}]
    assert manifest["deletions"] == [{"path": "docs/old.html"}]
    assert manifest["files"][0]["path"] == "docs/generated/index.html"
    assert manifest["files"][0]["executable"] is True
    assert (payload / "files/docs/generated/index.html").is_file()


def test_apply_payload_replaces_directory_deletes_paths_and_commits(tmp_path: Path) -> None:
    source_workspace = tmp_path / "source"
    generated = source_workspace / "docs/generated"
    generated.mkdir(parents=True)
    (generated / "index.html").write_text("<h1>Updated</h1>\n", encoding="utf-8")
    payload = source_workspace / ".devflows-writeback/payload"
    _run_script(
        CREATE_PAYLOAD,
        cwd=Path.cwd(),
        env={
            "GITHUB_WORKSPACE": str(source_workspace),
            "WRITEBACK_PAYLOAD_DIR": str(payload),
            "WRITEBACK_PATHS": "docs/generated",
            "WRITEBACK_DELETE_PATHS": "docs/remove.html",
        },
    )

    target = tmp_path / "target"
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Initial Author")
    _git(target, "config", "user.email", "initial@example.test")
    (target / "docs/generated").mkdir(parents=True)
    (target / "docs/generated/stale.html").write_text("stale\n", encoding="utf-8")
    (target / "docs/remove.html").write_text("remove\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "initial")

    _run_script(
        APPLY_PAYLOAD,
        cwd=target,
        env={
            "GITHUB_WORKSPACE": str(target),
            "WRITEBACK_PAYLOAD_DIR": str(payload),
            "WRITEBACK_EXPECTED_BASE_SHA": "",
            "COMMIT_AUTHOR_NAME": "DevFlows Bot",
            "COMMIT_AUTHOR_EMAIL": "devflows@example.test",
            "COMMIT_BRANCH": "main",
            "COMMIT_MESSAGE": "docs: update generated files",
            "COMMIT_PUSH": "false",
        },
    )

    assert (target / "docs/generated/index.html").read_text(
        encoding="utf-8"
    ) == "<h1>Updated</h1>\n"
    assert not (target / "docs/generated/stale.html").exists()
    assert not (target / "docs/remove.html").exists()
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "docs: update generated files"
    assert _git_stdout(target, "status", "--short") == ""


def test_apply_payload_absent_deletion_is_noop(tmp_path: Path) -> None:
    """Deleting a path absent from the target must not abort the writeback."""
    target = _init_target(tmp_path)
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(
        payload,
        files=[("generated/index.html", "<h1>Updated</h1>\n")],
        deletions=["never/existed.txt", "also/missing.html"],
    )

    _apply(target, payload)

    assert (target / "generated/index.html").read_text(encoding="utf-8") == "<h1>Updated</h1>\n"
    assert (target / "keep.txt").exists()
    assert _git_stdout(target, "status", "--short") == ""


def test_apply_payload_only_absent_deletion_commits_nothing(tmp_path: Path) -> None:
    """A payload of only already-absent deletions is a clean no-op, not an error."""
    target = _init_target(tmp_path)
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, deletions=["never/existed.txt"])

    result = _apply(target, payload, check=False)
    assert result.returncode == 0
    assert "No changes to commit." in result.stdout
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "initial"


def test_apply_payload_deletes_tracked_file(tmp_path: Path) -> None:
    """A deletion of a path that IS present still removes it (regression guard)."""
    target = _init_target(tmp_path)
    (target / "remove.txt").write_text("remove\n", encoding="utf-8")
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, deletions=["remove.txt"])

    _apply(target, payload)
    assert not (target / "remove.txt").exists()
    assert (target / "keep.txt").exists()
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "writeback"


def test_apply_payload_digest_mismatch_aborts(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, files=[("docs/out.html", "<h1>Hi</h1>\n")])
    # Corrupt the stored payload file so its digest no longer matches the manifest.
    (payload / "files/docs/out.html").write_text("tampered\n", encoding="utf-8")

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "digest mismatch" in result.stderr


def test_apply_payload_rejects_absolute_path(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, files=[("/etc/passwd", "pwned\n")])

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "must be relative" in result.stderr


def test_apply_payload_rejects_dotdot_traversal(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, files=[("../escape.txt", "pwned\n")])

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "must not contain '..'" in result.stderr


def test_apply_payload_rejects_git_internal_name(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    payload = tmp_path / "payload"
    _write_payload(payload, files=[(".git/hooks/pre-commit", "evil\n")])

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "internal workflow paths" in result.stderr


def test_apply_payload_refuses_symlinked_parent_directory(tmp_path: Path) -> None:
    """A symlinked parent in the target must not let a write escape the workspace."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target = _init_target(tmp_path)
    (target / "escape").symlink_to(outside, target_is_directory=True)

    payload = tmp_path / "payload"
    _write_payload(payload, files=[("escape/evil.txt", "pwned\n")])

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "symlinked parent" in result.stderr
    assert not (outside / "evil.txt").exists()


def test_apply_payload_refuses_symlink_target(tmp_path: Path) -> None:
    """Writing over a symlink leaf must be refused, not followed outside."""
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.txt"
    outside_file.write_text("original\n", encoding="utf-8")
    target = _init_target(tmp_path)
    (target / "link.txt").symlink_to(outside_file)

    payload = tmp_path / "payload"
    _write_payload(payload, files=[("link.txt", "pwned\n")])

    result = _apply(target, payload, check=False)
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert outside_file.read_text(encoding="utf-8") == "original\n"


def _simulate_artifact_roundtrip(
    payload_dir: Path, download_dir: Path, *, include_hidden: bool
) -> None:
    """Copy a payload as actions/upload-artifact + download-artifact would.

    upload-artifact treats the uploaded directory as the artifact root and, since
    v4, EXCLUDES any file with a hidden path component (a segment starting with
    ".") unless include-hidden-files is set; download-artifact restores the
    surviving tree under the download path. Modeling that flattening lets the
    writeback round-trip be exercised end-to-end without a hosted runner.
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    for file_path in sorted(payload_dir.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(payload_dir)
        if not include_hidden and any(part.startswith(".") for part in relative.parts):
            continue
        target = download_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_path.read_bytes())


def _create_hidden_payload(workspace: Path, payload: Path) -> None:
    """create-payload for a writeback under a hidden directory (.devflows-e2e/)."""
    generated = workspace / ".devflows-e2e/writeback/generated"
    generated.mkdir(parents=True)
    (generated / "index.html").write_text("<h1>Updated by writeback</h1>\n", encoding="utf-8")
    _run_script(
        CREATE_PAYLOAD,
        cwd=Path.cwd(),
        env={
            "GITHUB_WORKSPACE": str(workspace),
            "WRITEBACK_PAYLOAD_DIR": str(payload),
            "WRITEBACK_PATHS": ".devflows-e2e/writeback/generated",
            "WRITEBACK_DELETE_PATHS": "",
        },
    )


def test_hidden_payload_dropped_by_default_upload_breaks_apply(tmp_path: Path) -> None:
    """Reproduces PR #5 run 29072401089.

    upload-artifact's default hidden-file exclusion drops
    files/.devflows-e2e/** from the artifact while keeping the manifest that
    references them, so apply-payload aborts. This is exactly the failure the
    include-hidden-files: true fix prevents.
    """
    source = tmp_path / "source"
    payload = source / ".devflows-writeback/payload"
    _create_hidden_payload(source, payload)
    assert (payload / "files/.devflows-e2e/writeback/generated/index.html").is_file()

    download = tmp_path / "download"
    _simulate_artifact_roundtrip(payload, download, include_hidden=False)
    # The manifest survives (not hidden); the hidden file subtree is gone.
    assert (download / "manifest.json").is_file()
    assert not (download / "files/.devflows-e2e").exists()

    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")
    result = _apply(target, download, check=False)
    assert result.returncode != 0
    assert "Payload file is missing or invalid" in result.stderr


def test_hidden_payload_survives_when_hidden_files_included(tmp_path: Path) -> None:
    """With include-hidden-files, the round-trip preserves files/.devflows-e2e/**
    and apply-payload writes the file into the target checkout."""
    source = tmp_path / "source"
    payload = source / ".devflows-writeback/payload"
    _create_hidden_payload(source, payload)

    download = tmp_path / "download"
    _simulate_artifact_roundtrip(payload, download, include_hidden=True)
    assert (download / "files/.devflows-e2e/writeback/generated/index.html").is_file()

    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")
    _apply(target, download)
    assert (target / ".devflows-e2e/writeback/generated/index.html").read_text(
        encoding="utf-8"
    ) == "<h1>Updated by writeback</h1>\n"


def _init_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Initial Author")
    _git(target, "config", "user.email", "initial@example.test")
    return target


def _write_payload(
    payload: Path,
    *,
    files: list[tuple[str, str]] | None = None,
    deletions: list[str] | None = None,
    replace_paths: list[str] | None = None,
) -> None:
    files_dir = payload / "files"
    files_dir.mkdir(parents=True)
    manifest = {
        "version": 1,
        "source": {"repository": "owner/repo", "ref": "refs/heads/main", "sha": "abc123"},
        "replace_paths": [{"path": path} for path in (replace_paths or [])],
        "deletions": [{"path": path} for path in (deletions or [])],
        "files": [],
    }
    for relative, content in files or []:
        data = content.encode("utf-8")
        # Place the bytes at the declared path when possible so the happy-path
        # digest check reads real content. Malicious paths (absolute, "..",
        # symlink) are rejected by the apply script before the source file is
        # ever read, so a missing stand-in for those is fine.
        declared = files_dir / relative
        try:
            declared.parent.mkdir(parents=True, exist_ok=True)
            declared.write_bytes(data)
        except (OSError, ValueError):
            pass
        manifest["files"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "executable": False,
            }
        )
    (payload / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _apply(target: Path, payload: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(APPLY_PAYLOAD.resolve())],
        cwd=target,
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(target),
            "WRITEBACK_PAYLOAD_DIR": str(payload),
            "WRITEBACK_EXPECTED_BASE_SHA": "",
            "COMMIT_AUTHOR_NAME": "DevFlows Bot",
            "COMMIT_AUTHOR_EMAIL": "devflows@example.test",
            "COMMIT_BRANCH": "main",
            "COMMIT_MESSAGE": "writeback",
            "COMMIT_PUSH": "false",
        },
        check=check,
        capture_output=True,
        text=True,
    )


def _run_script(script: Path, *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, str(script.resolve())],
        cwd=cwd,
        env={**os.environ, **env},
        check=True,
    )


def _git(cwd: Path, *args: str) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _git_stdout(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
