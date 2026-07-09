from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType


def test_resolve_build_settings_writes_defaults(monkeypatch, tmp_path) -> None:
    module = _load_script("resolve-build-settings.py")
    output = tmp_path / "github-output"
    monkeypatch.setenv("CACHE_DEPENDENCY_HASH", "abc123")
    monkeypatch.setenv("CACHE_KEY", "")
    monkeypatch.setenv("CACHE_KEY_PREFIX", "devcontainer")
    monkeypatch.setenv("CACHE_PATH", "")
    monkeypatch.setenv("CACHE_RESTORE_KEYS", "")
    monkeypatch.setenv("DEVCONTAINER_CACHE_FROM", "")
    monkeypatch.setenv("DEVCONTAINER_CACHE_TO", "")
    monkeypatch.setenv("DEVCONTAINER_USER_DATA_FOLDER", "/tmp/devcontainer-userdata")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("MATRIX_PLATFORM_TAG", "linux-amd64")

    assert module.main() == 0

    rendered = output.read_text(encoding="utf-8")
    assert "cache-path=/tmp/devcontainer-userdata\n" in rendered
    assert "cache-key=devcontainer-linux-amd64-abc123\n" in rendered
    assert "cache-restore-keys=devcontainer-linux-amd64-\n" in rendered
    assert "cache-from=ghcr.io/example/project-devcontainer:devcontainer-linux-amd64\n" in rendered
    assert (
        "cache-to=type=registry,ref=ghcr.io/example/project-devcontainer:"
        "devcontainer-linux-amd64,mode=max\n"
    ) in rendered


def test_merge_manifest_creates_base_and_sha_tags(monkeypatch, tmp_path) -> None:
    module = _load_script("merge-manifest.py")
    output = tmp_path / "github-output"
    calls: list[list[str]] = []

    def fake_run(command, *, check):
        calls.append(command)
        assert check is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv(
        "BUILD_MATRIX",
        """[
          {"runner": "ubuntu-latest", "platform": "linux/amd64", "platform_tag": "linux-amd64"},
          {"runner": "ubuntu-24.04-arm", "platform": "linux/arm64", "platform_tag": "linux-arm64"}
        ]""",
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_SHA_TAG_ENABLED", "true")
    monkeypatch.setenv("IMAGE_SHA_TAG_PREFIX", "sha-")
    monkeypatch.setenv("IMAGE_TAG", "latest")
    monkeypatch.setenv("SOURCE_SHA", "0123456789abcdef")

    assert module.main() == 0

    assert calls == [
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "-t",
            "ghcr.io/example/project-devcontainer:latest",
            "ghcr.io/example/project-devcontainer:latest-linux-amd64",
            "ghcr.io/example/project-devcontainer:latest-linux-arm64",
        ],
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "-t",
            "ghcr.io/example/project-devcontainer:sha-0123456789abcdef",
            "ghcr.io/example/project-devcontainer:latest-linux-amd64",
            "ghcr.io/example/project-devcontainer:latest-linux-arm64",
        ],
    ]
    rendered = output.read_text(encoding="utf-8")
    assert "image-ref=ghcr.io/example/project-devcontainer:latest\n" in rendered
    assert "sha-image-ref=ghcr.io/example/project-devcontainer:sha-0123456789abcdef\n" in rendered


def _load_script(name: str) -> ModuleType:
    path = Path("workflows/build-devcontainer/scripts") / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
