from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from devflows.catalog import load_workflow
from devflows.publish import (
    MAX_GENERATED_WORKFLOW_BYTES,
    build_published_workflow,
    caller_required_permissions,
    render_published_workflow,
)

REPO = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO / "workflows" / "binder-build"
SCRIPT_DIR = WORKFLOW_DIR / "scripts"


def _load_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Load binder-build's parsing under a UNIQUE name so it never collides with another
# workflow's parsing.py (anaconda-publish ships one too). It is injected as the bare
# ``parsing`` name only for the duration of a script exec below.
parsing = _load_module(SCRIPT_DIR / "parsing.py", "binder_build_parsing")


def _load_script(name: str) -> ModuleType:
    """Exec a binder-build script with its sibling ``parsing`` bound to ours.

    The script does ``import parsing``; we point sys.modules['parsing'] at our unique
    module for the exec and restore the previous binding afterward so a concurrently
    loaded workflow's parsing is never clobbered.
    """
    path = SCRIPT_DIR / name
    module_name = "binder_build_" + name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    previous = sys.modules.get("parsing")
    sys.modules["parsing"] = parsing
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is not None:
            sys.modules["parsing"] = previous
        else:
            sys.modules.pop("parsing", None)
    return module


def _parse_github_output(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if "<<" in line:
            name, _, delimiter = line.partition("<<")
            index += 1
            body: list[str] = []
            while index < len(lines) and lines[index] != delimiter:
                body.append(lines[index])
                index += 1
            parsed[name] = "\n".join(body)
        index += 1
    return parsed


# --------------------------------------------------------------------------- #
# parsing.py: references, tags, paths, versions, artifact names                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    ["ghcr.io/owner/repo-binder", "owner/repo", "myimage", "registry:5000/team/app"],
)
def test_validate_image_name_accepts_untagged_references(name: str) -> None:
    assert parsing.validate_image_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "ghcr.io/owner/repo:latest", "owner/Repo", "ghcr.io/owner/repo@sha256:ab", "a b"],
)
def test_validate_image_name_rejects_tagged_or_malformed(name: str) -> None:
    with pytest.raises(parsing.SpecError):
        parsing.validate_image_name(name)


def test_validate_tag_list_parses_and_rejects_empty() -> None:
    assert parsing.validate_tag_list("latest\nv1.2.3\n", field="image-tags") == ["latest", "v1.2.3"]
    with pytest.raises(parsing.SpecError):
        parsing.validate_tag_list("   \n  ", field="image-tags")
    with pytest.raises(parsing.SpecError):
        parsing.validate_tag_list("bad tag", field="image-tags")


def test_validate_tag_prefix() -> None:
    assert parsing.validate_tag_prefix("sha-", field="image-sha-tag-prefix") == "sha-"
    with pytest.raises(parsing.SpecError):
        parsing.validate_tag_prefix("", field="image-sha-tag-prefix")
    with pytest.raises(parsing.SpecError):
        parsing.validate_tag_prefix("bad/prefix", field="image-sha-tag-prefix")


@pytest.mark.parametrize("path", [".", "src", "nested/dir"])
def test_validate_source_path_accepts_contained(path: str) -> None:
    assert parsing.validate_source_path(path, field="repo2docker-source-path") == path


@pytest.mark.parametrize("path", ["", "/etc", "../outside", "a/../../b"])
def test_validate_source_path_rejects_escape(path: str) -> None:
    with pytest.raises(parsing.SpecError):
        parsing.validate_source_path(path, field="repo2docker-source-path")


@pytest.mark.parametrize("version", ["2026.4.0", "2024.7.0", "2025.12.3"])
def test_validate_version_accepts_date_based(version: str) -> None:
    assert parsing.validate_version(version, field="repo2docker-version") == version


@pytest.mark.parametrize(
    "version",
    ["", "1.2.3", "2026.4.0; os.system('x')", "2026.4.0rc1", "jupyter-repo2docker==2026.4.0"],
)
def test_validate_version_rejects_specifiers(version: str) -> None:
    with pytest.raises(parsing.SpecError):
        parsing.validate_version(version, field="repo2docker-version")


def test_validate_artifact_name() -> None:
    assert parsing.validate_artifact_name("binder-dockerfile", field="x") == "binder-dockerfile"
    for bad in ["", "bad/name", "bad name", "-leading"]:
        with pytest.raises(parsing.SpecError):
            parsing.validate_artifact_name(bad, field="x")


def test_validate_provider_and_url() -> None:
    assert parsing.validate_provider("gh", field="binder-cache-provider") == "gh"
    with pytest.raises(parsing.SpecError):
        parsing.validate_provider("evil", field="binder-cache-provider")
    assert parsing.validate_https_url("https://mybinder.org", field="binder-cache-endpoint")
    for bad in ["http://mybinder.org", "ftp://x", "https://"]:
        with pytest.raises(parsing.SpecError):
            parsing.validate_https_url(bad, field="binder-cache-endpoint")


# --------------------------------------------------------------------------- #
# parsing.py: repo2docker-arguments ALLOWLIST                                    #
# --------------------------------------------------------------------------- #
def test_parse_arguments_accepts_allowlisted() -> None:
    parsed = parsing.parse_repo2docker_arguments(
        "--debug --no-clean --json-logs --build-arg=FOO=1 --label=team=x",
        field="repo2docker-arguments",
    )
    assert parsed == ["--debug", "--no-clean", "--json-logs", "--build-arg=FOO=1", "--label=team=x"]
    assert parsing.parse_repo2docker_arguments("", field="repo2docker-arguments") == []


@pytest.mark.parametrize(
    "smuggled",
    [
        "--push",
        "--no-push",
        "--no-run",
        "--run",
        "--no-build",
        "--build",
        "--ref=abc",
        "--image-name=attacker/evil",
        "--image=attacker/evil",
        "-eSECRET=1",
        "-v/etc:/host",
        "-p8888",
        "./attacker-repo",
        "positional",
        "--appendix=RUN evil",
        "--build-arg",  # value flag with no =VALUE
        "--debug=1",  # bool flag with a value
    ],
)
def test_parse_arguments_rejects_owned_and_unlisted(smuggled: str) -> None:
    with pytest.raises(parsing.SpecError):
        parsing.parse_repo2docker_arguments(smuggled, field="repo2docker-arguments")


def test_parse_arguments_rejects_unbalanced_quote() -> None:
    with pytest.raises(parsing.SpecError) as excinfo:
        parsing.parse_repo2docker_arguments("--label='unbalanced", field="repo2docker-arguments")
    assert "could not be parsed as shell arguments" in str(excinfo.value)


def test_owned_flag_message_mentions_typed_inputs() -> None:
    with pytest.raises(parsing.SpecError) as excinfo:
        parsing.parse_repo2docker_arguments("--image-name=x", field="repo2docker-arguments")
    assert "owned by typed inputs" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# validate-inputs.py                                                            #
# --------------------------------------------------------------------------- #
_VALID_ENV = {
    "IMAGE_NAME": "ghcr.io/owner/repo-binder",
    "IMAGE_TAGS": "latest",
    "IMAGE_SHA_TAG_ENABLED": "false",
    "IMAGE_SHA_TAG_PREFIX": "sha-",
    "REPO2DOCKER_SOURCE_PATH": ".",
    "REPO2DOCKER_VERSION": "2026.4.0",
    "REPO2DOCKER_ARGUMENTS": "",
    "REPO2DOCKER_TIMEOUT_MINUTES": "30",
    "PUSH_TIMEOUT_MINUTES": "30",
    "PUBLISH_DRY_RUN_ENABLED": "true",
    "PUSH_ENVIRONMENT_NAME": "",
    "DOCKERFILE_ARTIFACT_ENABLED": "true",
    "DOCKERFILE_ARTIFACT_NAME": "binder-dockerfile",
    "BINDER_CACHE_WARM_ENABLED": "false",
    "BINDER_CACHE_PROVIDER": "gh",
    "BINDER_CACHE_REPOSITORY": "owner/repo",
    "BINDER_CACHE_REF": "abc",
    "BINDER_CACHE_ENDPOINT": "https://mybinder.org",
}


def _run_validate(monkeypatch, **overrides) -> None:
    module = _load_script("validate-inputs.py")
    env = {**_VALID_ENV, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    module.main()


def test_validate_accepts_dry_run(monkeypatch) -> None:
    _run_validate(monkeypatch)  # no raise


def test_validate_accepts_real_push_with_environment(monkeypatch) -> None:
    _run_validate(
        monkeypatch, PUBLISH_DRY_RUN_ENABLED="false", PUSH_ENVIRONMENT_NAME="binder-release"
    )


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"IMAGE_NAME": ""}, "image-name is required"),
        ({"IMAGE_NAME": "ghcr.io/o/r:tag"}, "WITHOUT a tag"),
        ({"IMAGE_TAGS": ""}, "non-empty newline-separated list"),
        (
            {"PUBLISH_DRY_RUN_ENABLED": "false", "PUSH_ENVIRONMENT_NAME": ""},
            "push-environment-name is required",
        ),
        ({"REPO2DOCKER_ARGUMENTS": "--push"}, "owned by typed inputs"),
        ({"REPO2DOCKER_ARGUMENTS": "-eSECRET=1"}, "only the allowlisted"),
        ({"REPO2DOCKER_ARGUMENTS": "./x"}, "only the allowlisted"),
        ({"REPO2DOCKER_ARGUMENTS": "--label='x"}, "could not be parsed"),
        ({"REPO2DOCKER_SOURCE_PATH": "../outside"}, "workspace-relative path"),
        ({"REPO2DOCKER_VERSION": "2026.4.0; x"}, "date-based jupyter-repo2docker version"),
        ({"DOCKERFILE_ARTIFACT_NAME": "bad/name"}, "artifact-safe token"),
        ({"IMAGE_SHA_TAG_ENABLED": "true", "IMAGE_SHA_TAG_PREFIX": "bad/x"}, "safe tag prefix"),
        ({"REPO2DOCKER_TIMEOUT_MINUTES": "0"}, "positive integer"),
        (
            {"BINDER_CACHE_WARM_ENABLED": "true", "BINDER_CACHE_PROVIDER": "evil"},
            "binder-cache-provider must be one of",
        ),
    ],
)
def test_validate_rejections(monkeypatch, overrides, needle) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run_validate(monkeypatch, **overrides)
    assert needle in str(excinfo.value)


# --------------------------------------------------------------------------- #
# build-binder.py                                                               #
# --------------------------------------------------------------------------- #
def test_build_binder_builds_argv_and_writes_proof(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("build-binder.py")
    (tmp_path / "src").mkdir()
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"stdout": "sha256:deadbeef\n", "returncode": 0})()
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("IMAGE_NAME", "ghcr.io/owner/repo-binder")
    monkeypatch.setenv("REPO2DOCKER_VERSION", "2026.4.0")
    monkeypatch.setenv("REPO2DOCKER_SOURCE_PATH", "src")
    monkeypatch.setenv("REPO2DOCKER_ARGUMENTS", "--label=team=x")
    monkeypatch.setenv("PUBLISH_DRY_RUN_ENABLED", "true")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("PROOF_DIR", str(tmp_path / "proof"))
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "image"))

    assert module.main() == 0
    build_cmd = calls[0]
    assert build_cmd[:5] == [
        "uvx",
        "--from",
        "jupyter-repo2docker==2026.4.0",
        "jupyter-repo2docker",
        "--no-run",
    ]
    assert "--image-name" in build_cmd
    assert (
        build_cmd[build_cmd.index("--image-name") + 1]
        == "ghcr.io/owner/repo-binder:devflows-binder-build"
    )
    assert "--label=team=x" in build_cmd
    assert build_cmd[-1] == str((tmp_path / "src").resolve())
    # dry-run must NOT docker save
    assert not any(cmd[:2] == ["docker", "save"] for cmd in calls)
    assert (tmp_path / "proof" / "image-id").read_text().strip() == "sha256:deadbeef"


def test_build_binder_saves_archive_when_not_dry_run(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("build-binder.py")
    (tmp_path / "src").mkdir()
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"stdout": "sha256:abc\n", "returncode": 0})()
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    for key, value in {
        "IMAGE_NAME": "ghcr.io/owner/repo-binder",
        "REPO2DOCKER_VERSION": "2026.4.0",
        "REPO2DOCKER_SOURCE_PATH": "src",
        "REPO2DOCKER_ARGUMENTS": "",
        "PUBLISH_DRY_RUN_ENABLED": "false",
        "GITHUB_WORKSPACE": str(tmp_path),
        "PROOF_DIR": str(tmp_path / "proof"),
        "ARCHIVE_DIR": str(tmp_path / "image"),
    }.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    save_calls = [cmd for cmd in calls if cmd[:2] == ["docker", "save"]]
    assert len(save_calls) == 1
    assert save_calls[0][-1] == "ghcr.io/owner/repo-binder:devflows-binder-build"


def test_build_binder_rejects_source_escape(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("build-binder.py")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: None)
    for key, value in {
        "IMAGE_NAME": "ghcr.io/owner/repo-binder",
        "REPO2DOCKER_VERSION": "2026.4.0",
        "REPO2DOCKER_SOURCE_PATH": "../escape",
        "REPO2DOCKER_ARGUMENTS": "",
        "PUBLISH_DRY_RUN_ENABLED": "true",
        "GITHUB_WORKSPACE": str(tmp_path),
        "PROOF_DIR": str(tmp_path / "proof"),
        "ARCHIVE_DIR": str(tmp_path / "image"),
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises((SystemExit, parsing.SpecError)):
        module.main()


# --------------------------------------------------------------------------- #
# push-image.py                                                                 #
# --------------------------------------------------------------------------- #
def test_push_image_tags_pushes_and_emits_outputs(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("push-image.py")
    calls: list[list[str]] = []
    image = "ghcr.io/owner/repo-binder"
    digest = "sha256:" + "a" * 64

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"stdout": json.dumps([f"{image}@{digest}"]), "returncode": 0})()
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    output = tmp_path / "gh_output"
    output.touch()
    for key, value in {
        "IMAGE_NAME": image,
        "IMAGE_BUILD_TAG": "devflows-binder-build",
        "IMAGE_TAGS": "latest\nv1.0.0",
        "IMAGE_SHA_TAG_ENABLED": "true",
        "IMAGE_SHA_TAG_PREFIX": "sha-",
        "GITHUB_SHA": "abc123",
        "IMAGE_ARCHIVE": str(tmp_path / "image.tar"),
        "DOCKERFILE_ARTIFACT_ENABLED": "true",
        "DOCKERFILE_PATH": str(tmp_path / "df" / "Dockerfile"),
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)

    assert module.main() == 0
    pushed = [cmd[2] for cmd in calls if cmd[:2] == ["docker", "push"]]
    assert pushed == [f"{image}:latest", f"{image}:v1.0.0", f"{image}:sha-abc123"]
    assert any(cmd[:2] == ["docker", "load"] for cmd in calls)
    outputs = _parse_github_output(output)
    assert outputs["image-ref"] == f"{image}:latest"
    assert outputs["image-digest"] == digest
    assert (tmp_path / "df" / "Dockerfile").read_text() == f"FROM {image}@{digest}\n"


def test_push_image_no_dockerfile_when_disabled(monkeypatch, tmp_path: Path) -> None:
    module = _load_script("push-image.py")
    image = "ghcr.io/owner/repo-binder"
    digest = "sha256:" + "b" * 64

    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return type("R", (), {"stdout": json.dumps([f"{image}@{digest}"]), "returncode": 0})()
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    output = tmp_path / "gh_output"
    output.touch()
    for key, value in {
        "IMAGE_NAME": image,
        "IMAGE_BUILD_TAG": "devflows-binder-build",
        "IMAGE_TAGS": "latest",
        "IMAGE_SHA_TAG_ENABLED": "false",
        "IMAGE_SHA_TAG_PREFIX": "sha-",
        "GITHUB_SHA": "abc123",
        "IMAGE_ARCHIVE": str(tmp_path / "image.tar"),
        "DOCKERFILE_ARTIFACT_ENABLED": "false",
        "DOCKERFILE_PATH": str(tmp_path / "df" / "Dockerfile"),
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    assert not (tmp_path / "df" / "Dockerfile").exists()


# --------------------------------------------------------------------------- #
# preflight-push.py                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "env, expect_fail",
    [
        (
            {
                "DOCKER_LOGIN_ENABLED": "true",
                "DOCKER_REGISTRY": "ghcr.io",
                "DOCKER_PASSWORD_SET": "false",
            },
            False,
        ),
        (
            {
                "DOCKER_LOGIN_ENABLED": "true",
                "DOCKER_REGISTRY": "docker.io",
                "DOCKER_PASSWORD_SET": "false",
            },
            True,
        ),
        (
            {
                "DOCKER_LOGIN_ENABLED": "true",
                "DOCKER_REGISTRY": "docker.io",
                "DOCKER_PASSWORD_SET": "true",
            },
            False,
        ),
        (
            {
                "DOCKER_LOGIN_ENABLED": "false",
                "DOCKER_REGISTRY": "docker.io",
                "DOCKER_PASSWORD_SET": "false",
            },
            False,
        ),
    ],
)
def test_preflight_requires_password_for_non_ghcr(monkeypatch, env, expect_fail) -> None:
    module = _load_script("preflight-push.py")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if expect_fail:
        with pytest.raises(SystemExit) as excinfo:
            module.main()
        assert "docker-password" in str(excinfo.value)
    else:
        assert module.main() == 0


# --------------------------------------------------------------------------- #
# warm-cache.py                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("returncode, expected", [(0, 0), (28, 0), (7, 1)])
def test_warm_cache_treats_timeout_as_success(monkeypatch, returncode, expected) -> None:
    module = _load_script("warm-cache.py")
    seen: list[list[str]] = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return type("R", (), {"returncode": returncode})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    for key, value in {
        "BINDER_CACHE_ENDPOINT": "https://mybinder.org/",
        "BINDER_CACHE_PROVIDER": "gh",
        "BINDER_CACHE_REPOSITORY": "owner/repo",
        "BINDER_CACHE_REF": "abc",
    }.items():
        monkeypatch.setenv(key, value)
    assert module.main() == expected
    assert seen[0][-1] == "https://mybinder.org/build/gh/owner/repo/abc"


# --------------------------------------------------------------------------- #
# Pin management + workflow shape                                               #
# --------------------------------------------------------------------------- #
def _published() -> dict:
    return build_published_workflow(load_workflow(WORKFLOW_DIR))


def _steps(job: dict) -> list[dict]:
    return [step for step in job.get("steps", []) if isinstance(step, dict)]


def _workflow_default(name: str) -> str:
    workflow = load_workflow(WORKFLOW_DIR)
    return str(workflow.workflow_call["inputs"][name]["default"])


def test_repo2docker_version_pin_matches_renovate_manager() -> None:
    default = _workflow_default("repo2docker-version")
    assert re.fullmatch(r"[0-9]{4}\.[0-9]{1,2}\.[0-9]+", default)
    renovate = (REPO / "renovate.json5").read_text(encoding="utf-8")
    assert "workflows/binder-build/workflow" in renovate
    # Pull Renovate's ACTUAL matchString for this manager (the one keyed on a YAML
    # `default:` line) out of renovate.json5 and apply it to the source workflow, so
    # the configured manager provably still matches the pinned default.
    match_strings = re.findall(r"'([^']*default: [^']*currentValue[^']*)'", renovate)
    assert len(match_strings) == 1, "expected exactly one binder-build default matchString"
    configured = match_strings[0].replace("\\\\", "\\")
    python_pattern = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", configured)
    source = (WORKFLOW_DIR / "workflow.yaml").read_text(encoding="utf-8")
    match = re.search(python_pattern, source)
    assert match is not None, python_pattern
    assert match.group("datasource") == "pypi"
    assert match.group("depName") == "jupyter-repo2docker"
    assert match.group("currentValue") == default


def _push_script_step() -> dict:
    # id: push is the actual invocation step; the "devflows-runtime" materialize step
    # also contains the string "push-image.py" because it inlines the script body.
    push = _published()["jobs"]["push-image"]
    return next(s for s in _steps(push) if s.get("id") == "push")


def test_internal_build_tag_matches_push_job_env() -> None:
    assert _push_script_step()["env"]["IMAGE_BUILD_TAG"] == parsing.INTERNAL_BUILD_TAG


def test_generated_workflow_stays_under_size_budget() -> None:
    rendered = render_published_workflow(load_workflow(WORKFLOW_DIR))
    assert len(rendered.encode("utf-8")) < 100_000
    assert MAX_GENERATED_WORKFLOW_BYTES == 115_000


def test_caller_required_permissions_union() -> None:
    assert caller_required_permissions(_published()) == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
        "packages": "write",
    }


def test_only_push_job_holds_credentialed_grants() -> None:
    jobs = _published()["jobs"]
    for job_id in ("validate", "warm-binder-cache"):
        assert jobs[job_id].get("permissions") == {}
    assert jobs["build-binder"]["permissions"] == {"contents": "read", "actions": "read"}
    push = jobs["push-image"]["permissions"]
    assert push["packages"] == "write"
    assert push["id-token"] == "write"
    assert push["attestations"] == "write"


def test_docker_password_isolated_to_login_step() -> None:
    # The secret VALUE (the fallback expression) reaches exactly one step -- the
    # docker/login-action step. Every other reference is the presence-only boolean.
    push = _published()["jobs"]["push-image"]
    value_steps = [
        step for step in _steps(push) if "secrets.docker-password ||" in json.dumps(step)
    ]
    assert len(value_steps) == 1
    assert value_steps[0]["uses"].startswith("docker/login-action@")
    assert "secrets.docker-password" in json.dumps(value_steps[0]["with"]["password"])
    # The push script step (the one that runs push-image.py) never sees the secret.
    assert "docker-password" not in json.dumps(_push_script_step().get("env", {}))


def test_push_job_binds_environment_and_serial_concurrency() -> None:
    push = _published()["jobs"]["push-image"]
    assert push["environment"]["name"] == "${{ inputs.push-environment-name }}"
    assert push["concurrency"]["group"] == "binder-build-${{ inputs.push-environment-name }}"
    assert push["concurrency"]["cancel-in-progress"] is False
    assert "!inputs.publish-dry-run-enabled" in push["if"]


def test_dry_run_skips_push_and_warm_jobs() -> None:
    jobs = _published()["jobs"]
    assert "!inputs.publish-dry-run-enabled" in jobs["push-image"]["if"]
    assert "!inputs.publish-dry-run-enabled" in jobs["warm-binder-cache"]["if"]
    assert jobs["warm-binder-cache"]["continue-on-error"] is True
    for job_id in ("validate", "build-binder"):
        assert "if" not in jobs[job_id]


def test_build_job_never_binds_environment_or_holds_secret() -> None:
    build = _published()["jobs"]["build-binder"]
    assert "environment" not in build
    for step in _steps(build):
        assert "docker-password" not in json.dumps(step)


def test_attestation_uses_push_digest_subject() -> None:
    push = _published()["jobs"]["push-image"]
    attest = next(
        s
        for s in _steps(push)
        if str(s.get("uses", "")).startswith("actions/attest-build-provenance@")
    )
    assert attest["if"] == "inputs.attestation-enabled"
    assert attest["with"]["subject-name"] == "${{ inputs.image-name }}"
    assert attest["with"]["subject-digest"] == "${{ steps.push.outputs.image-digest }}"
    assert attest["with"]["push-to-registry"] is True
