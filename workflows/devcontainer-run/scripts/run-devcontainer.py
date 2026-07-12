"""Start a prebuilt devcontainer and run the caller's command inside it.

Modelled on paper-openjournals' run-inara.py: every input arrives through
os.environ, the `devcontainer up`/`devcontainer exec` argv are assembled
programmatically (never a shell string), and subprocess.run is called without a
shell. The flow is:

  1. Resolve the override config (minimal {"image": ref} or the caller's
     devcontainer.json merged with the image/remote-user overrides), written to
     RUNNER_TEMP so the checkout is never mutated. When the caller supplied a
     run-secrets bundle (a declared, GitHub-masked secret), it is parsed here and
     materialized into two 0600 files under RUNNER_TEMP: a secrets.json (the
     `up --secrets-file` shape, delivering secrets to the lifecycle HOOKS) and a
     secrets-bearing exec override-config whose remoteEnv carries the secrets to
     the COMMAND via a transient `docker exec -e` (no persisted label). Secrets
     are never placed in the `up` override-config remoteEnv or in any argv.
  2. `docker pull` the resolved image first for a clean, fast failure when the
     ref is wrong or the registry credentials are missing (the pull otherwise
     rides `docker run` auto-pull deep inside `up`).
  3. `devcontainer up --override-config ... --id-label ... --log-format json`
     (+ --secrets-file when run-secrets was set) against the workspace bind mount
     (no rebuild), parse the JSON result, emit container-id / remote-user
     outputs, and fail loudly on outcome: error.
  4. `devcontainer exec --override-config <exec-config> ... -- <run-shell> -c
     <run-command>` and exit with the command's own exit code (faithful
     propagation: a nonzero command fails the step, so a misconfigured call can
     never silently pass).

Cleanup (docker rm + shredding the two secret files) is a separate always()
step, so a container or secret file left behind by a failed `up` is still
removed.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import dcrun
import dcrun_run


def main() -> int:
    config = dcrun.parse_and_validate(os.environ, require_workspace=True)
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    id_label = os.environ.get("ID_LABEL", "").strip()
    if not id_label:
        raise SystemExit("ID_LABEL is required; it correlates `up`, `exec`, and cleanup.")

    # RUN_SECRETS is a DECLARED, GitHub-masked workflow_call secret (never an
    # input, so never in the inputs-only validate job). Parse+validate here, in
    # the run step, with no echo/set -x around it; a bad KEY fails the step loudly.
    run_secrets = dcrun_run.parse_run_secrets(os.environ.get("RUN_SECRETS", ""))

    caller_config = dcrun_run.load_caller_config(workspace, config.config_file)
    override = dcrun_run.synthesize_override_config(config, caller_config)

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    state_dir = dcrun_run.state_dir(runner_temp)
    state_dir.mkdir(parents=True, exist_ok=True)
    # The `up` override config carries NO secrets in remoteEnv (that would leak
    # them into the persisted devcontainer.metadata label).
    config_path = state_dir / "devcontainer.json"
    config_path.write_text(json.dumps(override, indent=2) + "\n", encoding="utf-8")

    secrets_file: Path | None = None
    exec_config_path = config_path
    if run_secrets:
        secrets_path, exec_path = dcrun_run.secret_file_paths(runner_temp)
        # up --secrets-file shape: {"KEY": "VALUE", ...}, injected into the hooks.
        dcrun_run.write_secret_file(secrets_path, run_secrets)
        secrets_file = secrets_path
        # exec override-config: base + secrets in remoteEnv, reaching the command
        # via a transient `docker exec -e` (no persisted label). 0600, cleaned up.
        exec_override = dcrun_run.build_exec_override_config(override, run_secrets)
        dcrun_run.write_secret_file(exec_path, exec_override)
        exec_config_path = exec_path

    resolved_image = override["image"]
    _pull(resolved_image)

    up_result = _up(config, workspace, config_path, id_label, secrets_file)
    _emit_outputs(up_result)
    outcome = up_result.get("outcome")
    if outcome != "success":
        message = (
            up_result.get("message")
            or up_result.get("description")
            or "devcontainer up reported a non-success outcome."
        )
        raise SystemExit(f"devcontainer up failed ({outcome}): {message}")

    return _exec(config, workspace, exec_config_path, id_label)


def _pull(image: str) -> None:
    print(f"Pulling image {image} (fail-fast before container setup)...", flush=True)
    completed = subprocess.run(["docker", "pull", image])  # noqa: PLW1510
    if completed.returncode != 0:
        raise SystemExit(
            f"Failed to pull image {image!r}. Verify the reference, the runner architecture "
            "matches a manifest entry, and (for a private image) that docker-login-enabled "
            "and docker-password / the ghcr.io github.token fallback are set."
        )


def _up(
    config: dcrun.Config,
    workspace: Path,
    config_path: Path,
    id_label: str,
    secrets_file: Path | None,
) -> dict:
    argv = dcrun_run.build_up_argv(config, workspace, config_path, id_label, secrets_file)
    # The echoed argv carries only the --secrets-file PATH, never a secret value.
    print("+ " + " ".join(shlex.quote(part) for part in argv), flush=True)
    completed = subprocess.run(argv, stdout=subprocess.PIPE, text=True)  # noqa: PLW1510
    sys.stdout.write(completed.stdout)
    sys.stdout.flush()
    if completed.returncode != 0 and not completed.stdout.strip():
        raise SystemExit(
            f"devcontainer up exited {completed.returncode} without a JSON result; cannot continue."
        )
    return dcrun_run.parse_up_result(completed.stdout)


def _exec(config: dcrun.Config, workspace: Path, config_path: Path, id_label: str) -> int:
    argv = dcrun_run.build_exec_argv(config, workspace, config_path, id_label)
    print("+ " + " ".join(shlex.quote(part) for part in argv), flush=True)
    completed = subprocess.run(argv)  # noqa: PLW1510
    return completed.returncode


def _emit_outputs(result: dict) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    container_id = str(result.get("containerId") or "")
    remote_user = str(result.get("remoteUser") or "")
    with open(output_file, "a", encoding="utf-8") as handle:
        handle.write(f"container-id={container_id}\n")
        handle.write(f"remote-user={remote_user}\n")


if __name__ == "__main__":
    sys.exit(main())
