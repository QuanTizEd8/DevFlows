from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["ASSERT_PATH"])
text = os.environ["ASSERT_TEXT"]
if not path.is_file():
    raise SystemExit(f"Expected file to exist: {path}")
content = path.read_text(encoding="utf-8")
if text not in content:
    raise SystemExit(f"Expected {path} to contain {text!r}.")
