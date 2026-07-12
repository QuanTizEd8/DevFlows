from __future__ import annotations

import os

name = os.environ["ASSERT_NAME"]
expected = os.environ["EXPECTED"]
actual = os.environ["ACTUAL"]
if actual != expected:
    raise SystemExit(f"{name}: expected {expected!r}, got {actual!r}.")
