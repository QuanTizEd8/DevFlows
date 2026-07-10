"""Relabel staged packages to the final label (the real public-release event).

Runs ``anaconda move --from-label <upload-label> --to-label <promote-label>
<owner>/<spec>`` for each owner-qualified target. Targets come from the verify
job's promoted-specs output (already validated and owner-prefixed there), so this
job only executes the plan. The single token-bearing step of the promote job.
Imports the materialized sibling modules parsing / commands.
"""

from __future__ import annotations

import os
import subprocess
import sys

import commands
import parsing


def main() -> int:
    if not os.environ.get("ANACONDA_API_TOKEN", "").strip():
        raise SystemExit(
            "ANACONDA_API_TOKEN is empty; pass the anaconda-token secret "
            "(secrets: inherit) to promote on anaconda.org."
        )
    server_url = os.environ.get("PUBLISH_SERVER_URL", "")
    from_label = parsing.validate_label(os.environ["UPLOAD_LABEL"], field="upload-label")
    to_label = parsing.validate_label(os.environ["PROMOTE_LABEL"], field="promote-label")
    client_version = commands.resolve_client_version(os.environ.get("PUBLISH_CLIENT_VERSION", ""))

    targets = [
        line.strip() for line in os.environ.get("PROMOTED_SPECS", "").splitlines() if line.strip()
    ]
    if not targets:
        raise SystemExit("no promote targets were computed; nothing to relabel.")

    for target in targets:
        argv = commands.uvx_wrap(
            client_version,
            commands.build_move_argv(
                server_url=server_url, from_label=from_label, to_label=to_label, target=target
            ),
        )
        print(f"promoting {target}: {from_label} -> {to_label}", flush=True)
        _run(argv)
    print(f"promoted {len(targets)} spec(s) from {from_label} to {to_label}.")
    return 0


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, check=False)  # noqa: S603 - argv is fully constructed, no shell
    if result.returncode != 0:
        sys.stderr.write(f"command failed (exit {result.returncode}): {' '.join(argv)}\n")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
