"""Start a prebuilt devcontainer and run the caller's command inside it.

Modelled on paper-openjournals' run-inara.py: every input arrives through
os.environ, the `devcontainer up`/`devcontainer exec` argv are assembled
programmatically (never a shell string), and subprocess.run is called without a
shell. The flow is:

  1. Resolve the override config (minimal {"image": ref} or the caller's
     devcontainer.json merged with the image/remote-user overrides), written to
     RUNNER_TEMP so the checkout is never mutated.
  2. `docker pull` the resolved image first for a clean, fast failure when the
     ref is wrong or the registry credentials are missing (the pull otherwise
     rides `docker run` auto-pull deep inside `up`).
  3. `devcontainer up --override-config ... --id-label ... --log-format json`
     against the workspace bind mount (no rebuild), parse the JSON result, emit
     container-id / remote-user outputs, and fail loudly on outcome: error.
  4. `devcontainer exec ... -- <run-shell> -c <run-command>` and exit with the
     command's own exit code (faithful propagation: a nonzero command fails the
     step, so a misconfigured call can never silently pass).

Cleanup (docker rm) is a separate always() step, so a container left behind by a
failed `up` is still removed.
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


def main() -> int:
    config = dcrun.parse_and_validate(os.environ, require_workspace=True)
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    id_label = os.environ.get("ID_LABEL", "").strip()
    if not id_label:
        raise SystemExit("ID_LABEL is required; it correlates `up`, `exec`, and cleanup.")

    caller_config = dcrun.load_caller_config(workspace, config.config_file)
    override = dcrun.synthesize_override_config(config, caller_config)

    runner_temp = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    config_dir = runner_temp / "devflows-devcontainer-run"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "devcontainer.json"
    config_path.write_text(json.dumps(override, indent=2) + "\n", encoding="utf-8")

    resolved_image = override["image"]
    _pull(resolved_image)

    up_result = _up(config, workspace, config_path, id_label)
    _emit_outputs(up_result)
    outcome = up_result.get("outcome")
    if outcome != "success":
        message = (
            up_result.get("message")
            or up_result.get("description")
            or "devcontainer up reported a non-success outcome."
        )
        raise SystemExit(f"devcontainer up failed ({outcome}): {message}")

    return _exec(config, workspace, config_path, id_label)


def _pull(image: str) -> None:
    print(f"Pulling image {image} (fail-fast before container setup)...", flush=True)
    completed = subprocess.run(["docker", "pull", image])  # noqa: PLW1510
    if completed.returncode != 0:
        raise SystemExit(
            f"Failed to pull image {image!r}. Verify the reference, the runner architecture "
            "matches a manifest entry, and (for a private image) that docker-login-enabled "
            "and docker-password / the ghcr.io github.token fallback are set."
        )


def _up(config: dcrun.Config, workspace: Path, config_path: Path, id_label: str) -> dict:
    argv = dcrun.build_up_argv(config, workspace, config_path, id_label)
    print("+ " + " ".join(shlex.quote(part) for part in argv), flush=True)
    completed = subprocess.run(argv, stdout=subprocess.PIPE, text=True)  # noqa: PLW1510
    sys.stdout.write(completed.stdout)
    sys.stdout.flush()
    if completed.returncode != 0 and not completed.stdout.strip():
        raise SystemExit(
            f"devcontainer up exited {completed.returncode} without a JSON result; cannot continue."
        )
    return dcrun.parse_up_result(completed.stdout)


def _exec(config: dcrun.Config, workspace: Path, config_path: Path, id_label: str) -> int:
    argv = dcrun.build_exec_argv(config, workspace, config_path, id_label)
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
