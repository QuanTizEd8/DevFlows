from __future__ import annotations

import json
import os
from pathlib import Path

files = json.loads(os.environ["DEVFLOWS_SETUP_FILES"])
for item in files:
    path = Path(item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(item.get("content", "")), encoding="utf-8")
