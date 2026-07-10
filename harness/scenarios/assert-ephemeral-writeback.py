from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

fixture_path = Path(os.environ["DEVFLOWS_FIXTURE_PATH"])
assertions = json.loads(os.environ["DEVFLOWS_ASSERTIONS"])

for assertion in assertions:
    assertion_type = assertion["type"]
    if assertion_type == "branch-file-contains":
        path = fixture_path / assertion["path"]
        if not path.is_file():
            raise SystemExit(f"Expected file to exist: {path}")
        text = str(assertion["text"])
        content = path.read_text(encoding="utf-8")
        if text not in content:
            raise SystemExit(f"Expected {path} to contain {text!r}.")
    elif assertion_type == "branch-file-missing":
        path = fixture_path / assertion["path"]
        if path.exists():
            raise SystemExit(f"Expected path to be absent: {path}")
    elif assertion_type == "latest-commit-message-equals":
        actual = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected = str(assertion["value"])
        if actual != expected:
            raise SystemExit(f"Expected latest commit message {expected!r}, got {actual!r}.")
    else:
        raise SystemExit(f"Unsupported branch assertion type: {assertion_type}")
