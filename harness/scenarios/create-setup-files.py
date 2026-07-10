from __future__ import annotations

import json
import os
from pathlib import Path

# Mirror the writeback/pandoc payload guards: setup files come from scenario
# metadata and are written into the checked-out workspace, so reject absolute
# paths, `..` traversal, and internal workflow paths, and confirm the resolved
# target stays inside the workspace before writing anything.
INTERNAL_PATH_NAMES = {".devflows-writeback", ".git"}


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


workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
files = json.loads(os.environ["DEVFLOWS_SETUP_FILES"])
for item in files:
    relative = _validated_relative_path(str(item["path"]))
    target = (workspace / relative).resolve()
    if workspace != target and workspace not in target.parents:
        raise SystemExit(f"path must stay inside the workspace: {item['path']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(item.get("content", "")), encoding="utf-8")
