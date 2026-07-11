"""Remove the devcontainer this run started (always() cleanup step).

There is no `devcontainer down`, so cleanup is by Docker: list every container
carrying this run's id-label and `docker rm -f` each one. Runs even when `up` or
the caller command failed (the workflow gates it with if: always()), so a
container left behind by a failed `up` is still removed. Container-written files
persist on the host bind mount, so the artifact-upload channel that runs after
this still sees them. Tolerant of "none found" and of a container already gone.
"""

from __future__ import annotations

import os
import subprocess
import sys

import dcrun


def main() -> int:
    if not _truthy(os.environ.get("REMOVE_CONTAINER", "")):
        print("remove-container is false; leaving the container in place.")
        return 0

    id_label = os.environ.get("ID_LABEL", "").strip()
    if not id_label:
        print("No id-label provided; nothing to clean up.")
        return 0

    completed = subprocess.run(  # noqa: PLW1510
        dcrun.build_cleanup_ids_command(id_label),
        stdout=subprocess.PIPE,
        text=True,
    )
    container_ids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not container_ids:
        print(f"No containers matched label {id_label!r}; nothing to remove.")
        return 0

    for container_id in container_ids:
        removed = subprocess.run(["docker", "rm", "-f", container_id])  # noqa: PLW1510
        if removed.returncode == 0:
            print(f"Removed container {container_id}.")
        else:
            print(f"Warning: could not remove container {container_id} (already gone?).")
    return 0


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    sys.exit(main())
