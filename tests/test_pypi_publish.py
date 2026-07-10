from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from devflows.actions import PINS_BY_REF
from devflows.catalog import load_catalog
from devflows.publish import build_published_workflow, caller_required_permissions

SCRIPTS = Path("workflows/pypi-publish/scripts")
GH_ACTION_PYPI_PUBLISH = "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b"

# Every env key any of the three scripts reads, cleared before each case so a
# leaked value from a prior test cannot mask a missing-input bug.
_ENV_KEYS = (
    "PUBLISH_INDEX",
    "PUBLISH_DIST_MANIFEST",
    "PUBLISH_DIST_PATH",
    "PUBLISH_EXPECTED_VERSION",
    "PUBLISH_ENVIRONMENT_NAME",
    "PUBLISH_DRY_RUN_ENABLED",
    "INSTALL_CHECK_ENABLED",
    "INSTALL_CHECK_ARGUMENTS",
    "INSTALL_CHECK_IMPORT_NAMES",
    "INSTALL_CHECK_TIMEOUT_MINUTES",
    "ARTIFACT_DOWNLOAD_ENABLED",
    "DEVFLOWS_STAGE_DIR",
    "PACKAGE_NAME",
    "PACKAGE_VERSION",
    "GITHUB_WORKSPACE",
    "GITHUB_OUTPUT",
    "GITHUB_STEP_SUMMARY",
    "RUNNER_TEMP",
)


def _load(script: str) -> ModuleType:
    path = SCRIPTS / script
    name = f"pypi_publish_{script.replace('-', '_').removesuffix('.py')}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: verify-dist.py defines a dataclass, and dataclasses
    # resolves field annotations via sys.modules[cls.__module__] at class creation.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _set(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return _set


def _read_outputs(path: Path) -> dict[str, str]:
    """Parse a GITHUB_OUTPUT file supporting both key=value and heredoc entries."""
    result: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, delimiter = line.split("<<", 1)
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index] != delimiter:
                body.append(lines[index])
                index += 1
            result[name] = "\n".join(body)
            index += 1
        elif "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
            index += 1
        else:
            index += 1
    return result


# --------------------------------------------------------------------------- #
# validate-inputs.py
# --------------------------------------------------------------------------- #

VALIDATE = "validate-inputs.py"
_VALID_MANIFEST = (
    '{"schema":1,"files":[{"name":"pkg-1.0.tar.gz","sha256":'
    '"0000000000000000000000000000000000000000000000000000000000000000",'
    '"size":1,"kind":"sdist"}],"artifacts":{"sdist":"pkg-sdist","wheels":"",'
    '"conda-channel":""}}'
)


def _valid_validate_env() -> dict[str, str]:
    return {
        "PUBLISH_INDEX": "pypi",
        "PUBLISH_DIST_MANIFEST": _VALID_MANIFEST,
        "PUBLISH_DIST_PATH": "dist",
        "PUBLISH_ENVIRONMENT_NAME": "pypi",
        "PUBLISH_DRY_RUN_ENABLED": "false",
        "INSTALL_CHECK_ENABLED": "false",
        "INSTALL_CHECK_ARGUMENTS": "",
        "ARTIFACT_DOWNLOAD_ENABLED": "true",
    }


def _expect_validate_failure(env, message: str, **overrides: str) -> None:
    module = _load(VALIDATE)
    values = _valid_validate_env()
    values.update(overrides)
    env(**values)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_validate_accepts_valid_inputs_and_emits_repository_url(env, tmp_path) -> None:
    module = _load(VALIDATE)
    output = tmp_path / "out.txt"
    env(**_valid_validate_env(), GITHUB_OUTPUT=str(output))
    assert module.main() == 0
    assert _read_outputs(output)["repository-url"] == "https://upload.pypi.org/legacy/"


def test_validate_testpypi_repository_url(env, tmp_path) -> None:
    module = _load(VALIDATE)
    output = tmp_path / "out.txt"
    env(**{**_valid_validate_env(), "PUBLISH_INDEX": "testpypi"}, GITHUB_OUTPUT=str(output))
    assert module.main() == 0
    assert _read_outputs(output)["repository-url"] == "https://test.pypi.org/legacy/"


def test_validate_rejects_url_index(env) -> None:
    _expect_validate_failure(
        env,
        "publish-index must be 'pypi' or 'testpypi'",
        PUBLISH_INDEX="https://my-devpi.example/simple",
    )


def test_validate_rejects_empty_manifest(env) -> None:
    _expect_validate_failure(env, "publish-dist-manifest is required", PUBLISH_DIST_MANIFEST="")


def test_validate_rejects_malformed_manifest(env) -> None:
    _expect_validate_failure(
        env, "publish-dist-manifest is not valid JSON", PUBLISH_DIST_MANIFEST="{not json"
    )


def test_validate_rejects_non_object_manifest(env) -> None:
    _expect_validate_failure(
        env, "publish-dist-manifest must be a JSON object", PUBLISH_DIST_MANIFEST="[1, 2, 3]"
    )


def test_validate_rejects_unsupported_schema(env) -> None:
    _expect_validate_failure(
        env,
        "unsupported dist-manifest schema",
        PUBLISH_DIST_MANIFEST='{"schema":2,"files":[],"artifacts":{}}',
    )


def test_validate_rejects_non_list_files(env) -> None:
    _expect_validate_failure(
        env,
        "'files' must be a list",
        PUBLISH_DIST_MANIFEST='{"schema":1,"files":{},"artifacts":{}}',
    )


def test_validate_rejects_nothing_to_publish(env) -> None:
    manifest = (
        '{"schema":1,"files":[{"name":"pkg-1.0-h0.conda","sha256":"x","size":1,'
        '"kind":"conda"}],"artifacts":{"sdist":"","wheels":"","conda-channel":"c"}}'
    )
    _expect_validate_failure(
        env, "contains no sdist or wheel distributions", PUBLISH_DIST_MANIFEST=manifest
    )


def test_validate_rejects_empty_dist_path(env) -> None:
    _expect_validate_failure(env, "publish-dist-path is required", PUBLISH_DIST_PATH="")


def test_validate_rejects_absolute_dist_path(env) -> None:
    _expect_validate_failure(
        env, "publish-dist-path must be a workspace-relative path", PUBLISH_DIST_PATH="/etc"
    )


def test_validate_rejects_traversal_dist_path(env) -> None:
    _expect_validate_failure(
        env, "publish-dist-path must be a workspace-relative path", PUBLISH_DIST_PATH="../outside"
    )


def test_validate_rejects_empty_environment_name(env) -> None:
    _expect_validate_failure(
        env, "publish-environment-name must not be empty", PUBLISH_ENVIRONMENT_NAME=""
    )


def test_validate_rejects_disabled_channel(env) -> None:
    _expect_validate_failure(
        env,
        "distributions can only arrive through the artifact-download channel",
        ARTIFACT_DOWNLOAD_ENABLED="false",
    )


def test_validate_rejects_install_check_in_dry_run(env) -> None:
    _expect_validate_failure(
        env,
        "install-check-enabled requires a real publish",
        PUBLISH_DRY_RUN_ENABLED="true",
        INSTALL_CHECK_ENABLED="true",
    )


@pytest.mark.parametrize(
    "argument",
    ["-i", "--index-url https://x/simple", "--extra-index-url https://x/simple", "-ihttps://x"],
)
def test_validate_rejects_index_flags(env, argument: str) -> None:
    _expect_validate_failure(
        env,
        "install-check-arguments must not select a package index",
        INSTALL_CHECK_ARGUMENTS=argument,
    )


def test_validate_accepts_benign_install_arguments(env) -> None:
    module = _load(VALIDATE)
    env(**{**_valid_validate_env(), "INSTALL_CHECK_ARGUMENTS": "--no-binary :all:"})
    assert module.main() == 0


def test_validate_rejects_unparseable_install_arguments(env) -> None:
    _expect_validate_failure(
        env,
        "install-check-arguments is not valid shell syntax",
        INSTALL_CHECK_ARGUMENTS="'unbalanced",
    )


# --------------------------------------------------------------------------- #
# verify-dist.py
# --------------------------------------------------------------------------- #

VERIFY = "verify-dist.py"


def _digest(data: bytes) -> tuple[str, int]:
    return hashlib.sha256(data).hexdigest(), len(data)


def _manifest(entries: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "schema": 1,
            "files": entries,
            "artifacts": {"sdist": "", "wheels": "", "conda-channel": ""},
        }
    )


def _entry(name: str, data: bytes, kind: str) -> dict[str, Any]:
    sha, size = _digest(data)
    return {"name": name, "sha256": sha, "size": size, "kind": kind}


def _run_verify(
    env,
    tmp_path: Path,
    *,
    disk: dict[str, bytes],
    entries: list[dict[str, Any]],
    index: str = "pypi",
    expected_version: str = "",
) -> dict[str, str]:
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, data in disk.items():
        (dist / name).write_bytes(data)
    output = tmp_path / "out.txt"
    env(
        PUBLISH_DIST_MANIFEST=_manifest(entries),
        PUBLISH_DIST_PATH="dist",
        PUBLISH_INDEX=index,
        PUBLISH_EXPECTED_VERSION=expected_version,
        DEVFLOWS_STAGE_DIR="stage",
        GITHUB_WORKSPACE=str(tmp_path),
        GITHUB_OUTPUT=str(output),
    )
    module = _load(VERIFY)
    assert module.main() == 0
    return _read_outputs(output)


SDIST = "devflows_pypi_fixture-0.1.0.tar.gz"
WHEEL = "devflows_pypi_fixture-0.1.0-py3-none-any.whl"
SDIST_BYTES = b"sdist-bytes"
WHEEL_BYTES = b"wheel-bytes-longer"


def test_verify_success_stages_and_outputs(env, tmp_path) -> None:
    outputs = _run_verify(
        env,
        tmp_path,
        disk={SDIST: SDIST_BYTES, WHEEL: WHEEL_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist"), _entry(WHEEL, WHEEL_BYTES, "wheel")],
    )
    assert outputs["package-name"] == "devflows-pypi-fixture"
    assert outputs["package-version"] == "0.1.0"
    assert outputs["release-url"] == "https://pypi.org/project/devflows-pypi-fixture/0.1.0/"
    staged = tmp_path / "stage"
    assert {p.name for p in staged.iterdir()} == {SDIST, WHEEL}


def test_verify_testpypi_release_url(env, tmp_path) -> None:
    outputs = _run_verify(
        env,
        tmp_path,
        disk={SDIST: SDIST_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist")],
        index="testpypi",
    )
    assert outputs["release-url"] == "https://test.pypi.org/project/devflows-pypi-fixture/0.1.0/"


def test_verify_normalizes_package_name(env, tmp_path) -> None:
    name = "My.Weird_Name-1.2.3.tar.gz"
    data = b"x"
    outputs = _run_verify(env, tmp_path, disk={name: data}, entries=[_entry(name, data, "sdist")])
    assert outputs["package-name"] == "my-weird-name"
    assert outputs["package-version"] == "1.2.3"


def _expect_verify_failure(
    env, tmp_path, message: str, *, disk, entries, expected_version="", index="pypi"
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    for name, data in disk.items():
        (dist / name).write_bytes(data)
    env(
        PUBLISH_DIST_MANIFEST=_manifest(entries),
        PUBLISH_DIST_PATH="dist",
        PUBLISH_INDEX=index,
        PUBLISH_EXPECTED_VERSION=expected_version,
        DEVFLOWS_STAGE_DIR="stage",
        GITHUB_WORKSPACE=str(tmp_path),
    )
    module = _load(VERIFY)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert message in str(excinfo.value)


def test_verify_rejects_sha256_mismatch(env, tmp_path) -> None:
    entry = _entry(SDIST, SDIST_BYTES, "sdist")
    entry["sha256"] = "1" * 64
    _expect_verify_failure(
        env, tmp_path, "sha256 mismatch", disk={SDIST: SDIST_BYTES}, entries=[entry]
    )


def test_verify_rejects_size_mismatch(env, tmp_path) -> None:
    entry = _entry(SDIST, SDIST_BYTES, "sdist")
    entry["size"] = 999
    entry["sha256"] = hashlib.sha256(b"x" * 999).hexdigest()
    _expect_verify_failure(
        env, tmp_path, "size mismatch", disk={SDIST: SDIST_BYTES}, entries=[entry]
    )


def test_verify_rejects_unlisted_file(env, tmp_path) -> None:
    _expect_verify_failure(
        env,
        tmp_path,
        "not a distribution listed in the manifest",
        disk={SDIST: SDIST_BYTES, "stray-1.0.tar.gz": b"stray"},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist")],
    )


def test_verify_rejects_missing_file(env, tmp_path) -> None:
    _expect_verify_failure(
        env,
        tmp_path,
        "missing from",
        disk={SDIST: SDIST_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist"), _entry(WHEEL, WHEEL_BYTES, "wheel")],
    )


def test_verify_rejects_conda_kind_file_on_disk(env, tmp_path) -> None:
    conda_name = "devflows_pypi_fixture-0.1.0-h0.conda"
    conda_bytes = b"conda"
    _expect_verify_failure(
        env,
        tmp_path,
        "conda-kind file",
        disk={SDIST: SDIST_BYTES, conda_name: conda_bytes},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist"), _entry(conda_name, conda_bytes, "conda")],
    )


def test_verify_rejects_mixed_versions(env, tmp_path) -> None:
    other = "devflows_pypi_fixture-0.2.0-py3-none-any.whl"
    _expect_verify_failure(
        env,
        tmp_path,
        "disagree on version",
        disk={SDIST: SDIST_BYTES, other: WHEEL_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist"), _entry(other, WHEEL_BYTES, "wheel")],
    )


def test_verify_rejects_mixed_names(env, tmp_path) -> None:
    other = "another_pkg-0.1.0-py3-none-any.whl"
    _expect_verify_failure(
        env,
        tmp_path,
        "disagree on package name",
        disk={SDIST: SDIST_BYTES, other: WHEEL_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist"), _entry(other, WHEEL_BYTES, "wheel")],
    )


def test_verify_rejects_expected_version_skew(env, tmp_path) -> None:
    _expect_verify_failure(
        env,
        tmp_path,
        "does not match the distribution version",
        disk={SDIST: SDIST_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist")],
        expected_version="9.9.9",
    )


def test_verify_accepts_matching_expected_version(env, tmp_path) -> None:
    outputs = _run_verify(
        env,
        tmp_path,
        disk={SDIST: SDIST_BYTES},
        entries=[_entry(SDIST, SDIST_BYTES, "sdist")],
        expected_version="0.1.0",
    )
    assert outputs["package-version"] == "0.1.0"


def test_verify_rejects_only_conda_manifest(env, tmp_path) -> None:
    conda_name = "pkg-1.0-h0.conda"
    _expect_verify_failure(
        env,
        tmp_path,
        "lists no sdist or wheel",
        disk={},
        entries=[_entry(conda_name, b"c", "conda")],
    )


def test_verify_rejects_invalid_manifest_sha256(env, tmp_path) -> None:
    _expect_verify_failure(
        env,
        tmp_path,
        "invalid sha256",
        disk={SDIST: SDIST_BYTES},
        entries=[{"name": SDIST, "sha256": "nothex", "size": len(SDIST_BYTES), "kind": "sdist"}],
    )


# --------------------------------------------------------------------------- #
# install-check.py (pure helpers)
# --------------------------------------------------------------------------- #

INSTALL_CHECK = "install-check.py"


def test_install_check_version_json_url() -> None:
    module = _load(INSTALL_CHECK)
    assert module.version_json_url("pypi", "foo", "1.0") == "https://pypi.org/pypi/foo/1.0/json"
    assert (
        module.version_json_url("testpypi", "foo", "1.0")
        == "https://test.pypi.org/pypi/foo/1.0/json"
    )


def test_install_check_simple_index_url() -> None:
    module = _load(INSTALL_CHECK)
    assert module.simple_index_url("pypi") == "https://pypi.org/simple"
    assert module.simple_index_url("testpypi") == "https://test.pypi.org/simple"


def test_install_check_build_command_pypi() -> None:
    module = _load(INSTALL_CHECK)
    command = module.build_install_command("pypi", "foo", "1.0", [], "/venv/bin/python")
    assert "--extra-index-url" not in command
    assert command[-1] == "foo==1.0"
    assert "https://pypi.org/simple" in command


def test_install_check_build_command_testpypi_adds_pypi_extra() -> None:
    module = _load(INSTALL_CHECK)
    command = module.build_install_command("testpypi", "foo", "1.0", ["--no-binary", ":all:"], "py")
    assert command[command.index("--index-url") + 1] == "https://test.pypi.org/simple"
    assert command[command.index("--extra-index-url") + 1] == "https://pypi.org/simple"
    assert "--no-binary" in command and command[-1] == "foo==1.0"


def test_install_check_parse_list() -> None:
    module = _load(INSTALL_CHECK)
    assert module._parse_list("foo\n\n  bar \n") == ["foo", "bar"]
    assert module._parse_list("") == []


@pytest.mark.parametrize("argument", ["-i", "--index-url=x", "--extra-index-url", "-ihttps://x"])
def test_install_check_rejects_index_flags(argument: str) -> None:
    module = _load(INSTALL_CHECK)
    with pytest.raises(SystemExit) as excinfo:
        module._parse_arguments(argument)
    assert "must not select a package index" in str(excinfo.value)


def test_install_check_accepts_benign_arguments() -> None:
    module = _load(INSTALL_CHECK)
    assert module._parse_arguments("--no-binary :all:") == ["--no-binary", ":all:"]


def test_install_check_parse_timeout() -> None:
    module = _load(INSTALL_CHECK)
    assert module._parse_timeout("15") == 15.0
    with pytest.raises(SystemExit):
        module._parse_timeout("0")
    with pytest.raises(SystemExit):
        module._parse_timeout("abc")


# --------------------------------------------------------------------------- #
# Generated workflow shape
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def published() -> dict[str, Any]:
    item = {w.id: w for w in load_catalog()}["pypi-publish"]
    return build_published_workflow(item)


def test_publish_has_no_checkout_channel(published) -> None:
    inputs = published["on"]["workflow_call"]["inputs"]
    assert "artifact-download-enabled" in inputs
    assert not any(name.startswith("checkout-") for name in inputs)


def test_job_permissions_are_least_privilege(published) -> None:
    jobs = published["jobs"]
    assert jobs["validate"]["permissions"] == {}
    # The generator uniformly grants the io host job contents: read.
    assert jobs["verify"]["permissions"] == {"actions": "read", "contents": "read"}
    assert jobs["publish"]["permissions"] == {"actions": "read", "id-token": "write"}
    assert jobs["install-check"]["permissions"] == {}


def test_caller_required_permissions_union(published) -> None:
    assert caller_required_permissions(published) == {
        "actions": "read",
        "contents": "read",
        "id-token": "write",
    }


def test_publish_job_is_oidc_only_and_skips_on_dry_run(published) -> None:
    publish = published["jobs"]["publish"]
    assert publish["if"] == "${{ !inputs.publish-dry-run-enabled }}"
    assert publish["environment"]["url"] == "${{ needs.verify.outputs.release-url }}"
    steps = publish["steps"]
    action_step = next(s for s in steps if str(s.get("uses", "")).startswith("pypa/gh-action"))
    assert action_step["uses"] == GH_ACTION_PYPI_PUBLISH
    assert GH_ACTION_PYPI_PUBLISH in PINS_BY_REF
    with_block = action_step["with"]
    assert "user" not in with_block and "password" not in with_block
    assert with_block["repository-url"] == "${{ needs.validate.outputs.repository-url }}"


def test_download_step_injected_in_verify_and_publish(published) -> None:
    for job_id in ("verify", "publish"):
        steps = published["jobs"][job_id]["steps"]
        assert any("download-artifact" in str(step.get("uses", "")) for step in steps)
