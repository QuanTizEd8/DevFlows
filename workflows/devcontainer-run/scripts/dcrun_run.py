"""Config-synthesis, secret-materialization, and argv helpers for devcontainer-run.

The run job's scripts (run-devcontainer.py, cleanup.py) resolve here; the
validate job never imports this module, so its inlined footprint stays small (the
generated workflow inlines each script per job, so keeping the run-only helpers
out of the validate copy is what keeps the file under the size cap). The
validation core -- Config, the syntactic regexes, and _truthy -- lives in the
sibling dcrun module, which this module imports; dcrun never imports back, so
there is no cycle and the validate job can inline dcrun standalone.

Every input still arrives through os.environ (mapped from inputs.* by the
workflow), never interpolated into a shell string. The `devcontainer up`/`exec`
argv are assembled programmatically and run without a shell; the caller's
run-command is delivered as a single literal argv token to the container shell's
-c, so a `$(...)`, `;`, or space in it is never re-expanded by the workflow.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from dcrun import _CONTROL, _ENV_NAME, _IMAGE_REFERENCE, Config

# Keys defensively dropped from a run-secrets bundle: the ephemeral Actions token,
# which a `toJSON(secrets)` + `secrets: inherit` bundle would otherwise carry into
# the user command. GitHub exposes it as GITHUB_TOKEN and (in the serialized
# secrets context) as github_token, so both spellings are stripped.
_DROPPED_SECRET_KEYS = frozenset({"github_token", "GITHUB_TOKEN"})
# RUNNER_TEMP subdirectory holding this run's generated override config and the
# 0600 secret files. run-devcontainer.py writes them here; cleanup.py shreds the
# secret files from the same place in its always() step.
_STATE_SUBDIR = "devflows-devcontainer-run"
# Build-recipe keys stripped when an image is forced: devcontainer-run runs a
# PREBUILT image and must never build, so any Dockerfile/compose recipe a
# config-file carried is removed before `up` sees it (see synthesize_override_config).
_BUILD_KEYS = ("build", "dockerFile", "dockerComposeFile")


# --------------------------------------------------------------------------- #
# run-secrets bundle (a DECLARED workflow_call secret, GitHub-masked)          #
# --------------------------------------------------------------------------- #
def parse_run_secrets(raw: str) -> dict[str, str]:
    """Parse the masked run-secrets bundle into a {KEY: VALUE} dict.

    Accepts a JSON object (primary; text starts with ``{``, values must be
    strings) or a ``KEY=VALUE``-per-line form (blank/``#`` lines skipped, split on
    the first ``=``). Each KEY must be a POSIX env name with no control character;
    a VALUE is an opaque literal. github_token / GITHUB_TOKEN are dropped so a
    ``toJSON(secrets)`` + ``inherit`` bundle never injects the Actions token.
    Errors quote only KEY names (never a value), and the JSON error is not chained,
    so no secret material leaks into the log.
    """
    text = raw.strip()
    if not text:
        return {}
    pairs = _run_secrets_from_json(text) if text.startswith("{") else _run_secrets_from_lines(raw)
    result: dict[str, str] = {}
    for key, value in pairs:
        if key in _DROPPED_SECRET_KEYS:
            continue
        if _CONTROL.search(key):
            raise SystemExit("run-secrets has a control character in a key name.")
        if not _ENV_NAME.match(key):
            raise SystemExit(
                f"run-secrets has an invalid environment variable name: {key!r}. "
                "Keys must match [A-Za-z_][A-Za-z0-9_]*."
            )
        result[key] = value
    return result


def _run_secrets_from_json(text: str) -> list[tuple[str, str]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # `from None`: the decoder message can quote secret material; do not chain.
        raise SystemExit(
            "run-secrets starts with '{' but is not valid JSON. Provide a JSON object "
            "of NAME -> value (assembled with per-value toJSON), or the KEY=VALUE form."
        ) from None
    if not isinstance(parsed, dict):
        raise SystemExit("run-secrets JSON must be an object of NAME -> value.")
    pairs: list[tuple[str, str]] = []
    for key, value in parsed.items():
        if not isinstance(value, str):
            raise SystemExit(
                f"run-secrets value for {str(key)!r} must be a string; got {type(value).__name__}."
            )
        pairs.append((str(key), value))
    return pairs


def _run_secrets_from_lines(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in raw.split("\n"):
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if "=" not in item:
            raise SystemExit(
                "run-secrets has a KEY=VALUE line with no '='; each non-blank, non-# "
                "line must be KEY=VALUE."
            )
        key, value = item.split("=", 1)
        pairs.append((key, value))
    return pairs


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
    # devcontainer-image (the input) is regex-validated in the validate job, but an
    # image taken from the config-file's own "image" field never passed that gate.
    # Apply the same syntactic check to whatever will be pulled so the value handed
    # to `docker pull` / `up` is always a well-formed reference.
    if not _IMAGE_REFERENCE.match(resolved.strip()):
        raise SystemExit(
            f"the resolved devcontainer image is not a valid reference: {resolved!r}. "
            'It comes from the devcontainer-config-file\'s "image" field; expected '
            "[registry/]name[:tag][@digest]."
        )
    # Force a pure image-based config: strip any build recipe the config-file carried
    # (build / dockerFile / dockerComposeFile). devcontainer-run runs a PREBUILT image
    # and must never build, so a build recipe sitting next to the forced image -- whose
    # precedence in `devcontainer up` is ambiguous and could trigger a build -- is
    # removed. The image's own features/hooks/user/env still apply via its
    # devcontainer.metadata label, and any config-file features/hooks are preserved.
    for build_key in _BUILD_KEYS:
        base.pop(build_key, None)
    if config.remote_user:
        base["remoteUser"] = config.remote_user
    return base


def build_exec_override_config(base_override: dict, secrets: Mapping[str, str]) -> dict:
    """The exec-phase override config: the base plus the run-secrets in remoteEnv.

    Secrets go in remoteEnv only for ``exec`` (never ``up``): exec injects them via
    a transient ``docker exec -e``, so they never land in the persisted
    ``devcontainer.metadata`` label an ``up`` remoteEnv would leak. Any caller
    remoteEnv is preserved; a shallow copy leaves the base (for ``up``) unchanged.
    """
    exec_override = dict(base_override)
    existing = exec_override.get("remoteEnv")
    remote_env = dict(existing) if isinstance(existing, dict) else {}
    remote_env.update(secrets)
    exec_override["remoteEnv"] = remote_env
    return exec_override


def state_dir(runner_temp: Path) -> Path:
    """RUNNER_TEMP subdirectory holding this run's generated override + secret files."""
    return runner_temp / _STATE_SUBDIR


def secret_file_paths(runner_temp: Path) -> tuple[Path, Path]:
    """The two 0600 secret files (up --secrets-file, exec override); cleanup shreds them."""
    directory = state_dir(runner_temp)
    return directory / "secrets.json", directory / "exec-config.json"


def write_secret_file(path: Path, data: object) -> None:
    """Serialize ``data`` to a 0600 JSON file, never briefly readable and never echoed."""
    text = json.dumps(data, indent=2) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def shred_file(path: Path) -> bool:
    """Overwrite with zeros, fsync, then unlink; True if removed, tolerant of absence."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    try:
        fd = os.open(path, os.O_WRONLY)
        try:
            os.write(fd, b"\0" * size)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def cli_invocation(config: Config) -> list[str]:
    """The pinned @devcontainers/cli invocation prefix.

    Run ephemerally with npx (the npm peer of uvx), never `npm install -g`: the
    version is pinned, nothing is installed into a global prefix, and it keeps the
    generated workflow free of an ad-hoc package-install step.
    """
    return ["npx", "--yes", f"@devcontainers/cli@{config.cli_version}"]


def build_up_argv(
    config: Config,
    workspace: Path,
    config_path: Path,
    id_label: str,
    secrets_file: Path | None = None,
) -> list[str]:
    """Assemble the `devcontainer up` argv (JSON result, no rebuild).

    When run-secrets carried values, ``secrets_file`` is the 0600 JSON file added
    as ``--secrets-file`` so the creation HOOKS get the secrets (only ``up`` accepts
    the flag; ``exec`` rejects it). Only the PATH lands in the argv, never a value,
    and secrets are kept out of this config's remoteEnv (which ``up`` would bake
    into the persisted devcontainer.metadata label).
    """
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
    if secrets_file is not None:
        argv += ["--secrets-file", str(secrets_file)]
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
