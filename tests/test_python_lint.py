from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow

SCRIPT_DIR = Path("workflows/python-lint/scripts")


def _load(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    module_name = "devflows_python_lint_" + name.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve string annotations against
    # the module's namespace (it looks the module up in sys.modules).
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                           #
# --------------------------------------------------------------------------- #
def _validate_env(tmp_path: Path) -> dict[str, str]:
    return {
        "GITHUB_WORKSPACE": str(tmp_path),
        "LINT_PATHS": ".",
        "LINT_WORKING_DIRECTORY": ".",
        "LINT_REPORT_DIRECTORY": "",
        "LINT_UV_CACHE_MODE": "auto",
        "LINT_UV_SYNC_ENABLED": "false",
        "LINT_UV_SYNC_ARGUMENTS": "",
        "LINT_RUFF_CHECK_ENABLED": "true",
        "LINT_RUFF_CHECK_ARGUMENTS": "",
        "LINT_RUFF_FORMAT_ENABLED": "true",
        "LINT_RUFF_FORMAT_ARGUMENTS": "",
        "LINT_RUFF_VERSION": "",
        "LINT_TYPECHECK_ENABLED": "true",
        "LINT_TYPECHECK_TOOL": "mypy",
        "LINT_TYPECHECK_VERSION": "",
        "LINT_TYPECHECK_ARGUMENTS": "",
        "LINT_TYPECHECK_PYTHON_VERSIONS": "[]",
        "LINT_TYPECHECK_WITH": "",
    }


def _run_validate(monkeypatch, tmp_path: Path, **overrides: str) -> None:
    module = _load("validate-inputs.py")
    env = {**_validate_env(tmp_path), **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0


def _expect_validate_error(monkeypatch, tmp_path: Path, message: str, **overrides: str) -> None:
    module = _load("validate-inputs.py")
    env = {**_validate_env(tmp_path), **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_accepts_defaults(monkeypatch, tmp_path) -> None:
    _run_validate(monkeypatch, tmp_path)


def test_validate_accepts_full_pinned_configuration(monkeypatch, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    _run_validate(
        monkeypatch,
        tmp_path,
        LINT_PATHS="src\n.",
        LINT_UV_SYNC_ENABLED="true",
        LINT_UV_SYNC_ARGUMENTS="--all-extras --group typing",
        LINT_RUFF_VERSION="0.14.2",
        LINT_RUFF_CHECK_ARGUMENTS="--select E,F --preview",
        LINT_TYPECHECK_TOOL="pyright",
        LINT_TYPECHECK_VERSION="1.1.400",
        LINT_TYPECHECK_ARGUMENTS="--strict",
        LINT_TYPECHECK_PYTHON_VERSIONS='["3.11", "3.13"]',
        LINT_TYPECHECK_WITH="types-requests\n.",
    )


def test_validate_rejects_empty_lint_paths(monkeypatch, tmp_path) -> None:
    _expect_validate_error(monkeypatch, tmp_path, "lint-paths must not be empty", LINT_PATHS="  ")


def test_validate_rejects_missing_path(monkeypatch, tmp_path) -> None:
    _expect_validate_error(monkeypatch, tmp_path, "does not exist", LINT_PATHS="nope")


def test_validate_rejects_path_escape(monkeypatch, tmp_path) -> None:
    _expect_validate_error(monkeypatch, tmp_path, "escapes the workspace", LINT_PATHS="../evil")


def test_validate_rejects_working_directory_outside_workspace(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch, tmp_path, "inside GITHUB_WORKSPACE", LINT_WORKING_DIRECTORY="../escape"
    )


def test_validate_rejects_unknown_typecheck_tool(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch, tmp_path, "typecheck-tool must be one of", LINT_TYPECHECK_TOOL="pytype"
    )


def test_validate_rejects_malformed_version_json(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "must be a JSON array",
        LINT_TYPECHECK_PYTHON_VERSIONS="3.11, 3.13",
    )


def test_validate_rejects_bad_target_version(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "must match 3.<minor>",
        LINT_TYPECHECK_PYTHON_VERSIONS='["3.11", "cpython"]',
    )


def test_validate_rejects_all_tools_disabled(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "must be true",
        LINT_RUFF_CHECK_ENABLED="false",
        LINT_RUFF_FORMAT_ENABLED="false",
        LINT_TYPECHECK_ENABLED="false",
    )


@pytest.mark.parametrize("flag", ["--fix", "--fix-only", "--unsafe-fixes", "--output-format=json"])
def test_validate_rejects_forbidden_ruff_check_arguments(monkeypatch, tmp_path, flag) -> None:
    _expect_validate_error(
        monkeypatch, tmp_path, "read-only", LINT_RUFF_CHECK_ARGUMENTS=f"--select F {flag}"
    )


def test_validate_rejects_typecheck_python_version_override(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "controlled by typecheck-python-versions",
        LINT_TYPECHECK_ARGUMENTS="--python-version 3.12",
    )


def test_validate_rejects_uv_sync_without_pyproject(monkeypatch, tmp_path) -> None:
    _expect_validate_error(monkeypatch, tmp_path, "no pyproject.toml", LINT_UV_SYNC_ENABLED="true")


def test_validate_rejects_uv_sync_arguments_without_sync(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "uv-sync-enabled is false",
        LINT_UV_SYNC_ARGUMENTS="--locked",
    )


def test_validate_rejects_bad_version_string(monkeypatch, tmp_path) -> None:
    _expect_validate_error(monkeypatch, tmp_path, "bare version string", LINT_RUFF_VERSION=">=0.14")


def test_validate_rejects_bad_uv_cache_mode(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch, tmp_path, "uv-cache-mode must be one of", LINT_UV_CACHE_MODE="yes"
    )


def test_validate_rejects_flag_in_typecheck_with(monkeypatch, tmp_path) -> None:
    _expect_validate_error(
        monkeypatch,
        tmp_path,
        "requirement specifiers, not flags",
        LINT_TYPECHECK_WITH="--index-url https://example.com",
    )


# --------------------------------------------------------------------------- #
# run-lint.py: command construction                                            #
# --------------------------------------------------------------------------- #
def test_ruff_command_uvx_latest() -> None:
    module = _load("run-lint.py")
    assert module._ruff_command(["check", "."], "", False) == ["uvx", "ruff", "check", "."]


def test_ruff_command_uvx_pinned() -> None:
    module = _load("run-lint.py")
    assert module._ruff_command(["check", "."], "0.14.2", False) == [
        "uvx",
        "ruff@0.14.2",
        "check",
        ".",
    ]


def test_ruff_command_project_env_when_synced_and_unpinned() -> None:
    module = _load("run-lint.py")
    assert module._ruff_command(["check", "."], "", True) == [
        "uv",
        "run",
        "--no-sync",
        "ruff",
        "check",
        ".",
    ]


def test_ruff_command_pinned_wins_over_sync() -> None:
    module = _load("run-lint.py")
    # A pinned ruff always runs via uvx, even in sync mode, for reproducibility.
    assert module._ruff_command(["check"], "0.14.2", True)[0] == "uvx"


def test_typecheck_command_uvx_with_target_and_stubs() -> None:
    module = _load("run-lint.py")
    command = module._typecheck_command(
        "mypy", "1.11.0", "3.11", ["--strict"], ["types-requests"], ["src"], False
    )
    assert command == [
        "uvx",
        "--with",
        "types-requests",
        "mypy@1.11.0",
        "--python-version",
        "3.11",
        "--strict",
        "src",
    ]


def test_typecheck_command_pyright_uses_pythonversion_flag() -> None:
    module = _load("run-lint.py")
    command = module._typecheck_command("pyright", "", "3.13", [], [], ["."], False)
    assert "--pythonversion" in command
    assert "3.13" in command
    assert command[1] == "pyright"


def test_typecheck_command_sync_layers_tool_with_flag() -> None:
    module = _load("run-lint.py")
    command = module._typecheck_command("mypy", "1.11.0", None, [], ["."], ["."], True)
    assert command[:5] == ["uv", "run", "--no-sync", "--with", "mypy==1.11.0"]
    assert command[-2:] == ["mypy", "."]


# --------------------------------------------------------------------------- #
# run-lint.py: parsing                                                         #
# --------------------------------------------------------------------------- #
def test_classify_maps_exit_codes() -> None:
    module = _load("run-lint.py")
    assert module._classify(0) == ("success", False)
    assert module._classify(1) == ("failure", False)
    assert module._classify(2) == ("failure", True)
    assert module._classify(127) == ("failure", True)


def test_parse_ruff_check_counts_and_annotates(tmp_path) -> None:
    module = _load("run-lint.py")
    stdout = json.dumps(
        [
            {
                "code": "F401",
                "filename": str(tmp_path / "pkg/mod.py"),
                "location": {"row": 1, "column": 8},
                "message": "`os` imported but unused",
            }
        ]
    )
    violations, annotations = module._parse_ruff_check(stdout, tmp_path)
    assert violations == 1
    assert annotations[0]["file"] == "pkg/mod.py"
    assert annotations[0]["line"] == "1"
    assert annotations[0]["title"] == "ruff F401"


def test_parse_ruff_check_handles_non_json() -> None:
    module = _load("run-lint.py")
    assert module._parse_ruff_check("boom", Path("/tmp")) == (0, [])


def test_parse_reformat_count_from_summary() -> None:
    module = _load("run-lint.py")
    text = "--- mod.py\n+++ mod.py\n@@ ...\n\n2 files would be reformatted"
    assert module._parse_reformat_count(text) == 2


def test_parse_reformat_count_fallback_to_headers() -> None:
    module = _load("run-lint.py")
    assert module._parse_reformat_count("--- a.py\n+++ a.py\n") == 1


def test_parse_typecheck_mypy(tmp_path) -> None:
    module = _load("run-lint.py")
    stdout = f"{tmp_path}/pkg/mod.py:3: error: Incompatible return value\nFound 1 error\n"
    errors, annotations = module._parse_typecheck("mypy", stdout, "", tmp_path)
    assert errors == 1
    assert annotations[0]["file"] == "pkg/mod.py"
    assert annotations[0]["line"] == "3"


def test_parse_typecheck_pyright(tmp_path) -> None:
    module = _load("run-lint.py")
    stdout = f"  {tmp_path}/mod.py:2:5 - error: bad type\n1 error\n"
    errors, annotations = module._parse_typecheck("pyright", stdout, "", tmp_path)
    assert errors == 1
    assert annotations[0]["col"] == "5"


# --------------------------------------------------------------------------- #
# run-lint.py: outcome matrix (full main() with faked subprocesses)            #
# --------------------------------------------------------------------------- #
def _run_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "gh-output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "gh-summary"),
        "LINT_PATHS": ".",
        "LINT_WORKING_DIRECTORY": ".",
        "LINT_ENFORCE": "true",
        "LINT_ANNOTATIONS_ENABLED": "true",
        "LINT_REPORT_DIRECTORY": "report",
        "LINT_UV_SYNC_ENABLED": "false",
        "LINT_UV_SYNC_ARGUMENTS": "",
        "LINT_RUFF_CHECK_ENABLED": "true",
        "LINT_RUFF_CHECK_ARGUMENTS": "",
        "LINT_RUFF_FORMAT_ENABLED": "true",
        "LINT_RUFF_FORMAT_ARGUMENTS": "",
        "LINT_RUFF_VERSION": "",
        "LINT_TYPECHECK_ENABLED": "true",
        "LINT_TYPECHECK_TOOL": "mypy",
        "LINT_TYPECHECK_VERSION": "",
        "LINT_TYPECHECK_ARGUMENTS": "",
        "LINT_TYPECHECK_PYTHON_VERSIONS": "[]",
        "LINT_TYPECHECK_WITH": "",
    }
    env.update(overrides)
    return env


def _fake_run(module: ModuleType, spec: dict[str, tuple[int, str, str]]):
    def fake(command: list[str], cwd: Path):
        if command[:2] == ["uv", "sync"]:
            key = "sync"
        elif "--output-format=json" in command:
            key = "ruff-check"
        elif "format" in command:
            key = "ruff-format"
        else:
            key = "typecheck"
        returncode, stdout, stderr = spec.get(key, (0, "", ""))
        return module.RunResult(returncode, stdout, stderr)

    return fake


def _drive_main(monkeypatch, tmp_path, spec, **overrides):
    module = _load("run-lint.py")
    for key, value in _run_env(tmp_path, **overrides).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, "_run", _fake_run(module, spec))
    exit_code = None
    raised = None
    try:
        exit_code = module.main()
    except SystemExit as error:
        raised = error
    outputs = _parse_output(tmp_path / "gh-output")
    results = json.loads((tmp_path / "report/results.json").read_text(encoding="utf-8"))
    return exit_code, raised, outputs, results


_RUFF_FINDING = (
    1,
    json.dumps([{"code": "F401", "filename": "m.py", "location": {}, "message": "x"}]),
    "",
)
_FORMAT_FINDING = (1, "--- m.py\n+++ m.py\n1 file would be reformatted", "")


def test_matrix_all_success(monkeypatch, tmp_path) -> None:
    exit_code, raised, outputs, results = _drive_main(
        monkeypatch, tmp_path, {"ruff-check": (0, "[]", ""), "ruff-format": (0, "", "")}
    )
    assert raised is None
    assert exit_code == 0
    assert outputs["lint-outcome"] == "success"
    assert outputs["ruff-check-outcome"] == "success"
    assert outputs["typecheck-outcome"] == "success"
    assert results["version"] == 1
    assert results["tools"]["ruff-check"]["violations"] == 0


def test_matrix_findings_enforced_fails(monkeypatch, tmp_path) -> None:
    exit_code, raised, outputs, _ = _drive_main(
        monkeypatch, tmp_path, {"ruff-check": _RUFF_FINDING}, LINT_ENFORCE="true"
    )
    assert isinstance(raised, SystemExit)
    assert exit_code is None
    # Outputs are still written before the enforcing failure.
    assert outputs["lint-outcome"] == "failure"
    assert outputs["ruff-check-outcome"] == "failure"


def test_matrix_findings_advisory_succeeds(monkeypatch, tmp_path) -> None:
    exit_code, raised, outputs, _ = _drive_main(
        monkeypatch,
        tmp_path,
        {"ruff-check": _RUFF_FINDING, "ruff-format": _FORMAT_FINDING},
        LINT_ENFORCE="false",
        LINT_TYPECHECK_ENABLED="false",
    )
    assert raised is None
    assert exit_code == 0
    assert outputs["lint-outcome"] == "failure"
    assert outputs["ruff-check-outcome"] == "failure"
    assert outputs["ruff-format-outcome"] == "failure"
    assert outputs["typecheck-outcome"] == "skipped"


def test_matrix_crash_fails_even_in_advisory_mode(monkeypatch, tmp_path) -> None:
    exit_code, raised, outputs, _ = _drive_main(
        monkeypatch,
        tmp_path,
        {"ruff-check": (2, "", "usage error")},
        LINT_ENFORCE="false",
    )
    assert isinstance(raised, SystemExit)
    assert exit_code is None
    assert outputs["lint-outcome"] == "failure"


def test_matrix_multi_version_typecheck_records_each(monkeypatch, tmp_path) -> None:
    exit_code, raised, outputs, results = _drive_main(
        monkeypatch,
        tmp_path,
        {"ruff-check": (0, "[]", ""), "ruff-format": (0, "", "")},
        LINT_TYPECHECK_PYTHON_VERSIONS='["3.11", "3.13"]',
    )
    assert raised is None
    assert exit_code == 0
    runs = results["tools"]["typecheck"]["runs"]
    assert [run["python-version"] for run in runs] == ["3.11", "3.13"]
    assert results["tools"]["typecheck"]["tool"] == "mypy"


def _parse_output(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


# --------------------------------------------------------------------------- #
# interface snapshot: generated workflow matches the design post-conventions   #
# --------------------------------------------------------------------------- #
def _python_lint():
    for item in load_catalog():
        if item.id == "python-lint":
            return item
    raise AssertionError("python-lint workflow not found in catalog")


def test_published_inputs_cover_design_and_conventions() -> None:
    workflow = build_published_workflow(_python_lint())
    inputs = workflow["on"]["workflow_call"]["inputs"]
    expected = {
        "lint-paths",
        "lint-working-directory",
        "lint-enforce",
        "lint-annotations-enabled",
        "lint-report-directory",
        "lint-timeout-minutes",
        "lint-python-version",
        "uv-version",
        "uv-cache-mode",
        "uv-sync-enabled",
        "uv-sync-arguments",
        "ruff-check-enabled",
        "ruff-check-arguments",
        "ruff-format-enabled",
        "ruff-format-arguments",
        "ruff-version",
        "typecheck-enabled",
        "typecheck-tool",
        "typecheck-version",
        "typecheck-arguments",
        "typecheck-python-versions",
        "typecheck-with",
    }
    assert expected <= set(inputs)
    # Convention: uv cache passthrough is uv-cache-mode (string), never -enabled.
    assert inputs["uv-cache-mode"]["type"] == "string"
    # io channels are present; writeback is not (read-only workflow).
    assert "checkout-enabled" in inputs
    assert "artifact-upload-enabled" in inputs
    assert not any(name.startswith("commit-") for name in inputs)


def test_published_outputs_are_renamed_per_conventions() -> None:
    workflow = build_published_workflow(_python_lint())
    outputs = set(workflow["on"]["workflow_call"]["outputs"])
    assert outputs == {
        "lint-outcome",
        "ruff-check-outcome",
        "ruff-format-outcome",
        "typecheck-outcome",
        "lint-results",
    }


def test_published_permissions_are_least_privilege() -> None:
    workflow = build_published_workflow(_python_lint())
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["python-lint"]
    # The artifact channels add actions: read; nothing is granted write.
    assert job["permissions"] == {"contents": "read", "actions": "read"}
