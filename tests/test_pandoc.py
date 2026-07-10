from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

RUN_PANDOC = Path("workflows/pandoc/scripts/run-pandoc.py")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_pandoc", RUN_PANDOC)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_env(monkeypatch, tmp_path: Path, *, image: str, arguments: str) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PANDOC_IMAGE", image)
    monkeypatch.setenv("PANDOC_ARGUMENTS", arguments)
    monkeypatch.setenv("PANDOC_WORKING_DIRECTORY", ".")


@pytest.mark.parametrize(
    "image",
    [
        "pandoc/latex:3-ubuntu",
        "pandoc/core",
        "docker.io/pandoc/core",
        "ghcr.io/org/pandoc-filter:1.2.3",
        "myregistry.com:5000/team/pandoc-extra",
        "quay.io/user/pandoc@sha256:" + "a" * 64,
    ],
)
def test_valid_image_references_are_accepted(monkeypatch, tmp_path, image) -> None:
    module = _load_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, check: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    _set_env(monkeypatch, tmp_path, image=image, arguments="--version")

    assert module.main() == 0
    # The image is passed as the trailing positional argument before pandoc args.
    assert image in calls[0]
    assert calls[0].index(image) < calls[0].index("--version")


@pytest.mark.parametrize(
    "image",
    [
        "",
        "   ",
        "-rm",
        "pandoc/latex:",
        "pandoc//core",
        "/pandoc/core",
        "pandoc/core:bad tag",
        "pandoc/core@sha256:short",
    ],
)
def test_malformed_image_references_are_rejected(monkeypatch, tmp_path, image) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: pytest.fail("docker must not run for a malformed image"),
    )
    _set_env(monkeypatch, tmp_path, image=image, arguments="--version")

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "not a valid image reference" in str(excinfo.value)


def test_empty_arguments_are_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: pytest.fail("docker must not run when arguments are empty"),
    )
    _set_env(monkeypatch, tmp_path, image="pandoc/core", arguments="   ")

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "must not be empty" in str(excinfo.value)


def test_working_directory_outside_workspace_is_rejected(monkeypatch, tmp_path) -> None:
    module = _load_module()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PANDOC_IMAGE", "pandoc/core")
    monkeypatch.setenv("PANDOC_ARGUMENTS", "--version")
    monkeypatch.setenv("PANDOC_WORKING_DIRECTORY", "../escape")

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "GITHUB_WORKSPACE" in str(excinfo.value)


def test_command_mounts_workspace_and_sets_workdir(monkeypatch, tmp_path) -> None:
    module = _load_module()
    subdir = tmp_path / "docs"
    subdir.mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, check: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PANDOC_IMAGE", "pandoc/core")
    monkeypatch.setenv("PANDOC_ARGUMENTS", "--standalone --output=out.html in.md")
    monkeypatch.setenv("PANDOC_WORKING_DIRECTORY", "docs")

    assert module.main() == 0
    command = calls[0]
    assert command[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path.resolve()}:/data" in command
    assert "/data/docs" in command
    assert command[-3:] == ["--standalone", "--output=out.html", "in.md"]
