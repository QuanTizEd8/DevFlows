#!/usr/bin/env python3
"""Force-move moving major tags (``<component>/vN``) after a release-please run.

Runs on a bare CI runner with the system ``python3`` (standard library only, so it
needs neither pixi nor the devflows package). It reads the full
release-please-action outputs object as JSON from ``RELEASE_PLEASE_OUTPUTS`` and,
for every released package whose major version is ``>= 1``, force-moves the
moving major tag ``<component>/v<major>`` onto that release's commit.

The automation is dormant by construction while the catalog is on ``0.x``: every
released major is ``0`` there, so ``compute_major_tag_moves`` returns nothing and
no tag is moved. It starts working the first time a workflow is released at
``1.0.0`` — no new machinery is needed on 1.0 day.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def compute_major_tag_moves(outputs: dict) -> list[tuple[str, str]]:
    """Return ``(major_tag, commit_sha)`` pairs to force-move for a release run.

    Pure function over the release-please-action outputs object (all values are
    strings, as GitHub Actions delivers them). Packages released below ``1.0.0``
    are skipped so the automation stays dormant during ``0.x``.
    """
    if str(outputs.get("releases_created", "")).strip().lower() != "true":
        return []
    try:
        paths = json.loads(outputs.get("paths_released") or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    moves: list[tuple[str, str]] = []
    for path in paths:
        tag_name = str(outputs.get(f"{path}--tag_name") or "").strip()
        sha = str(outputs.get(f"{path}--sha") or "").strip()
        major_raw = str(outputs.get(f"{path}--major") or "").strip()
        if not tag_name or not sha or not major_raw:
            continue
        try:
            major = int(major_raw)
        except ValueError:
            continue
        if major < 1:
            # Dormant during 0.x: no moving major tag is published pre-1.0.
            continue
        # Release tags are "<component>/vX.Y.Z"; the moving major tag is
        # "<component>/v<major>".
        component = tag_name.rsplit("/", 1)[0]
        if not component:
            continue
        moves.append((f"{component}/v{major}", sha))
    return moves


def _move_tag(tag: str, sha: str) -> None:
    subprocess.run(["git", "tag", "--force", tag, sha], check=True)
    subprocess.run(["git", "push", "--force", "origin", f"refs/tags/{tag}"], check=True)


def main() -> int:
    raw = os.environ.get("RELEASE_PLEASE_OUTPUTS", "").strip()
    if not raw:
        print("no RELEASE_PLEASE_OUTPUTS provided; nothing to do.")
        return 0
    try:
        outputs = json.loads(raw)
    except json.JSONDecodeError as error:
        print(f"could not parse RELEASE_PLEASE_OUTPUTS: {error}", file=sys.stderr)
        return 1
    moves = compute_major_tag_moves(outputs)
    if not moves:
        print("no released package has major >= 1; moving-tag automation is dormant.")
        return 0
    for tag, sha in moves:
        print(f"force-moving {tag} -> {sha}")
        _move_tag(tag, sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
