from __future__ import annotations

import os

# Assert the reusable-workflow call job reached the expected conclusion. Success
# scenarios expect "success" (the default); expect-failure scenarios set
# EXPECTED_RESULT=failure so the assert job stays green only when the call failed
# as designed and turns red if it unexpectedly succeeded.
actual = os.environ["ACTUAL_RESULT"]
expected = os.environ.get("EXPECTED_RESULT", "success")
if actual != expected:
    raise SystemExit(f"Expected scenario job result {expected!r}, got {actual!r}.")
