"""Relabel staged packages to the final label (the real public-release event).

Runs ``anaconda move`` per owner-qualified target from the verify job's
promoted-specs output (already validated and owner-prefixed there). The single
token-bearing step of the promote job. Imports only commands; labels are
re-validated in-module to avoid inlining the whole parsing module here.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import commands

# Mirror of parsing._LABEL_RE (kept in sync by test_promote_label_regex_matches_parsing).
# The labels are already validated in the validate job; this is a defense-in-depth
# re-check on the credentialed job without pulling in all of parsing.py.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_label(value: str, *, field: str) -> str:
    value = value.strip()
    if not value or not _LABEL_RE.match(value):
        raise SystemExit(f"{field} must be a safe channel label; got {value!r}.")
    return value


def main() -> int:
    if not os.environ.get("ANACONDA_API_TOKEN", "").strip():
        raise SystemExit(
            "ANACONDA_API_TOKEN is empty; pass the anaconda-token secret "
            "(secrets: inherit) to promote on anaconda.org."
        )
    server_url = os.environ.get("PUBLISH_SERVER_URL", "")
    from_label = _validate_label(os.environ["UPLOAD_LABEL"], field="upload-label")
    to_label = _validate_label(os.environ["PROMOTE_LABEL"], field="promote-label")
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
