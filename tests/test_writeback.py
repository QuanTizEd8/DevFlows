from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

APPLY_PATCH = Path("workflows/writeback/scripts/apply-patch.py")


# --------------------------------------------------------------------------- #
# happy paths                                                                  #
# --------------------------------------------------------------------------- #
def test_apply_patch_adds_modifies_deletes_and_commits(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    (target / "mod.txt").write_text("old\n", encoding="utf-8")
    (target / "remove.txt").write_text("bye\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")

    patch = _build_patch(
        target,
        lambda w: (
            (w / "new.txt").write_text("new\n", encoding="utf-8"),
            (w / "mod.txt").write_text("new content\n", encoding="utf-8"),
            (w / "remove.txt").unlink(),
        ),
    )
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    _apply(target, patch_file)

    assert (target / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert (target / "mod.txt").read_text(encoding="utf-8") == "new content\n"
    assert not (target / "remove.txt").exists()
    assert (target / "keep.txt").exists()
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "writeback"
    assert _git_stdout(target, "status", "--short") == ""


def test_apply_patch_with_hidden_directory(tmp_path: Path) -> None:
    """A patch touching a dot-directory (.github/**) applies with no special casing.

    The old manifest payload had to opt into upload-artifact's hidden-file handling;
    a single patch file carries hidden paths inline, so nothing extra is needed.
    """
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    patch = _build_patch(
        target,
        lambda w: (
            (w / ".github").mkdir(),
            (w / ".github/generated.yml").write_text("on: push\n", encoding="utf-8"),
        ),
    )
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    _apply(target, patch_file)
    assert (target / ".github/generated.yml").read_text(encoding="utf-8") == "on: push\n"


def test_apply_patch_pushes_when_commit_push_true(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    target = _init_target(tmp_path)
    (target / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")
    _git(target, "remote", "add", "origin", str(remote))
    _git(target, "push", "-u", "origin", "main")

    patch = _build_patch(
        target, lambda w: (w / "added.txt").write_text("added\n", encoding="utf-8")
    )
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    _apply(target, patch_file, push=True)

    pushed = subprocess.run(
        ["git", "-C", str(remote), "log", "-1", "--pretty=%s", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert pushed == "writeback"


# --------------------------------------------------------------------------- #
# three-way / drift                                                            #
# --------------------------------------------------------------------------- #
def test_apply_patch_three_way_when_target_advanced(tmp_path: Path) -> None:
    """A patch still applies when the branch advanced with a non-conflicting change."""
    target = _init_target(tmp_path)
    (target / "a.txt").write_text("original\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")

    patch = _build_patch(
        target, lambda w: (w / "a.txt").write_text("changed by patch\n", encoding="utf-8")
    )
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    # Advance the branch with an unrelated file, so HEAD is no longer the patch base.
    (target / "b.txt").write_text("added later\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "advance")

    _apply(target, patch_file)
    assert (target / "a.txt").read_text(encoding="utf-8") == "changed by patch\n"
    assert (target / "b.txt").exists()


def test_apply_patch_expected_base_sha_guard_aborts_on_mismatch(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")
    patch = _build_patch(target, lambda w: (w / "x.txt").write_text("x\n", encoding="utf-8"))
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    result = _apply(target, patch_file, expected_base="0" * 40, check=False)
    assert result.returncode != 0
    assert "expected" in result.stderr
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "initial"


def test_apply_patch_expected_base_sha_guard_allows_match(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    (target / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")
    base = _git_stdout(target, "rev-parse", "HEAD")

    patch = _build_patch(target, lambda w: (w / "x.txt").write_text("x\n", encoding="utf-8"))
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    _apply(target, patch_file, expected_base=base)
    assert (target / "x.txt").exists()


# --------------------------------------------------------------------------- #
# no-op / failure                                                              #
# --------------------------------------------------------------------------- #
def test_apply_empty_patch_is_noop(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    (target / "keep.txt").write_text("keep\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")

    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(b"")

    result = _apply(target, patch_file, check=False)
    assert result.returncode == 0
    assert "empty" in result.stdout.lower()
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "initial"


def test_apply_missing_patch_file_fails(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    result = _apply(target, tmp_path / "nope.patch", check=False)
    assert result.returncode != 0
    assert "not be found" in result.stderr or "not found" in result.stderr.lower()


def test_apply_malformed_patch_fails_loudly(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    _git(target, "commit", "--allow-empty", "-m", "initial")

    patch_file = tmp_path / "changes.patch"
    patch_file.write_text("this is not a valid patch\n", encoding="utf-8")

    result = _apply(target, patch_file, check=False)
    assert result.returncode != 0
    assert "git apply" in result.stderr
    assert _git_stdout(target, "log", "-1", "--pretty=%s") == "initial"


def test_apply_conflicting_patch_fails(tmp_path: Path) -> None:
    target = _init_target(tmp_path)
    (target / "c.txt").write_text("line one\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "initial")

    patch = _build_patch(
        target, lambda w: (w / "c.txt").write_text("patched line\n", encoding="utf-8")
    )
    patch_file = tmp_path / "changes.patch"
    patch_file.write_bytes(patch)

    # Rewrite the same line differently and commit, so the 3-way merge conflicts.
    (target / "c.txt").write_text("diverged line\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "diverge")

    result = _apply(target, patch_file, check=False)
    assert result.returncode != 0
    assert "git apply" in result.stderr


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _init_target(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Initial Author")
    _git(target, "config", "user.email", "initial@example.test")
    return target


def _build_patch(repo: Path, mutate: Callable[[Path], object]) -> bytes:
    """Mutate the working tree, capture `git diff --cached --binary`, then restore.

    This mirrors the patch-emit channel (git add -A; git diff --cached --binary;
    git reset) and leaves the repo back at its committed state so the patch is
    applied to a clean checkout, exactly as writeback does.
    """
    mutate(repo)
    _git(repo, "add", "-A")
    patch = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--binary"],
        check=True,
        capture_output=True,
    ).stdout
    _git(repo, "reset", "--hard", "HEAD")
    _git(repo, "clean", "-fd")
    return patch


def _apply(
    target: Path,
    patch_file: Path,
    *,
    push: bool = False,
    expected_base: str = "",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(APPLY_PATCH.resolve())],
        cwd=target,
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(target),
            "WRITEBACK_PATCH_FILE": str(patch_file),
            "WRITEBACK_EXPECTED_BASE_SHA": expected_base,
            "COMMIT_AUTHOR_NAME": "DevFlows Bot",
            "COMMIT_AUTHOR_EMAIL": "devflows@example.test",
            "COMMIT_BRANCH": "main",
            "COMMIT_MESSAGE": "writeback",
            "COMMIT_PUSH": "true" if push else "false",
        },
        check=check,
        capture_output=True,
        text=True,
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
