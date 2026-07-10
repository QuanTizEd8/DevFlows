from __future__ import annotations

import base64
import json
import os
from pathlib import Path

# Mirror the writeback/pandoc payload guards: setup files come from scenario
# metadata and are written into the checked-out workspace, so reject absolute
# paths, `..` traversal, and internal workflow paths, and confirm the resolved
# target stays inside the workspace before writing anything. The same guards
# apply to a `source-path` copied out of the checkout.
INTERNAL_PATH_NAMES = {".devflows-writeback", ".git"}
# Exactly one payload source per file, matching the schema's oneOf.
PAYLOAD_KEYS = ("content", "source-path", "content-base64")


def _validated_relative_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise SystemExit(f"path must be relative: {raw_path}")
    if str(path) in {"", "."}:
        raise SystemExit("path must not be empty or '.'.")
    if ".." in path.parts:
        raise SystemExit(f"path must not contain '..': {raw_path}")
    if any(part in INTERNAL_PATH_NAMES for part in path.parts):
        raise SystemExit(f"path must not include internal workflow paths: {raw_path}")
    return path


def _resolved_inside_workspace(workspace: Path, relative: Path, raw_path: str) -> Path:
    target = (workspace / relative).resolve()
    if workspace != target and workspace not in target.parents:
        raise SystemExit(f"path must stay inside the workspace: {raw_path}")
    return target


workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
files = json.loads(os.environ["DEVFLOWS_SETUP_FILES"])
for item in files:
    raw_target = str(item["path"])
    relative = _validated_relative_path(raw_target)
    target = _resolved_inside_workspace(workspace, relative, raw_target)
    present = [key for key in PAYLOAD_KEYS if key in item]
    if len(present) != 1:
        raise SystemExit(
            f"file {raw_target!r} must set exactly one of {', '.join(PAYLOAD_KEYS)}; got {present}"
        )
    mode = present[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "content":
        target.write_text(str(item["content"]), encoding="utf-8")
    elif mode == "content-base64":
        target.write_bytes(base64.b64decode(str(item["content-base64"])))
    else:  # source-path: copy a (possibly binary) file out of the checkout.
        raw_source = str(item["source-path"])
        source_relative = _validated_relative_path(raw_source)
        source = _resolved_inside_workspace(workspace, source_relative, raw_source)
        if not source.is_file():
            raise SystemExit(f"source-path is not a file in the workspace: {raw_source}")
        target.write_bytes(source.read_bytes())
