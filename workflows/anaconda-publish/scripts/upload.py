"""Stage verified conda packages onto anaconda.org under the staging label.

The ONLY step in the upload job that carries ANACONDA_API_TOKEN. It re-verifies
every file against the caller-supplied manifest one more time (a TOCTOU guard),
then runs ``anaconda upload`` for each verified file via an argv built by the
materialized sibling modules (env + shlex, never a shell string). anaconda-client
reads the token from the inherited ANACONDA_API_TOKEN env, never a process arg.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import arguments
import commands
import digest
import parsing


def main() -> int:
    if not os.environ.get("ANACONDA_API_TOKEN", "").strip():
        raise SystemExit(
            "ANACONDA_API_TOKEN is empty; pass the anaconda-token secret "
            "(secrets: inherit) to upload to anaconda.org."
        )
    owner = parsing.validate_owner(os.environ["PUBLISH_OWNER"])
    server_url = os.environ.get("PUBLISH_SERVER_URL", "")
    label = parsing.validate_label(os.environ["UPLOAD_LABEL"], field="upload-label")
    mode = arguments.validate_existing_mode(os.environ.get("UPLOAD_EXISTING_MODE", "fail"))
    extra = arguments.parse_extra_arguments(
        os.environ.get("UPLOAD_ARGUMENTS", ""), field="upload-arguments"
    )
    client_version = commands.resolve_client_version(os.environ.get("PUBLISH_CLIENT_VERSION", ""))

    dist_path = Path(os.environ["PUBLISH_DIST_PATH"]).resolve()
    manifest = json.loads(os.environ["PUBLISH_DIST_MANIFEST"])
    try:
        verified = digest.verify_files_against_manifest(dist_path, manifest)
        digest.resolve_version(verified, expected=os.environ.get("PUBLISH_EXPECTED_VERSION", ""))
    except parsing.SpecError as error:
        raise SystemExit(f"re-verification failed before upload: {error}") from error

    for item in verified:
        argv = commands.uvx_wrap(
            client_version,
            commands.build_upload_argv(
                server_url=server_url,
                owner=owner,
                label=label,
                mode=mode,
                extra_arguments=extra,
                file_path=str(item.path),
            ),
        )
        print(f"uploading {item.name} -> {owner} (label {label})", flush=True)
        _run(argv)
    print(f"uploaded {len(verified)} file(s) to {owner} under label {label}.")
    return 0


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, check=False)  # noqa: S603 - argv is fully constructed, no shell
    if result.returncode != 0:
        sys.stderr.write(f"command failed (exit {result.returncode}): {' '.join(argv)}\n")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
