from __future__ import annotations

import os

actual = os.environ["ACTUAL_RESULT"]
if actual != "success":
    raise SystemExit(f"Expected scenario job to succeed, got {actual!r}.")
