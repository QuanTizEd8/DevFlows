from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow

SCRIPT_DIR = Path("workflows/python-test/scripts")

# Workflow-specific inputs the published interface must expose (design after the
# lead ruling that removed Codecov, plus the harmonizer naming conventions).
EXPECTED_INPUTS = {
    "test-matrix",
    "test-env-manager",
    "test-environment-file",
    "test-install-source",
    "test-source-directory",
    "test-dist-path",
    "test-install-prefer",
    "test-install-extras",
    "test-dependency-groups",
    "test-dependencies",
    "test-command",
    "test-working-directory",
    "test-fail-fast",
    "test-timeout-minutes",
    "uv-version",
    "uv-cache-mode",
    "micromamba-version",
    "micromamba-cache-enabled",
    "report-artifact-enabled",
    "report-path",
    "report-artifact-name",
    "report-merge-enabled",
    "report-artifact-retention-days",
    "report-artifact-include-hidden-files",
}


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATE = _load("validate-inputs")
INSTALL = _load("install-package")
RUNTESTS = _load("run-tests")


def _normalize(matrix: str, **overrides):
    kwargs = {
        "raw_matrix": matrix,
        "env_manager": "uv",
        "workflow_env_file": "",
        "install_source": "source",
        "install_prefer": "wheel",
        "dependency_groups": "",
        "report_enabled": False,
        "report_path": "",
    }
    kwargs.update(overrides)
    return VALIDATE.normalize(**kwargs)


# --------------------------------------------------------------- validate-inputs


def test_uv_leg_normalizes_with_derived_name() -> None:
    legs = _normalize('[{"runner": "ubuntu-latest", "python-version": "3.13"}]')
    assert legs == [
        {
            "runner": "ubuntu-latest",
            "name": "ubuntu-latest-py3.13",
            "test-arguments": "",
            "python-version": "3.13",
        }
    ]


def test_explicit_name_and_test_arguments_are_preserved() -> None:
    legs = _normalize(
        '[{"runner": "ubuntu-latest", "python-version": "3.12", '
        '"name": "linux", "test-arguments": "-k smoke"}]'
    )
    assert legs[0]["name"] == "linux"
    assert legs[0]["test-arguments"] == "-k smoke"


def test_array_runner_is_kept_and_used_in_derived_name() -> None:
    legs = _normalize('[{"runner": ["self-hosted", "linux"], "python-version": "3.13"}]')
    assert legs[0]["runner"] == ["self-hosted", "linux"]
    assert legs[0]["name"] == "self-hosted-linux-py3.13"


def test_duplicate_leg_names_fail() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize(
            '[{"runner": "ubuntu-latest", "python-version": "3.13", "name": "x"}, '
            '{"runner": "ubuntu-latest", "python-version": "3.12", "name": "x"}]'
        )
    assert "unique" in str(excinfo.value)


def test_unknown_leg_key_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize('[{"runner": "ubuntu-latest", "python-version": "3.13", "os": "linux"}]')
    assert "unknown keys" in str(excinfo.value)


def test_uv_leg_requires_python_version() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize('[{"runner": "ubuntu-latest"}]')
    assert "python-version" in str(excinfo.value)


def test_invalid_matrix_json_fails() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize("not-json")
    assert "valid JSON" in str(excinfo.value)


def test_empty_matrix_fails() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize("[]")
    assert "must not be empty" in str(excinfo.value)


def test_non_object_leg_fails() -> None:
    with pytest.raises(SystemExit):
        _normalize('["ubuntu-latest"]')


@pytest.mark.parametrize(
    "field,value,fragment",
    [
        ("env_manager", "conda", "test-env-manager"),
        ("install_source", "wheelhouse", "test-install-source"),
        ("install_prefer", "egg", "test-install-prefer"),
    ],
)
def test_enum_inputs_are_validated(field, value, fragment) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize('[{"runner": "ubuntu-latest", "python-version": "3.13"}]', **{field: value})
    assert fragment in str(excinfo.value)


def test_report_enabled_requires_report_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize(
            '[{"runner": "ubuntu-latest", "python-version": "3.13"}]',
            report_enabled=True,
            report_path="   ",
        )
    assert "report-path" in str(excinfo.value)


def test_env_file_is_forbidden_with_uv() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize(
            '[{"runner": "ubuntu-latest", "python-version": "3.13"}]',
            workflow_env_file="env.yml",
        )
    assert "uv" in str(excinfo.value)


def test_micromamba_requires_environment_file() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize(
            '[{"runner": "ubuntu-latest", "python-version": "3.13"}]',
            env_manager="micromamba",
        )
    assert "environment file" in str(excinfo.value)


def test_micromamba_leg_resolves_env_file_and_create_args() -> None:
    legs = _normalize(
        '[{"runner": "ubuntu-latest", "python-version": "3.12", "name": "m"}]',
        env_manager="micromamba",
        workflow_env_file="env.yml",
    )
    assert legs[0]["environment-file"] == "env.yml"
    assert legs[0]["create-args"] == "python=3.12"


def test_micromamba_leg_without_python_version_has_empty_create_args() -> None:
    legs = _normalize(
        '[{"runner": "ubuntu-latest", "name": "m", "environment-file": "leg.yml"}]',
        env_manager="micromamba",
    )
    assert legs[0]["environment-file"] == "leg.yml"
    assert legs[0]["create-args"] == ""
    assert "python-version" not in legs[0]


def test_leg_environment_file_overrides_workflow_env_file() -> None:
    legs = _normalize(
        '[{"runner": "ubuntu-latest", "python-version": "3.12", '
        '"name": "m", "environment-file": "leg.yml"}]',
        env_manager="micromamba",
        workflow_env_file="workflow.yml",
    )
    assert legs[0]["environment-file"] == "leg.yml"


def test_dependency_groups_forbidden_with_micromamba() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _normalize(
            '[{"runner": "ubuntu-latest", "name": "m", "environment-file": "env.yml"}]',
            env_manager="micromamba",
            dependency_groups="docs",
        )
    assert "test-dependency-groups" in str(excinfo.value)


def test_main_writes_normalized_matrix_to_github_output(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("TEST_MATRIX", '[{"runner": "ubuntu-latest", "python-version": "3.13"}]')
    monkeypatch.setenv("TEST_ENV_MANAGER", "uv")
    for name in ("TEST_ENVIRONMENT_FILE", "TEST_DEPENDENCY_GROUPS", "REPORT_PATH"):
        monkeypatch.delenv(name, raising=False)

    assert VALIDATE.main() == 0
    line = output.read_text(encoding="utf-8").strip()
    assert line.startswith("matrix=")
    payload = json.loads(line[len("matrix=") :])
    assert payload[0]["runner"] == "ubuntu-latest"
    assert payload[0]["python-version"] == "3.13"


# --------------------------------------------------------------- install-package


def _capture_runs(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(INSTALL.subprocess, "run", fake_run)
    return calls


def _install_env(monkeypatch, **env) -> None:
    defaults = {
        "TEST_ENV_MANAGER": "uv",
        "TEST_INSTALL_SOURCE": "source",
        "TEST_SOURCE_DIRECTORY": ".",
        "TEST_DIST_PATH": "dist",
        "TEST_INSTALL_PREFER": "wheel",
        "TEST_INSTALL_EXTRAS": "",
        "TEST_DEPENDENCY_GROUPS": "",
        "TEST_DEPENDENCIES": "",
    }
    defaults.update(env)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)


def test_source_install_uses_uv_pip_with_resolved_path(monkeypatch, tmp_path) -> None:
    calls = _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_SOURCE_DIRECTORY=str(tmp_path))
    assert INSTALL.main() == 0
    assert calls[0][:3] == ["uv", "pip", "install"]
    assert calls[0][-1] == str(tmp_path.resolve())


def test_source_install_appends_extras(monkeypatch, tmp_path) -> None:
    calls = _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_SOURCE_DIRECTORY=str(tmp_path), TEST_INSTALL_EXTRAS="test\nplot")
    assert INSTALL.main() == 0
    assert calls[0][-1] == f"{tmp_path.resolve()}[test,plot]"


def test_missing_source_directory_fails(monkeypatch, tmp_path) -> None:
    _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_SOURCE_DIRECTORY=str(tmp_path / "nope"))
    with pytest.raises(SystemExit) as excinfo:
        INSTALL.main()
    assert "test-source-directory does not exist" in str(excinfo.value)


def test_artifact_install_resolves_name_and_find_links(monkeypatch, tmp_path) -> None:
    (tmp_path / "sampledist-1.2.3-py3-none-any.whl").write_bytes(b"x")
    calls = _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_INSTALL_SOURCE="artifact", TEST_DIST_PATH=str(tmp_path))
    assert INSTALL.main() == 0
    command = calls[0]
    assert command[:3] == ["uv", "pip", "install"]
    assert "--no-index" in command
    assert "--find-links" in command
    assert command[command.index("--find-links") + 1] == str(tmp_path)
    assert command[-1] == "sampledist"


def test_artifact_install_prefer_sdist_adds_no_binary(monkeypatch, tmp_path) -> None:
    (tmp_path / "sampledist-1.0.0.tar.gz").write_bytes(b"x")
    calls = _capture_runs(monkeypatch)
    _install_env(
        monkeypatch,
        TEST_INSTALL_SOURCE="artifact",
        TEST_DIST_PATH=str(tmp_path),
        TEST_INSTALL_PREFER="sdist",
    )
    assert INSTALL.main() == 0
    command = calls[0]
    assert command[command.index("--no-binary") + 1] == "sampledist"


def test_artifact_install_no_distributions_fails(monkeypatch, tmp_path) -> None:
    _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_INSTALL_SOURCE="artifact", TEST_DIST_PATH=str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        INSTALL.main()
    assert "no wheels or sdists" in str(excinfo.value)


def test_artifact_install_missing_directory_fails(monkeypatch, tmp_path) -> None:
    _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_INSTALL_SOURCE="artifact", TEST_DIST_PATH=str(tmp_path / "gone"))
    with pytest.raises(SystemExit) as excinfo:
        INSTALL.main()
    assert "is not a directory" in str(excinfo.value)


def test_artifact_install_multiple_package_names_fails(monkeypatch, tmp_path) -> None:
    (tmp_path / "foo-1.0-py3-none-any.whl").write_bytes(b"x")
    (tmp_path / "bar-1.0-py3-none-any.whl").write_bytes(b"x")
    _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_INSTALL_SOURCE="artifact", TEST_DIST_PATH=str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        INSTALL.main()
    assert "multiple package names" in str(excinfo.value)


def test_micromamba_installer_uses_python_pip(monkeypatch, tmp_path) -> None:
    calls = _capture_runs(monkeypatch)
    _install_env(monkeypatch, TEST_ENV_MANAGER="micromamba", TEST_SOURCE_DIRECTORY=str(tmp_path))
    assert INSTALL.main() == 0
    assert calls[0][:4] == ["python", "-m", "pip", "install"]


def test_dependency_groups_install_uses_group_flags(monkeypatch, tmp_path) -> None:
    calls = _capture_runs(monkeypatch)
    _install_env(
        monkeypatch,
        TEST_SOURCE_DIRECTORY=str(tmp_path),
        TEST_DEPENDENCY_GROUPS="docs\ntest",
    )
    assert INSTALL.main() == 0
    group_call = calls[-1]
    assert group_call[:3] == ["uv", "pip", "install"]
    assert group_call.count("--group") == 2
    assert "docs" in group_call and "test" in group_call


def test_extra_dependencies_are_installed(monkeypatch, tmp_path) -> None:
    calls = _capture_runs(monkeypatch)
    _install_env(
        monkeypatch, TEST_SOURCE_DIRECTORY=str(tmp_path), TEST_DEPENDENCIES="pytest\npytest-cov"
    )
    assert INSTALL.main() == 0
    assert calls[-1] == ["uv", "pip", "install", "pytest", "pytest-cov"]


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Sample_Dist-1.0-py3-none-any.whl", "sample-dist"),
        ("my_pkg-2.0.0-cp311-cp311-linux_x86_64.whl", "my-pkg"),
        ("my-pkg-1.0.0.tar.gz", "my-pkg"),
        ("Some.Name-0.1.tar.gz", "some-name"),
    ],
)
def test_project_name_parsing(filename, expected) -> None:
    assert INSTALL._project_name(Path(filename)) == expected


def test_install_run_propagates_nonzero_exit(monkeypatch, tmp_path) -> None:
    def fake_run(argv, *args, **kwargs):
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(INSTALL.subprocess, "run", fake_run)
    _install_env(monkeypatch, TEST_SOURCE_DIRECTORY=str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        INSTALL.main()
    assert excinfo.value.code == 7


# ------------------------------------------------------------------- run-tests


def test_run_tests_builds_argv_and_returns_code(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, *args, **kwargs):
        captured["argv"] = list(argv)
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(RUNTESTS.subprocess, "run", fake_run)
    monkeypatch.setenv("TEST_COMMAND", "pytest --maxfail=1")
    monkeypatch.setenv("TEST_ARGUMENTS", "-k smoke")
    monkeypatch.setenv("TEST_WORKING_DIRECTORY", str(tmp_path))

    assert RUNTESTS.main() == 0
    assert captured["argv"] == ["pytest", "--maxfail=1", "-k", "smoke"]
    assert captured["cwd"] == str(tmp_path)


def test_run_tests_propagates_exit_code(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        RUNTESTS.subprocess,
        "run",
        lambda argv, *a, **k: subprocess.CompletedProcess(argv, 5),
    )
    monkeypatch.setenv("TEST_COMMAND", "pytest")
    monkeypatch.setenv("TEST_ARGUMENTS", "")
    monkeypatch.setenv("TEST_WORKING_DIRECTORY", str(tmp_path))
    assert RUNTESTS.main() == 5


def test_run_tests_empty_command_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        RUNTESTS.subprocess, "run", lambda *a, **k: pytest.fail("must not run empty command")
    )
    monkeypatch.setenv("TEST_COMMAND", "   ")
    monkeypatch.setenv("TEST_ARGUMENTS", "")
    monkeypatch.setenv("TEST_WORKING_DIRECTORY", str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        RUNTESTS.main()
    assert "test-command must not be empty" in str(excinfo.value)


def test_run_tests_missing_working_directory_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RUNTESTS.subprocess, "run", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setenv("TEST_COMMAND", "pytest")
    monkeypatch.setenv("TEST_ARGUMENTS", "")
    monkeypatch.setenv("TEST_WORKING_DIRECTORY", str(tmp_path / "gone"))
    with pytest.raises(SystemExit) as excinfo:
        RUNTESTS.main()
    assert "test-working-directory does not exist" in str(excinfo.value)


# ------------------------------------------------------------ interface snapshot


def _published():
    item = next(item for item in load_catalog() if item.id == "python-test")
    return build_published_workflow(item)


def test_published_interface_matches_design_after_conventions() -> None:
    workflow = _published()
    inputs = workflow["on"]["workflow_call"]["inputs"]
    workflow_specific = {
        name
        for name in inputs
        if not name.startswith(("checkout-", "artifact-download-", "artifact-upload-", "commit-"))
    }
    assert workflow_specific == EXPECTED_INPUTS
    # Channel inputs are injected by the generator.
    assert "checkout-enabled" in inputs
    assert "artifact-download-enabled" in inputs
    # Codecov inputs were removed from v1 (lead ruling).
    assert not any(name.startswith("coverage-") for name in inputs)
    outputs = workflow["on"]["workflow_call"]["outputs"]
    assert set(outputs) == {"report-artifact-name"}


def test_test_job_stays_read_only_without_id_token() -> None:
    workflow = _published()
    permissions = workflow["jobs"]["test"]["permissions"]
    assert permissions == {"contents": "read", "actions": "read"}
    assert "id-token" not in permissions
    assert workflow["permissions"] == {"contents": "read"}
