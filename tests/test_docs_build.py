from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_catalog
from devflows.publish import published_workflow_call

SCRIPT_DIR = Path("workflows/docs-build/scripts")


def _load_script(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py").replace("-", "_"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                           #
# --------------------------------------------------------------------------- #
def _validate_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    base = {
        "DOCS_TOOL": "sphinx",
        "DOCS_ENVIRONMENT": "pip",
        "DOCS_BUILD_COMMAND": "",
        "DOCS_WORKING_DIRECTORY": ".",
        "DOCS_OUTPUT_DIRECTORY": "_site",
        "DOCS_WARNINGS_AS_ERRORS": "false",
        "DOCS_LINKCHECK_ENABLED": "false",
        "SPHINX_BUILDER": "html",
        "SPHINX_ARGUMENTS": "",
        "MKDOCS_ARGUMENTS": "",
        "UV_CACHE_MODE": "auto",
        "PIP_REQUIREMENTS_FILE": "",
        "PIP_INSTALL_TARGETS": "sphinx",
        "PIXI_LOCKED": "true",
        "PIXI_FROZEN": "false",
        "MICROMAMBA_ENVIRONMENT_FILE": "",
        "CONTAINER_IMAGE": "",
        "CONTAINER_LOGIN_ENABLED": "false",
        "CONTAINER_PASSWORD_SET": "false",
        "PAGES_ARTIFACT_ENABLED": "false",
        "PAGES_ARTIFACT_NAME": "github-pages",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "gh-output"),
    }
    base.update(overrides)
    return base


def _run_validate(monkeypatch, tmp_path: Path, **overrides: str) -> ModuleType:
    module = _load_script("validate-inputs.py")
    for key, value in _validate_env(tmp_path, **overrides).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    return module


def _read_outputs(tmp_path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    output_file = tmp_path / "gh-output"
    if not output_file.exists():
        return parsed
    for line in output_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


def test_validate_pip_happy_path(monkeypatch, tmp_path) -> None:
    _run_validate(monkeypatch, tmp_path)
    outputs = _read_outputs(tmp_path)
    assert outputs["docs-output-directory"] == "_site"
    assert outputs["docs-linkcheck-report-directory"] == ""
    assert outputs["pages-artifact-name"] == ""


def test_validate_emits_linkcheck_and_pages_outputs(monkeypatch, tmp_path) -> None:
    _run_validate(
        monkeypatch,
        tmp_path,
        DOCS_LINKCHECK_ENABLED="true",
        PAGES_ARTIFACT_ENABLED="true",
        PAGES_ARTIFACT_NAME="my-pages",
    )
    outputs = _read_outputs(tmp_path)
    assert outputs["docs-linkcheck-report-directory"] == "_site-linkcheck"
    assert outputs["pages-artifact-name"] == "my-pages"


@pytest.mark.parametrize(
    "overrides",
    [
        {"DOCS_ENVIRONMENT": "uv", "UV_CACHE_MODE": "true", "PIP_INSTALL_TARGETS": ""},
        {"DOCS_ENVIRONMENT": "pixi", "PIP_INSTALL_TARGETS": ""},
        {
            "DOCS_ENVIRONMENT": "micromamba",
            "MICROMAMBA_ENVIRONMENT_FILE": "env.yml",
            "PIP_INSTALL_TARGETS": "",
        },
        {
            "DOCS_ENVIRONMENT": "container",
            "CONTAINER_IMAGE": "ghcr.io/org/docs:1",
            "PIP_INSTALL_TARGETS": "",
        },
        {"DOCS_TOOL": "mkdocs", "MKDOCS_ARGUMENTS": "--verbose", "SPHINX_BUILDER": ""},
        {"DOCS_BUILD_COMMAND": "make html", "SPHINX_ARGUMENTS": "", "SPHINX_BUILDER": ""},
    ],
)
def test_validate_accepts_valid_combinations(monkeypatch, tmp_path, overrides) -> None:
    _run_validate(monkeypatch, tmp_path, **overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DOCS_TOOL": "flatdoc"}, "docs-tool must be one of"),
        ({"DOCS_ENVIRONMENT": "conda"}, "docs-environment must be one of"),
        ({"DOCS_OUTPUT_DIRECTORY": ""}, "docs-output-directory must not be empty"),
        ({"DOCS_OUTPUT_DIRECTORY": "../escape"}, "GITHUB_WORKSPACE"),
        ({"DOCS_WORKING_DIRECTORY": "../escape"}, "GITHUB_WORKSPACE"),
        ({"DOCS_WORKING_DIRECTORY": "missing-subdir"}, "does not exist"),
        (
            {"DOCS_BUILD_COMMAND": "make html", "SPHINX_ARGUMENTS": "-W"},
            "sphinx-arguments must be empty when docs-build-command",
        ),
        (
            {"DOCS_TOOL": "mkdocs", "SPHINX_ARGUMENTS": "-W", "SPHINX_BUILDER": ""},
            "sphinx-arguments must be empty when docs-tool is mkdocs",
        ),
        (
            {"MKDOCS_ARGUMENTS": "--strict"},
            "mkdocs-arguments must be empty when docs-tool is sphinx",
        ),
        ({"SPHINX_BUILDER": ""}, "sphinx-builder must be non-empty"),
        (
            {"DOCS_TOOL": "mkdocs", "DOCS_LINKCHECK_ENABLED": "true", "SPHINX_BUILDER": ""},
            "docs-linkcheck-enabled requires docs-tool sphinx",
        ),
        (
            {"DOCS_ENVIRONMENT": "uv", "UV_CACHE_MODE": "sometimes", "PIP_INSTALL_TARGETS": ""},
            "uv-cache-mode must be one of",
        ),
        (
            {"DOCS_ENVIRONMENT": "pip", "PIP_INSTALL_TARGETS": "", "PIP_REQUIREMENTS_FILE": ""},
            "pip mode requires",
        ),
        (
            {
                "DOCS_ENVIRONMENT": "pixi",
                "PIXI_LOCKED": "true",
                "PIXI_FROZEN": "true",
                "PIP_INSTALL_TARGETS": "",
            },
            "mutually exclusive",
        ),
        (
            {
                "DOCS_ENVIRONMENT": "micromamba",
                "MICROMAMBA_ENVIRONMENT_FILE": "",
                "PIP_INSTALL_TARGETS": "",
            },
            "micromamba mode requires",
        ),
        (
            {"DOCS_ENVIRONMENT": "container", "CONTAINER_IMAGE": "", "PIP_INSTALL_TARGETS": ""},
            "container mode requires container-image",
        ),
        (
            {
                "DOCS_ENVIRONMENT": "container",
                "CONTAINER_IMAGE": "bad image!",
                "PIP_INSTALL_TARGETS": "",
            },
            "not a valid image reference",
        ),
        (
            {
                "DOCS_ENVIRONMENT": "container",
                "CONTAINER_IMAGE": "ghcr.io/org/d:1",
                "CONTAINER_LOGIN_ENABLED": "true",
                "CONTAINER_PASSWORD_SET": "false",
                "PIP_INSTALL_TARGETS": "",
            },
            "container-login-enabled requires the container-password secret",
        ),
    ],
)
def test_validate_rejects_bad_combinations(monkeypatch, tmp_path, overrides, message) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _validate_env(tmp_path, **overrides).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_container_login_ok_with_password(monkeypatch, tmp_path) -> None:
    _run_validate(
        monkeypatch,
        tmp_path,
        DOCS_ENVIRONMENT="container",
        CONTAINER_IMAGE="ghcr.io/org/docs:1",
        CONTAINER_LOGIN_ENABLED="true",
        CONTAINER_PASSWORD_SET="true",
        PIP_INSTALL_TARGETS="",
    )


def test_validate_ignores_non_selected_group_inputs(monkeypatch, tmp_path) -> None:
    # A bogus uv-cache-mode is ignored when not in uv mode (pip mode selected).
    _run_validate(monkeypatch, tmp_path, UV_CACHE_MODE="garbage")


# --------------------------------------------------------------------------- #
# install-environment.py                                                       #
# --------------------------------------------------------------------------- #
def _install_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    base = {
        "DOCS_ENVIRONMENT": "uv",
        "DOCS_WORKING_DIRECTORY": ".",
        "UV_SYNC_LOCKED": "true",
        "UV_SYNC_GROUPS": "",
        "UV_SYNC_EXTRAS": "",
        "UV_SYNC_ARGUMENTS": "",
        "PIP_REQUIREMENTS_FILE": "",
        "PIP_INSTALL_TARGETS": "",
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    base.update(overrides)
    return base


def _capture_install(monkeypatch, tmp_path: Path, **overrides: str) -> list[str]:
    module = _load_script("install-environment.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kw: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    for key, value in _install_env(tmp_path, **overrides).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    return calls[0]


def test_install_uv_sync_builds_argv(monkeypatch, tmp_path) -> None:
    command = _capture_install(
        monkeypatch,
        tmp_path,
        UV_SYNC_GROUPS="docs\ntest",
        UV_SYNC_EXTRAS="pdf",
        UV_SYNC_ARGUMENTS="--no-dev",
    )
    assert command[:2] == ["uv", "sync"]
    assert "--locked" in command
    assert command.count("--group") == 2
    assert "docs" in command and "test" in command
    assert "--extra" in command and "pdf" in command
    assert "--no-dev" in command


def test_install_uv_sync_unlocked_omits_locked(monkeypatch, tmp_path) -> None:
    command = _capture_install(monkeypatch, tmp_path, UV_SYNC_LOCKED="false")
    assert "--locked" not in command


def test_install_pip_builds_argv(monkeypatch, tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("sphinx\n", encoding="utf-8")
    command = _capture_install(
        monkeypatch,
        tmp_path,
        DOCS_ENVIRONMENT="pip",
        PIP_REQUIREMENTS_FILE="requirements.txt",
        PIP_INSTALL_TARGETS=".[docs]\nfuro",
    )
    assert command[1:4] == ["-m", "pip", "install"]
    assert "-r" in command
    assert str((tmp_path / "requirements.txt").resolve()) in command
    assert ".[docs]" in command and "furo" in command


def test_install_pip_requires_something(monkeypatch, tmp_path) -> None:
    module = _load_script("install-environment.py")
    for key, value in _install_env(tmp_path, DOCS_ENVIRONMENT="pip").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "pip mode requires" in str(excinfo.value)


def test_install_rejects_non_uv_pip_environment(monkeypatch, tmp_path) -> None:
    module = _load_script("install-environment.py")
    for key, value in _install_env(tmp_path, DOCS_ENVIRONMENT="container").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "only valid for uv/pip" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# run-docs-build.py                                                            #
# --------------------------------------------------------------------------- #
def test_docs_build_argv_sphinx() -> None:
    module = _load_script("run-docs-build.py")
    argv = module.docs_build_argv(
        tool="sphinx",
        builder="dirhtml",
        warnings_as_errors=True,
        sphinx_arguments=["-D", "language=en"],
        mkdocs_arguments=[],
        source_path="/src",
        output_path="/out",
        config_path="/cfg",
    )
    assert argv == [
        "sphinx-build",
        "-b",
        "dirhtml",
        "-W",
        "--keep-going",
        "-D",
        "language=en",
        "/src",
        "/out",
    ]


def test_docs_build_argv_mkdocs() -> None:
    module = _load_script("run-docs-build.py")
    argv = module.docs_build_argv(
        tool="mkdocs",
        builder="html",
        warnings_as_errors=True,
        sphinx_arguments=[],
        mkdocs_arguments=["--verbose"],
        source_path="/src",
        output_path="/out",
        config_path="/cfg",
    )
    assert argv == [
        "mkdocs",
        "build",
        "--config-file",
        "/cfg",
        "--site-dir",
        "/out",
        "--strict",
        "--verbose",
    ]


def test_linkcheck_argv() -> None:
    module = _load_script("run-docs-build.py")
    assert module.linkcheck_argv(
        sphinx_arguments=["-q"], source_path="/src", report_path="/rep"
    ) == ["sphinx-build", "-b", "linkcheck", "-q", "/src", "/rep"]


def test_render_path_host_and_container(tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    assert module.render_path(tmp_path, "docs", "pip") == str(tmp_path / "docs")
    assert module.render_path(tmp_path, "docs", "container") == "/data/docs"
    assert module.render_path(tmp_path, ".", "container") == "/data"


def test_render_path_rejects_escape(tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    with pytest.raises(SystemExit):
        module.render_path(tmp_path, "../escape", "pip")


@pytest.mark.parametrize(
    ("environment", "expected_prefix"),
    [
        ("pixi", ["pixi", "run", "--environment", "default", "--"]),
        ("uv", ["uv", "run", "--no-sync", "--"]),
        ("micromamba", ["micromamba", "run", "-n", "docs-build"]),
        ("pip", []),
    ],
)
def test_wrap_in_environment(tmp_path, environment, expected_prefix) -> None:
    module = _load_script("run-docs-build.py")
    inner = ["sphinx-build", "-b", "html", "/s", "/o"]
    command = module.wrap_in_environment(
        inner,
        environment=environment,
        workspace=tmp_path,
        container_workdir="/data",
        pixi_environment="default",
        pixi_manifest_path="",
        image="",
    )
    assert command == [*expected_prefix, *inner]


def test_wrap_pixi_with_manifest(tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    command = module.wrap_in_environment(
        ["mkdocs", "build"],
        environment="pixi",
        workspace=tmp_path,
        container_workdir="/data",
        pixi_environment="docs",
        pixi_manifest_path="pixi.toml",
        image="",
    )
    assert "--manifest-path" in command
    assert str((tmp_path / "pixi.toml").resolve()) in command
    assert command[-2:] == ["mkdocs", "build"]


def test_wrap_container(tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    command = module.wrap_in_environment(
        ["sphinx-build", "-b", "html", "/data/docs", "/data/_site"],
        environment="container",
        workspace=tmp_path,
        container_workdir="/data/docs",
        pixi_environment="default",
        pixi_manifest_path="",
        image="sphinxdoc/sphinx:8.1.3",
    )
    assert command[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path}:/data" in command
    assert "--workdir" in command and "/data/docs" in command
    assert "sphinxdoc/sphinx:8.1.3" in command
    assert command[-4:] == ["-b", "html", "/data/docs", "/data/_site"]


def _run_docs_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    base = {
        "DOCS_BUILD_MODE": "build",
        "DOCS_TOOL": "sphinx",
        "DOCS_ENVIRONMENT": "pip",
        "DOCS_BUILD_COMMAND": "",
        "DOCS_WORKING_DIRECTORY": ".",
        "DOCS_OUTPUT_DIRECTORY": "_site",
        "DOCS_WARNINGS_AS_ERRORS": "false",
        "SPHINX_SOURCE_DIRECTORY": "docs",
        "SPHINX_BUILDER": "html",
        "SPHINX_ARGUMENTS": "",
        "MKDOCS_CONFIG_FILE": "mkdocs.yml",
        "MKDOCS_ARGUMENTS": "",
        "PIXI_ENVIRONMENT": "default",
        "PIXI_MANIFEST_PATH": "",
        "CONTAINER_IMAGE": "",
        "GITHUB_WORKSPACE": str(tmp_path),
    }
    base.update(overrides)
    return base


def test_main_build_runs_and_checks_output(monkeypatch, tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    output_dir = tmp_path / "_site"

    def fake_run(command, **kw):
        # Simulate the tool writing the site.
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    for key, value in _run_docs_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0


def test_main_build_fails_on_empty_output(monkeypatch, tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 0),
    )
    for key, value in _run_docs_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "was not created" in str(excinfo.value)


def test_main_trusted_command_used(monkeypatch, tmp_path) -> None:
    module = _load_script("run-docs-build.py")
    captured: list[list[str]] = []
    output_dir = tmp_path / "_site"

    def fake_run(command, **kw):
        captured.append(command)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("x", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    for key, value in _run_docs_env(tmp_path, DOCS_BUILD_COMMAND="make docs").items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    # The trusted command is executed via bash -c, not the generated sphinx argv.
    assert "bash" in captured[0]
    assert "make docs" in captured[0]
    assert "sphinx-build" not in captured[0]


# --------------------------------------------------------------------------- #
# Generated interface (post-conventions)                                       #
# --------------------------------------------------------------------------- #
def _docs_build_call() -> dict:
    for item in load_catalog():
        if item.id == "docs-build":
            return published_workflow_call(item)
    raise AssertionError("docs-build workflow not found in catalog")


def test_interface_applies_convention_renames() -> None:
    call = _docs_build_call()
    inputs = call["inputs"]
    # uv-cache-enabled -> uv-cache-mode
    assert "uv-cache-mode" in inputs and "uv-cache-enabled" not in inputs
    # bare python-version -> pip-python-version
    assert "pip-python-version" in inputs and "python-version" not in inputs
    # container-registry-username -> container-username; default is repository owner
    assert "container-username" in inputs and "container-registry-username" not in inputs
    assert inputs["container-username"]["default"] == "${{ github.repository_owner }}"
    # uv-cache-mode is a string enum defaulting to auto
    assert inputs["uv-cache-mode"]["type"] == "string"
    assert inputs["uv-cache-mode"]["default"] == "auto"


def test_interface_adds_micromamba_group() -> None:
    inputs = _docs_build_call()["inputs"]
    assert {
        "micromamba-environment-file",
        "micromamba-version",
        "micromamba-cache-enabled",
    } <= set(inputs)


def test_interface_has_no_writeback_channel() -> None:
    call = _docs_build_call()
    inputs = call["inputs"]
    # Writeback is deliberately OFF: no commit-* inputs, no contents:write tax.
    assert not any(key.startswith("commit-") for key in inputs)
    # But the read-only channels are present.
    assert "checkout-enabled" in inputs
    assert "artifact-upload-enabled" in inputs
    assert "artifact-download-enabled" in inputs


def test_interface_secret_and_outputs() -> None:
    call = _docs_build_call()
    assert "container-password" in call["secrets"]
    assert "container-registry-password" not in call["secrets"]
    assert set(call["outputs"]) == {
        "pages-artifact-name",
        "pages-artifact-id",
        "docs-output-directory",
        "docs-linkcheck-report-directory",
    }


def test_interface_environment_required() -> None:
    inputs = _docs_build_call()["inputs"]
    assert inputs["docs-environment"]["required"] is True
    assert inputs["pages-artifact-name"]["default"] == "github-pages"
