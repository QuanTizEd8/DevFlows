"""Exercise the extracted scenario-harness scripts as real, testable code.

The scripts under ``harness/scenarios`` are the source of truth invoked by the
generated scenario workflows. Extracting them from string constants means ruff
lints them and these tests can run their logic directly.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

# Resolve now so tests that chdir into a tmp dir still find the scripts.
HARNESS = Path("harness/scenarios").resolve()


def _run(script: str, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    runpy.run_path(str(HARNESS / script), run_name="__main__")


def test_assert_result_passes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _run("assert-result.py", {"ACTUAL_RESULT": "success"}, monkeypatch)


def test_assert_result_fails_on_non_success(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        _run("assert-result.py", {"ACTUAL_RESULT": "failure"}, monkeypatch)


def test_assert_equals_matches_and_mismatches(monkeypatch: pytest.MonkeyPatch) -> None:
    _run("assert-equals.py", {"ASSERT_NAME": "n", "EXPECTED": "x", "ACTUAL": "x"}, monkeypatch)
    with pytest.raises(SystemExit):
        _run("assert-equals.py", {"ASSERT_NAME": "n", "EXPECTED": "x", "ACTUAL": "y"}, monkeypatch)


def test_assert_file_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    present = tmp_path / "present.txt"
    present.write_text("hi", encoding="utf-8")
    _run("assert-file-exists.py", {"ASSERT_PATH": str(present)}, monkeypatch)
    with pytest.raises(SystemExit):
        _run("assert-file-exists.py", {"ASSERT_PATH": str(tmp_path / "missing.txt")}, monkeypatch)


def test_assert_file_contains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "doc.html"
    target.write_text("<h1>Title</h1>", encoding="utf-8")
    _run("assert-file-contains.py", {"ASSERT_PATH": str(target), "ASSERT_TEXT": "<h1"}, monkeypatch)
    with pytest.raises(SystemExit):
        _run(
            "assert-file-contains.py",
            {"ASSERT_PATH": str(target), "ASSERT_TEXT": "absent"},
            monkeypatch,
        )


def test_create_setup_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    _run(
        "create-setup-files.py",
        {"DEVFLOWS_SETUP_FILES": '[{"path": "nested/out.txt", "content": "body"}]'},
        monkeypatch,
    )
    assert (tmp_path / "nested/out.txt").read_text(encoding="utf-8") == "body"


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "../escape.txt", ".git/hooks/pre-commit", ".devflows-writeback/x"],
)
def test_create_setup_files_rejects_unsafe_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad_path: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        _run(
            "create-setup-files.py",
            {"DEVFLOWS_SETUP_FILES": json.dumps([{"path": bad_path, "content": "x"}])},
            monkeypatch,
        )


def test_create_setup_files_content_base64(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import base64

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    payload = bytes(range(256))  # a non-UTF-8 binary blob
    _run(
        "create-setup-files.py",
        {
            "DEVFLOWS_SETUP_FILES": json.dumps(
                [{"path": "bin/blob.dat", "content-base64": base64.b64encode(payload).decode()}]
            )
        },
        monkeypatch,
    )
    assert (tmp_path / "bin/blob.dat").read_bytes() == payload


def test_create_setup_files_source_path_copies_from_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    payload = bytes(range(256))
    source = tmp_path / "fixtures/example.whl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)
    _run(
        "create-setup-files.py",
        {
            "DEVFLOWS_SETUP_FILES": json.dumps(
                [{"path": "wheelhouse/example.whl", "source-path": "fixtures/example.whl"}]
            )
        },
        monkeypatch,
    )
    assert (tmp_path / "wheelhouse/example.whl").read_bytes() == payload


def test_create_setup_files_source_path_rejects_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        _run(
            "create-setup-files.py",
            {
                "DEVFLOWS_SETUP_FILES": json.dumps(
                    [{"path": "out.dat", "source-path": "../outside.dat"}]
                )
            },
            monkeypatch,
        )


def test_create_setup_files_source_path_missing_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        _run(
            "create-setup-files.py",
            {
                "DEVFLOWS_SETUP_FILES": json.dumps(
                    [{"path": "out.dat", "source-path": "fixtures/absent.dat"}]
                )
            },
            monkeypatch,
        )


@pytest.mark.parametrize(
    "item",
    [
        {"path": "a.txt"},  # no source
        {"path": "a.txt", "content": "x", "content-base64": "eA=="},  # two sources
    ],
)
def test_create_setup_files_requires_exactly_one_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, item: dict
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        _run("create-setup-files.py", {"DEVFLOWS_SETUP_FILES": json.dumps([item])}, monkeypatch)


def test_assert_result_honors_expected_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Expect-failure scenarios pass EXPECTED_RESULT=failure.
    _run(
        "assert-result.py",
        {"ACTUAL_RESULT": "failure", "EXPECTED_RESULT": "failure"},
        monkeypatch,
    )
    with pytest.raises(SystemExit):
        _run(
            "assert-result.py",
            {"ACTUAL_RESULT": "success", "EXPECTED_RESULT": "failure"},
            monkeypatch,
        )
