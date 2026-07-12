"""Tests for the mutation-scenario harness scripts (setup/cleanup/assert).

These exercise the three previously-untested substantive scripts against a local
bare git remote (no network) plus the shared ``_ephemeral`` derivation helper.
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(".dev/harness/scenarios").resolve()


def _load_ephemeral():
    spec = importlib.util.spec_from_file_location("_ephemeral", HARNESS / "_ephemeral.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ephemeral = _load_ephemeral()


def _run(script: str, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runpy.run_path(str(HARNESS / script), run_name="__main__")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@example.test")
    _git(work, "config", "user.name", "Tester")
    _git(work, "remote", "add", "origin", str(remote))
    (work / "README.md").write_text("seed\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "init")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _remote_heads(work: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(ephemeral.parse_ls_remote_heads(result.stdout))


# --------------------------------------------------------- _ephemeral derivation


def test_branch_and_artifact_derivations() -> None:
    assert ephemeral.branch_name("pfx", "42", "3") == "pfx-42-3"
    assert ephemeral.artifact_name("wb", "42", "3") == "wb-42-3"


def test_run_branch_glob_matches_every_attempt_of_setup() -> None:
    # The glob cleanup uses must match whatever branch setup would derive for any
    # attempt of the same run — the invariant that keeps re-runs from orphaning.
    import fnmatch

    glob = ephemeral.run_branch_glob("pfx", "42")
    for attempt in ("1", "2", "17"):
        assert fnmatch.fnmatch(ephemeral.branch_name("pfx", "42", attempt), glob)
    assert not fnmatch.fnmatch(ephemeral.branch_name("pfx", "99", "1"), glob)


def test_parse_ls_remote_heads() -> None:
    stdout = "abc123\trefs/heads/pfx-42-1\ndef456\trefs/heads/other\n"
    assert ephemeral.parse_ls_remote_heads(stdout) == ["pfx-42-1", "other"]
    assert ephemeral.parse_ls_remote_heads("") == []


def test_is_already_deleted_classification() -> None:
    assert ephemeral.is_already_deleted("error: remote ref does not exist")
    assert ephemeral.is_already_deleted("error: unable to delete 'x': remote ref does not exist")
    assert not ephemeral.is_already_deleted("fatal: could not read from remote repository")


# ------------------------------------------------------------------- cleanup


def test_cleanup_deletes_all_attempt_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _remote, work = _init_repo_with_remote(tmp_path)
    for name in ("pfx-42-1", "pfx-42-2", "pfx-99-1", "unrelated"):
        _git(work, "push", "origin", f"main:refs/heads/{name}")
    monkeypatch.chdir(work)

    # Current attempt is 3, but attempts 1 and 2 pushed branches; all must go.
    _run(
        "cleanup-ephemeral-branch.py",
        {"DEVFLOWS_BRANCH_PREFIX": "pfx", "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "3"},
        monkeypatch,
    )

    remaining = _remote_heads(work)
    assert "pfx-42-1" not in remaining
    assert "pfx-42-2" not in remaining
    assert {"pfx-99-1", "unrelated", "main"} <= remaining


def test_cleanup_noop_when_no_matching_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _remote, work = _init_repo_with_remote(tmp_path)
    monkeypatch.chdir(work)

    _run(
        "cleanup-ephemeral-branch.py",
        {"DEVFLOWS_BRANCH_PREFIX": "pfx", "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1"},
        monkeypatch,
    )

    assert "No ephemeral branches" in capsys.readouterr().out


# --------------------------------------------------------------------- setup


def test_setup_pushes_branch_and_builds_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _remote, work = _init_repo_with_remote(tmp_path)

    github_output = tmp_path / "output.txt"
    github_output.write_text("", encoding="utf-8")
    monkeypatch.chdir(work)

    _run(
        "setup-ephemeral-writeback.py",
        {
            "GITHUB_WORKSPACE": str(work),
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_RUN_ID": "7",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "owner/repo",
            "DEVFLOWS_ARTIFACT_NAME": "wb-patch",
            "DEVFLOWS_BRANCH_PREFIX": "e2e/wb",
            "DEVFLOWS_FIXTURE_PATH": ".devflows-e2e/writeback",
            "DEVFLOWS_INITIAL_FILES": json.dumps([{"path": "remove.html", "content": "old\n"}]),
            "DEVFLOWS_PAYLOAD_FILES": json.dumps(
                [{"path": "generated/index.html", "content": "<h1>hi</h1>\n"}]
            ),
            "DEVFLOWS_PAYLOAD_PATHS": json.dumps(["generated"]),
            "DEVFLOWS_DELETE_PATHS": json.dumps(["remove.html"]),
        },
        monkeypatch,
    )

    outputs = github_output.read_text(encoding="utf-8")
    assert "branch=e2e/wb-7-1" in outputs
    assert "artifact-name=wb-patch-7-1" in outputs
    patch_file = work / ".devflows-patch/changes.patch"
    assert patch_file.is_file()
    # The captured patch adds the new generated file and deletes the removed one.
    patch_text = patch_file.read_text(encoding="utf-8")
    assert "generated/index.html" in patch_text
    assert "remove.html" in patch_text
    assert "e2e/wb-7-1" in _remote_heads(work)


# ------------------------------------------------------------------- assert


def _writeback_assertions() -> list[dict]:
    return [
        {
            "type": "branch-file-contains",
            "path": "generated/index.html",
            "text": "Updated by writeback",
        },
        {"type": "branch-file-missing", "path": "generated/stale.html"},
        {"type": "latest-commit-message-equals", "value": "test: writeback e2e"},
    ]


def test_assert_ephemeral_writeback_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    _git(tmp_path, "config", "user.email", "t@example.test")
    _git(tmp_path, "config", "user.name", "Tester")
    fixture = tmp_path / "fx" / "generated"
    fixture.mkdir(parents=True)
    (fixture / "index.html").write_text("<h1>Updated by writeback</h1>\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "test: writeback e2e")
    monkeypatch.chdir(tmp_path)

    _run(
        "assert-ephemeral-writeback.py",
        {
            "DEVFLOWS_FIXTURE_PATH": "fx",
            "DEVFLOWS_ASSERTIONS": json.dumps(_writeback_assertions()),
        },
        monkeypatch,
    )


def test_assert_ephemeral_writeback_fails_on_wrong_commit_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    _git(tmp_path, "config", "user.email", "t@example.test")
    _git(tmp_path, "config", "user.name", "Tester")
    fixture = tmp_path / "fx" / "generated"
    fixture.mkdir(parents=True)
    (fixture / "index.html").write_text("<h1>Updated by writeback</h1>\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "wrong message")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        _run(
            "assert-ephemeral-writeback.py",
            {
                "DEVFLOWS_FIXTURE_PATH": "fx",
                "DEVFLOWS_ASSERTIONS": json.dumps(_writeback_assertions()),
            },
            monkeypatch,
        )
