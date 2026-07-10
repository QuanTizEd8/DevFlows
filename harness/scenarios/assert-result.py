from __future__ import annotations

import os

# Assert the reusable-workflow call job succeeded. Negative-path scenarios do not
# use this script; they are validation-failure scenarios that run the target
# workflow's validate-inputs.py directly (see assert-validation-failure.py).
actual = os.environ["ACTUAL_RESULT"]
if actual != "success":
    raise SystemExit(f"Expected scenario job result 'success', got {actual!r}.")
