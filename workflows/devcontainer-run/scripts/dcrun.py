"""Shared input-validation core for devcontainer-run.

validate-inputs.py (the fail-fast validate job), check-registry-auth.py (the
registry-auth preflight), and run-devcontainer.py all resolve the caller inputs
through this module so every job agrees exactly on what is legal. The run-only
config-synthesis, secret-materialization, and argv helpers live in the sibling
dcrun_run module (imported only by the run job) so the validate job inlines just
this smaller validation core -- keeping the generated workflow under the size cap.
This module never imports dcrun_run, so it can be inlined standalone.

Every input reaches this module only through os.environ (mapped from inputs.* by
the workflow), never interpolated into a shell string; see dcrun_run for how the
`devcontainer up`/`exec` argv are assembled programmatically and run without a
shell. This is the whole point of the env-mediated design.
"""

from __future__ import annotations

import json
import re
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
# ASCII control characters (C0 range plus DEL). container-env/cache entries are
# split on newlines and then rejected if any control char survives, so an embedded
# newline/escape/NUL in a single entry is a hard error rather than a silent split.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# A remoteUser value: a username or a bare numeric uid. It is written into JSON
# (never a shell), so this only rejects whitespace/control and shell-looking junk.
_REMOTE_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
# A pinned @devcontainers/cli npm version. Constraining it here keeps the
# env-mediated `npx --yes @devcontainers/cli@<version>` invocation safe.
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
    cache_enabled: bool  # whether the actions/cache restore/save step is active
    cache_paths: tuple[str, ...]  # host/workspace paths cached, one per line
    cache_key: str  # exact restore/save key
    cache_restore_keys: tuple[str, ...]  # ordered fallback key prefixes


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
    cache_enabled, cache_paths, cache_key, cache_restore_keys = _validate_cache(env)

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
        cache_enabled=cache_enabled,
        cache_paths=cache_paths,
        cache_key=cache_key,
        cache_restore_keys=cache_restore_keys,
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
    """Validate the non-secret container-env bundle into KEY=VALUE lines.

    Split on newlines only (not the broader str.splitlines set) so an entry that
    smuggles an embedded control character is rejected here rather than silently
    torn into two entries. The key must be a POSIX env name; the value is taken
    literally after the first '=' (so '=' and spaces in a value are fine) and is
    never eval'd -- it is handed to `--remote-env KEY=VALUE` verbatim.
    """
    entries: list[str] = []
    for line in value.split("\n"):
        item = line.strip()
        if not item:
            continue
        if _CONTROL.search(item):
            raise SystemExit(
                f"container-env has a control character in an entry: {line!r}; entries must be "
                "plain KEY=VALUE lines separated by newlines."
            )
        if "=" not in item:
            raise SystemExit(
                f"container-env entries must be KEY=VALUE (newline-separated); got {line!r}."
            )
        key = item.split("=", 1)[0]
        if not _ENV_NAME.match(key):
            raise SystemExit(f"container-env has an invalid environment variable name: {key!r}.")
        entries.append(item)
    return tuple(entries)


def _validate_cache(env: Mapping[str, str]) -> tuple[bool, tuple[str, ...], str, tuple[str, ...]]:
    """Validate the actions/cache inputs (only enforced when cache-enabled).

    cache-paths / cache-key / cache-restore-keys reach the SHA-pinned actions/cache
    step through its `with:` block (never a run: body), so they are injection-safe by
    construction; this still rejects control characters and requires the paths+key
    that make the step meaningful. Paths may be workspace-relative (e.g. .pixi, which
    the container sees through the bind mount) or absolute host paths. When
    cache-enabled is false the values are ignored (the step is `if:`-gated off), so
    validation is skipped entirely.
    """
    enabled = _truthy(env.get("CACHE_ENABLED", ""))
    if not enabled:
        return False, (), "", ()
    paths = _split_cache_lines(env.get("CACHE_PATHS", ""), "cache-paths")
    if not paths:
        raise SystemExit(
            "cache-enabled is true but cache-paths is empty; provide at least one "
            "newline-separated path to cache (e.g. .pixi)."
        )
    key = env.get("CACHE_KEY", "").strip()
    if not key:
        raise SystemExit(
            "cache-enabled is true but cache-key is empty; provide a non-empty cache-key."
        )
    if _CONTROL.search(key):
        raise SystemExit("cache-key must not contain control characters (including newlines).")
    restore_keys = _split_cache_lines(env.get("CACHE_RESTORE_KEYS", ""), "cache-restore-keys")
    return True, paths, key, restore_keys


def _split_cache_lines(value: str, field: str) -> tuple[str, ...]:
    """Split a newline list into stripped entries, rejecting control characters.

    Splitting on '\\n' only (then rejecting any surviving control char) means an
    embedded newline/escape inside a single path or restore-key is a hard error, not
    a silent extra entry.
    """
    items: list[str] = []
    for line in value.split("\n"):
        item = line.strip()
        if not item:
            continue
        if _CONTROL.search(item):
            raise SystemExit(f"{field} has a control character in an entry: {line!r}.")
        items.append(item)
    return tuple(items)


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


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
