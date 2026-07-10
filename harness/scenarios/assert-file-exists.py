from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["ASSERT_PATH"])
if not path.is_file():
    raise SystemExit(f"Expected file to exist: {path}")
