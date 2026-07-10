"""Lean TOCTOU re-verify inside the credentialed zenodo-deposit job.

Recomputes sha256+size for every caller-manifest entry and atomically compares
them against the manifest immediately before the token-bearing deposit step, so an
artifact swapped between the prepare download and the deposit download cannot ride
the credentialed upload. It does NOT re-inline prepare's glob/metadata logic: when
no publish-dist-manifest is supplied there is nothing to re-verify and it is a
no-op (assets upload as-is, matching the optional-manifest contract). Imports only
dist_manifest and hashing.
"""

from __future__ import annotations

import os
from pathlib import Path

import dist_manifest
import hashing


def main() -> int:
    raw = os.environ.get("PUBLISH_DIST_MANIFEST", "").strip()
    if not raw:
        print("no publish-dist-manifest supplied; nothing to re-verify before upload.")
        return 0
    source = Path(
        os.environ.get("ZENODO_ASSET_SOURCE_PATH", "").strip()
        or os.environ.get("ARTIFACT_DOWNLOAD_PATH", "").strip()
        or "."
    ).resolve()
    try:
        entries = dist_manifest.manifest_entries(dist_manifest.parse_manifest(raw))
        verified = hashing.verify_entries(source, entries)
    except (dist_manifest.ManifestError, hashing.DigestError) as error:
        raise SystemExit(f"re-verification failed before Zenodo upload: {error}") from error
    print(f"re-verified {len(verified)} file(s) against publish-dist-manifest before upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
