"""Destructive channel maintenance: remove versions/files from anaconda.org.

Runs ``anaconda remove --force <owner>/<spec>`` for each owner-qualified target
(``--force`` is anaconda-client's do-not-prompt flag, replacing the cm draft's
interactive prompt that hangs and dies in CI; the human gate is the type-the-name
maintain-confirm input plus the strict maintain environment's reviewers). Targets
come from the verify job's removed-specs output (validated and owner-prefixed
there). The single token-bearing step of the maintain job.

Imports the sibling ``specs.py`` (a ``${DEVFLOWS_SCRIPT_ROOT}/anaconda-publish/
specs.py`` comment in the step run body makes the sync step inline it).
"""

from __future__ import annotations

import os
import subprocess
import sys

import specs


def main() -> int:
    if not os.environ.get("ANACONDA_API_TOKEN", "").strip():
        raise SystemExit(
            "ANACONDA_API_TOKEN is empty; pass the anaconda-token secret "
            "(secrets: inherit) to remove packages from anaconda.org."
        )
    server_url = os.environ.get("PUBLISH_SERVER_URL", "")
    client_version = specs.resolve_client_version(os.environ.get("PUBLISH_CLIENT_VERSION", ""))

    targets = [
        line.strip() for line in os.environ.get("REMOVED_SPECS", "").splitlines() if line.strip()
    ]
    if not targets:
        raise SystemExit("no removal targets were computed; nothing to remove.")

    for target in targets:
        argv = specs.uvx_wrap(
            client_version, specs.build_remove_argv(server_url=server_url, target=target)
        )
        print(f"removing {target}", flush=True)
        _run(argv)
    print(f"removed {len(targets)} spec(s).")
    return 0


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, check=False)  # noqa: S603 - argv is fully constructed, no shell
    if result.returncode != 0:
        sys.stderr.write(f"command failed (exit {result.returncode}): {' '.join(argv)}\n")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
