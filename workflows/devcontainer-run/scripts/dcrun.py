"""Shared validation, config-synthesis, and argv helpers for devcontainer-run.

validate-inputs.py (the fail-fast validate job), check-registry-auth.py (the
registry-auth preflight), run-devcontainer.py, and cleanup.py all resolve the
caller inputs through this module so every job agrees exactly on what is legal.

Every input reaches this module only through os.environ (mapped from inputs.* by
the workflow), never interpolated into a shell string. run-devcontainer.py builds
the `devcontainer up`/`devcontainer exec` argv programmatically and calls
subprocess.run without a shell; the caller's run-command is delivered as a single
literal argv token to the container shell's -c (the intended, contained place for
shell semantics), so a `$(...)`, `;`, or space in it is never re-expanded by the
workflow. This is the whole point of the env-mediated design.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Syntactic image-reference grammar, identical to paper-openjournals/pandoc: a
# well-formed [registry/]name[:tag][@digest] reference. Validation is syntactic
# only; the caller is trusted to supply an image they trust (it runs with the
# workspace bind-mounted).
_ALNUM = r"[a-z0-9]+"
_SEPARATOR = r"(?:[._]|__|[-]+)"
_PATH_COMPONENT = rf"{_ALNUM}(?:{_SEPARATOR}{_ALNUM})*"
_NAME = rf"{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_DOMAIN = rf"{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*(?::[0-9]+)?"
_TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
_DIGEST = r"[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9A-Fa-f]{32,}"
_IMAGE_REFERENCE = re.compile(rf"^(?:{_DOMAIN}/)?{_NAME}(?::{_TAG})?(?:@{_DIGEST})?$")

# run-shell enum: the shell the caller's run-command is executed under.
SHELLS = ("bash", "sh")
# --update-remote-user-uid-default enum.
UID_MODES = ("never", "on", "off")
# A POSIX-ish environment variable name for container-env keys.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A remoteUser value: a username or a bare numeric uid. It is written into JSON
# (never a shell), so this only rejects whitespace/control and shell-looking junk.
_REMOTE_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
# A pinned @devcontainers/cli npm version. Constraining it here keeps the
# env-mediated `npm install -g @devcontainers/cli@<version>` install safe.
_CLI_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+.][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class Config:
    """A fully validated invocation, shared by every job."""

    image: str  # '' when a devcontainer-config-file supplies the image instead
    config_file: str  # validated workspace-relative path, or ''
    run_command: str
    run_shell: str
    run_working_directory: str  # validated workspace-relative subdir, or ''
    remote_user: str  # '' means "leave the config/label remoteUser untouched"
    skip_post_create: bool
    update_remote_user_uid: str
    container_env: tuple[str, ...]  # validated KEY=VALUE lines
    features: str  # raw JSON object string for --additional-features, or ''
    cli_version: str


def parse_and_validate(env: Mapping[str, str], *, require_workspace: bool = True) -> Config:
    """Validate every input and return the resolved Config.

    Runs in the validate job (before checkout) and in the run job (after
    checkout); neither path touches the filesystem here, so both agree exactly.
    The devcontainer-config-file is only checked lexically (containment); its
    existence and its JSON contents are validated by run-devcontainer.py once the
    checkout is present.
    """
    workspace = _workspace(env, require_workspace)

    run_command = env.get("RUN_COMMAND", "")
    if not run_command.strip():
        raise SystemExit("run-command is required; it must not be empty.")

    run_shell = env.get("RUN_SHELL", "bash").strip() or "bash"
    if run_shell not in SHELLS:
        raise SystemExit(f"run-shell must be one of {', '.join(SHELLS)}; got {run_shell!r}.")

    image = _validate_image(env.get("DEVCONTAINER_IMAGE", ""))
    config_file = _validate_config_file(env.get("DEVCONTAINER_CONFIG_FILE", ""), workspace)
    if not image and not config_file:
        raise SystemExit(
            "at least one of devcontainer-image or devcontainer-config-file is required "
            "so the run has an image to start (no image => nothing to run)."
        )

    working_directory = _validate_working_directory(env.get("RUN_WORKING_DIRECTORY", ""), workspace)
    remote_user = _validate_remote_user(env.get("REMOTE_USER", ""))
    update_uid = env.get("UPDATE_REMOTE_USER_UID", "on").strip() or "on"
    if update_uid not in UID_MODES:
        raise SystemExit(
            f"update-remote-user-uid must be one of {', '.join(UID_MODES)}; got {update_uid!r}."
        )
    container_env = _validate_container_env(env.get("CONTAINER_ENV", ""))
    features = _validate_features(env.get("DEVCONTAINER_FEATURES", ""))
    cli_version = _validate_cli_version(env.get("DEVCONTAINER_CLI_VERSION", ""))

    return Config(
        image=image,
        config_file=config_file,
        run_command=run_command,
        run_shell=run_shell,
        run_working_directory=working_directory,
        remote_user=remote_user,
        skip_post_create=_truthy(env.get("SKIP_POST_CREATE", "")),
        update_remote_user_uid=update_uid,
        container_env=container_env,
        features=features,
        cli_version=cli_version,
    )


def _workspace(env: Mapping[str, str], require_workspace: bool) -> Path:
    value = env.get("GITHUB_WORKSPACE")
    if not value:
        if not require_workspace:
            return Path.cwd()
        raise SystemExit(
            "GITHUB_WORKSPACE is not set; devcontainer-run validation must run in a "
            "GitHub Actions or act runner environment where it is defined."
        )
    return Path(value).resolve()


def _validate_image(value: str) -> str:
    image = value.strip()
    if not image:
        return ""
    if not _IMAGE_REFERENCE.match(image):
        raise SystemExit(
            f"devcontainer-image is not a valid image reference: {value!r}. "
            "Expected [registry/]name[:tag][@digest]."
        )
    return image


def _validate_config_file(value: str, workspace: Path) -> str:
    if not value.strip():
        return ""
    return _workspace_relative(value, workspace, "devcontainer-config-file")


def _validate_working_directory(value: str, workspace: Path) -> str:
    if not value.strip():
        return ""
    return _workspace_relative(value, workspace, "run-working-directory")


def _validate_remote_user(value: str) -> str:
    user = value.strip()
    if not user:
        return ""
    if not _REMOTE_USER.match(user):
        raise SystemExit(
            f"remote-user must be a plain username or uid: {value!r}. "
            "Allowed characters are letters, digits, '_', '.', and '-'."
        )
    return user


def _validate_container_env(value: str) -> tuple[str, ...]:
    entries: list[str] = []
    for line in value.splitlines():
        item = line.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit(
                f"container-env entries must be KEY=VALUE (newline-separated); got {line!r}."
            )
        key = item.split("=", 1)[0]
        if not _ENV_NAME.match(key):
            raise SystemExit(f"container-env has an invalid environment variable name: {key!r}.")
        entries.append(item)
    return tuple(entries)


def _validate_features(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"devcontainer-features must be valid JSON: {error}.") from error
    if not isinstance(parsed, dict):
        raise SystemExit("devcontainer-features must be a JSON object of feature-id -> options.")
    return raw


def _validate_cli_version(value: str) -> str:
    version = value.strip()
    if not version:
        raise SystemExit("devcontainer-cli-version is required (the pinned @devcontainers/cli).")
    if not _CLI_VERSION.match(version):
        raise SystemExit(
            f"devcontainer-cli-version must be a valid version (e.g. 0.87.0); got {value!r}."
        )
    return version


def _workspace_relative(value: str, workspace: Path, field: str) -> str:
    """Return the workspace-relative POSIX path, rejecting escapes.

    Rejects absolute paths and any '..' component before resolving, then confirms
    the resolved path stays inside GITHUB_WORKSPACE.
    """
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SystemExit(
            f"{field} must stay inside GITHUB_WORKSPACE (no absolute paths and no '..'): {value}"
        )
    resolved = (workspace / candidate).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise SystemExit(f"{field} must stay inside GITHUB_WORKSPACE: {value}")
    return resolved.relative_to(workspace).as_posix()


def validate_registry_auth(env: Mapping[str, str]) -> None:
    """Refuse to send github.token to a registry other than ghcr.io.

    Verbatim from build-devcontainer: the docker-login password falls back to
    github.token only for ghcr.io. Any other registry must supply an explicit
    docker-password secret, otherwise the caller could silently leak github.token
    to a third-party registry. This runs in its own validate-job step because it
    reads a secret-presence expression, which the validation-failure scenario
    harness (inputs-only) cannot reconstruct.
    """
    if not _truthy(env.get("DOCKER_LOGIN_ENABLED", "")):
        return
    if _truthy(env.get("DOCKER_PASSWORD_SET", "")):
        return
    registry = env.get("DOCKER_REGISTRY", "").strip().lower()
    if registry != "ghcr.io":
        target = registry or "docker hub"
        raise SystemExit(
            f"docker-login-enabled is true for registry {target!r} but no docker-password "
            "secret was provided. The github.token login fallback is restricted to ghcr.io; "
            "pass docker-password to authenticate to any other registry."
        )


# --------------------------------------------------------------------------- #
# Config synthesis + argv (run job)                                            #
# --------------------------------------------------------------------------- #
def parse_jsonc(text: str) -> object:
    """Parse a devcontainer.json, tolerating JSONC comments / trailing commas.

    Plain JSON parses directly (the common case and every checked-in fixture);
    only a JSONDecodeError falls back to comment/trailing-comma stripping, so a
    valid document is never mangled.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_jsonc(text))


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_caller_config(workspace: Path, config_file: str) -> dict | None:
    """Read and JSON-parse the caller's devcontainer.json, or None when unset."""
    if not config_file:
        return None
    path = (workspace / config_file).resolve()
    if not path.is_file():
        raise SystemExit(f"devcontainer-config-file does not exist or is not a file: {config_file}")
    parsed = parse_jsonc(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit("devcontainer-config-file must contain a JSON object.")
    return parsed


def synthesize_override_config(config: Config, caller_config: dict | None) -> dict:
    """Build the override devcontainer config written to RUNNER_TEMP.

    When no config-file is given this is a minimal {"image": <ref>} that the
    image's devcontainer.metadata label enriches with features/hooks/user/env.
    When a config-file IS given it is the base, so its features and lifecycle
    hooks are preserved. devcontainer-image (when set) overrides the base image;
    remote-user (when set) forces the exec user. The resolved config MUST carry
    an image so the run never rebuilds from a Dockerfile.
    """
    base: dict = dict(caller_config) if caller_config else {}
    if config.image:
        base["image"] = config.image
    resolved = base.get("image")
    if not isinstance(resolved, str) or not resolved.strip():
        raise SystemExit(
            "no image could be resolved: provide devcontainer-image, or a "
            'devcontainer-config-file whose JSON sets "image". devcontainer-run '
            "runs a prebuilt image and never builds from a Dockerfile."
        )
    if config.remote_user:
        base["remoteUser"] = config.remote_user
    return base


def cli_invocation(config: Config) -> list[str]:
    """The pinned @devcontainers/cli invocation prefix.

    Run ephemerally with npx (the npm peer of uvx), never `npm install -g`: the
    version is pinned, nothing is installed into a global prefix, and it keeps the
    generated workflow free of an ad-hoc package-install step.
    """
    return ["npx", "--yes", f"@devcontainers/cli@{config.cli_version}"]


def build_up_argv(config: Config, workspace: Path, config_path: Path, id_label: str) -> list[str]:
    """Assemble the `devcontainer up` argv (JSON result, no rebuild)."""
    argv = [
        *cli_invocation(config),
        "up",
        "--workspace-folder",
        str(workspace),
        "--override-config",
        str(config_path),
        "--id-label",
        id_label,
        "--log-format",
        "json",
        "--update-remote-user-uid-default",
        config.update_remote_user_uid,
        "--remove-existing-container",
    ]
    if config.skip_post_create:
        argv.append("--skip-post-create")
    if config.features:
        argv += ["--additional-features", config.features]
    for entry in config.container_env:
        argv += ["--remote-env", entry]
    return argv


def build_exec_command(config: Config) -> str:
    """The single -c payload the container shell runs.

    With run-working-directory empty (the default) this is the caller's
    run-command verbatim, so it stays one literal argv token. When a working
    directory is set, a validated `cd` is prepended (the directory is
    shell-quoted; the caller command still owns everything after &&).
    """
    if config.run_working_directory:
        return f"cd {shlex.quote(config.run_working_directory)} && {config.run_command}"
    return config.run_command


def build_exec_argv(config: Config, workspace: Path, config_path: Path, id_label: str) -> list[str]:
    """Assemble the `devcontainer exec` argv for the caller's run-command.

    The same --override-config and --id-label as `up` correlate exec to the one
    container started this run. The run-command is passed env-mediated as a single
    argv token to `<run-shell> -c`, never interpolated into a workflow run: block.
    """
    argv = [
        *cli_invocation(config),
        "exec",
        "--workspace-folder",
        str(workspace),
        "--override-config",
        str(config_path),
        "--id-label",
        id_label,
    ]
    for entry in config.container_env:
        argv += ["--remote-env", entry]
    argv += ["--", config.run_shell, "-c", build_exec_command(config)]
    return argv


def parse_up_result(stdout: str) -> dict:
    """Return the JSON result object from `devcontainer up --log-format json`.

    The result is the last stdout line that parses as a JSON object carrying an
    "outcome" key; any preceding structured log lines are skipped.
    """
    result: dict | None = None
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "outcome" in parsed:
            result = parsed
    if result is None:
        raise SystemExit("devcontainer up did not emit a JSON result object; cannot continue.")
    return result


def build_cleanup_ids_command(id_label: str) -> list[str]:
    """The `docker ps` argv that lists containers labelled for this run."""
    return ["docker", "ps", "-aq", "--filter", f"label={id_label}"]


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
