from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

RESOLVE_BASE_ENV = {
    "CACHE_DEPENDENCY_HASH": "abc123",
    "CACHE_KEY": "",
    "CACHE_KEY_PREFIX": "devcontainer",
    "CACHE_PATH": "",
    "CACHE_RESTORE_KEYS": "",
    "DEVCONTAINER_CACHE_FROM": "",
    "DEVCONTAINER_CACHE_TO": "",
    "DEVCONTAINER_CACHE_REGISTRY_ENABLED": "true",
    "DEVCONTAINER_PUSH": "always",
    "DEVCONTAINER_USER_DATA_FOLDER": "/tmp/devcontainer-userdata",
    "IMAGE_NAME": "ghcr.io/example/project-devcontainer",
    "MATRIX_PLATFORM_TAG": "linux-amd64",
}


# --------------------------------------------------------------------------- #
# resolve-build-settings.py                                                    #
# --------------------------------------------------------------------------- #
def _run_resolve(monkeypatch, tmp_path, **overrides) -> dict[str, str]:
    module = _load_script("resolve-build-settings.py")
    output = tmp_path / "github-output"
    env = {**RESOLVE_BASE_ENV, "GITHUB_OUTPUT": str(output), **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    return _parse_output(output)


def test_resolve_build_settings_writes_defaults(monkeypatch, tmp_path) -> None:
    parsed = _run_resolve(monkeypatch, tmp_path)
    assert parsed["cache-path"] == "/tmp/devcontainer-userdata"
    assert parsed["cache-key"] == "devcontainer-linux-amd64-abc123"
    assert parsed["cache-restore-keys"] == "devcontainer-linux-amd64-"
    assert parsed["cache-from"] == "ghcr.io/example/project-devcontainer:devcontainer-linux-amd64"
    assert parsed["cache-to"] == (
        "type=registry,ref=ghcr.io/example/project-devcontainer:devcontainer-linux-amd64,mode=max"
    )


def test_resolve_registry_cache_disabled_clears_both(monkeypatch, tmp_path) -> None:
    parsed = _run_resolve(monkeypatch, tmp_path, DEVCONTAINER_CACHE_REGISTRY_ENABLED="false")
    assert parsed["cache-from"] == ""
    assert parsed["cache-to"] == ""


def test_resolve_cache_none_sentinel_disables_registry_cache(monkeypatch, tmp_path) -> None:
    parsed = _run_resolve(
        monkeypatch,
        tmp_path,
        DEVCONTAINER_CACHE_FROM="none",
        DEVCONTAINER_CACHE_TO="none",
    )
    assert parsed["cache-from"] == ""
    assert parsed["cache-to"] == ""


def test_resolve_cache_to_disabled_when_push_never(monkeypatch, tmp_path) -> None:
    parsed = _run_resolve(monkeypatch, tmp_path, DEVCONTAINER_PUSH="never")
    # cache-from (a read) is still allowed to speed up build-only validation...
    assert parsed["cache-from"] == "ghcr.io/example/project-devcontainer:devcontainer-linux-amd64"
    # ...but cache-to (a push) is auto-disabled so no push rights are needed.
    assert parsed["cache-to"] == ""


def test_resolve_explicit_cache_values_are_passed_through(monkeypatch, tmp_path) -> None:
    parsed = _run_resolve(
        monkeypatch,
        tmp_path,
        DEVCONTAINER_CACHE_FROM="type=gha",
        DEVCONTAINER_CACHE_TO="type=gha,mode=max",
    )
    assert parsed["cache-from"] == "type=gha"
    assert parsed["cache-to"] == "type=gha,mode=max"


def test_resolve_rejects_newline_in_output_value(monkeypatch, tmp_path) -> None:
    module = _load_script("resolve-build-settings.py")
    output = tmp_path / "github-output"
    env = {
        **RESOLVE_BASE_ENV,
        "GITHUB_OUTPUT": str(output),
        # A caller-controlled cache path carrying a newline must not be able to
        # forge additional step outputs.
        "CACHE_PATH": "/tmp/data\ncache-to=type=registry,ref=evil,mode=max",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "newline" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                           #
# --------------------------------------------------------------------------- #
_VALID_MATRIX = json.dumps(
    [
        {"runner": "ubuntu-latest", "platform": "linux/amd64", "platform_tag": "linux-amd64"},
        {"runner": "ubuntu-24.04-arm", "platform": "linux/arm64", "platform_tag": "linux-arm64"},
    ]
)


def _run_validate(monkeypatch, **env) -> None:
    module = _load_script("validate-inputs.py")
    base = {
        "BUILD_MATRIX": _VALID_MATRIX,
        "DOCKER_LOGIN_ENABLED": "false",
        "DOCKER_PASSWORD_SET": "false",
        "DOCKER_REGISTRY": "ghcr.io",
    }
    for key, value in {**base, **env}.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0


def test_validate_accepts_well_formed_matrix(monkeypatch) -> None:
    _run_validate(monkeypatch)


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        ("[]", "nonempty"),
        ('{"platform_tag": "x"}', "nonempty"),
        ('["not-an-object"]', "must be an object"),
        ('[{"runner": "r", "platform": "linux/amd64"}]', "platform_tag is required"),
        ('[{"runner": "r", "platform_tag": "t"}]', "platform is required"),
        (
            '[{"runner": "r", "platform": "p", "platform_tag": "t"},'
            ' {"runner": "r2", "platform": "p2", "platform_tag": "t"}]',
            "duplicate platform_tag",
        ),
    ],
)
def test_validate_rejects_bad_matrix(monkeypatch, matrix, message) -> None:
    module = _load_script("validate-inputs.py")
    monkeypatch.setenv("BUILD_MATRIX", matrix)
    monkeypatch.setenv("DOCKER_LOGIN_ENABLED", "false")
    monkeypatch.setenv("DOCKER_PASSWORD_SET", "false")
    monkeypatch.setenv("DOCKER_REGISTRY", "ghcr.io")
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_allows_ghcr_token_fallback(monkeypatch) -> None:
    _run_validate(monkeypatch, DOCKER_LOGIN_ENABLED="true", DOCKER_REGISTRY="ghcr.io")


def test_validate_allows_other_registry_with_password(monkeypatch) -> None:
    _run_validate(
        monkeypatch,
        DOCKER_LOGIN_ENABLED="true",
        DOCKER_REGISTRY="docker.io",
        DOCKER_PASSWORD_SET="true",
    )


def test_validate_allows_login_disabled(monkeypatch) -> None:
    _run_validate(monkeypatch, DOCKER_LOGIN_ENABLED="false", DOCKER_REGISTRY="docker.io")


@pytest.mark.parametrize("registry", ["docker.io", "", "myregistry.example.com"])
def test_validate_rejects_token_fallback_to_non_ghcr(monkeypatch, registry) -> None:
    module = _load_script("validate-inputs.py")
    monkeypatch.setenv("BUILD_MATRIX", _VALID_MATRIX)
    monkeypatch.setenv("DOCKER_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DOCKER_PASSWORD_SET", "false")
    monkeypatch.setenv("DOCKER_REGISTRY", registry)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "restricted to ghcr.io" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# capture-digest.py                                                            #
# --------------------------------------------------------------------------- #
def test_capture_digest_parses_and_writes(monkeypatch, tmp_path) -> None:
    module = _load_script("capture-digest.py")
    digest = "sha256:" + "a" * 64

    def fake_run(command, *, check, capture_output, text):
        assert command[:4] == ["docker", "buildx", "imagetools", "inspect"]
        assert "ghcr.io/example/project-devcontainer:latest-linux-amd64" in command
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"digest": digest}))

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_TAG", "latest")
    monkeypatch.setenv("MATRIX_PLATFORM_TAG", "linux-amd64")
    monkeypatch.setenv("DIGEST_DIR", str(tmp_path / "digests"))

    assert module.main() == 0
    assert (tmp_path / "digests/linux-amd64").read_text(encoding="utf-8").strip() == digest


def test_capture_digest_rejects_non_sha256(monkeypatch, tmp_path) -> None:
    module = _load_script("capture-digest.py")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout=json.dumps({"digest": "deadbeef"})
        ),
    )
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_TAG", "latest")
    monkeypatch.setenv("MATRIX_PLATFORM_TAG", "linux-amd64")
    monkeypatch.setenv("DIGEST_DIR", str(tmp_path / "digests"))

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "unexpected manifest digest" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# merge-manifest.py                                                            #
# --------------------------------------------------------------------------- #
def _write_digests(digest_dir: Path, mapping: dict[str, str]) -> None:
    digest_dir.mkdir(parents=True, exist_ok=True)
    for platform_tag, digest in mapping.items():
        (digest_dir / platform_tag).write_text(digest + "\n", encoding="utf-8")


def test_merge_manifest_merges_by_digest(monkeypatch, tmp_path) -> None:
    module = _load_script("merge-manifest.py")
    output = tmp_path / "github-output"
    digest_dir = tmp_path / "digests"
    amd = "sha256:" + "1" * 64
    arm = "sha256:" + "2" * 64
    _write_digests(digest_dir, {"linux-amd64": amd, "linux-arm64": arm})

    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, check: calls.append(command) or subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setenv("BUILD_MATRIX", _VALID_MATRIX)
    monkeypatch.setenv("DIGEST_DIR", str(digest_dir))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_SHA_TAG_ENABLED", "true")
    monkeypatch.setenv("IMAGE_SHA_TAG_PREFIX", "sha-")
    monkeypatch.setenv("IMAGE_TAG", "latest")
    monkeypatch.setenv("SOURCE_SHA", "0123456789abcdef")

    assert module.main() == 0

    image = "ghcr.io/example/project-devcontainer"
    assert calls == [
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "-t",
            f"{image}:latest",
            f"{image}@{amd}",
            f"{image}@{arm}",
        ],
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "-t",
            f"{image}:sha-0123456789abcdef",
            f"{image}@{amd}",
            f"{image}@{arm}",
        ],
    ]
    parsed = _parse_output(output)
    assert parsed["image-ref"] == f"{image}:latest"
    assert parsed["sha-image-ref"] == f"{image}:sha-0123456789abcdef"


def test_merge_manifest_errors_on_missing_digest(monkeypatch, tmp_path) -> None:
    module = _load_script("merge-manifest.py")
    digest_dir = tmp_path / "digests"
    # Only one of the two expected platform digests is present.
    _write_digests(digest_dir, {"linux-amd64": "sha256:" + "1" * 64})

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: pytest.fail("imagetools must not run with an incomplete manifest"),
    )
    monkeypatch.setenv("BUILD_MATRIX", _VALID_MATRIX)
    monkeypatch.setenv("DIGEST_DIR", str(digest_dir))
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_TAG", "latest")

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "missing digest for platform 'linux-arm64'" in str(excinfo.value)


def test_merge_manifest_errors_on_invalid_digest(monkeypatch, tmp_path) -> None:
    module = _load_script("merge-manifest.py")
    digest_dir = tmp_path / "digests"
    _write_digests(digest_dir, {"linux-amd64": "not-a-digest", "linux-arm64": "sha256:" + "2" * 64})

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: pytest.fail("imagetools must not run with an invalid digest"),
    )
    monkeypatch.setenv("BUILD_MATRIX", _VALID_MATRIX)
    monkeypatch.setenv("DIGEST_DIR", str(digest_dir))
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/example/project-devcontainer")
    monkeypatch.setenv("IMAGE_TAG", "latest")

    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "invalid digest" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _parse_output(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        parsed[key] = value
    return parsed


def _load_script(name: str) -> ModuleType:
    path = Path("workflows/build-devcontainer/scripts") / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
