from __future__ import annotations

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
