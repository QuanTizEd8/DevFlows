"""Tokenless TOCTOU re-verify immediately before the credentialed upload step.

Re-hashes the files-to-upload against the caller-supplied dist manifest (the same
bidirectional sha256/size check the verify job ran) so an artifact swapped between
the verify and upload downloads cannot ride the credentialed upload. Runs before
the single ANACONDA_API_TOKEN-bearing step. Imports only digest (plus its
manifest/parsing helpers) -- no plan/argv machinery.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import digest
import parsing


def main() -> int:
    dist_path = Path(os.environ["PUBLISH_DIST_PATH"]).resolve()
    try:
        manifest = json.loads(os.environ["PUBLISH_DIST_MANIFEST"])
    except json.JSONDecodeError as error:
        raise SystemExit(f"publish-dist-manifest is not valid JSON: {error}.") from error
    try:
        verified = digest.verify_files_against_manifest(dist_path, manifest)
        digest.resolve_version(verified, expected=os.environ.get("PUBLISH_EXPECTED_VERSION", ""))
    except parsing.SpecError as error:
        raise SystemExit(f"re-verification failed before upload: {error}") from error
    print(f"re-verified {len(verified)} file(s) against the dist manifest before upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
