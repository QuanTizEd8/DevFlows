from __future__ import annotations

import os
import subprocess
import sys

# Run a workflow's input-validation script and assert it REJECTS the inputs.
#
# validation-failure scenarios do not call the reusable workflow. The generated
# job checks the repository out and points DEVFLOWS_VALIDATE_SCRIPT at
# workflows/<id>/scripts/validate-inputs.py, having already exported the env the
# workflow's own validate step would set (its inputs.* mapping, reconstructed
# from the scenario inputs and the workflow input defaults). Those input env
# vars are inherited by the subprocess below.
#
# The scenario is GREEN when the script exits nonzero (it rejected the inputs as
# designed). It is RED when the script exits 0 (the inputs were accepted
# unexpectedly) or when DEVFLOWS_FAILURE_MESSAGE_CONTAINS is set but absent from
# the captured output (a different rejection fired than the one under test).
script = os.environ["DEVFLOWS_VALIDATE_SCRIPT"]
expected_message = os.environ.get("DEVFLOWS_FAILURE_MESSAGE_CONTAINS", "")

result = subprocess.run(
    [sys.executable, script],
    capture_output=True,
    text=True,
)
output = result.stdout + result.stderr
# Surface the validator's own output so a failing scenario is debuggable.
sys.stdout.write(output)

if result.returncode == 0:
    raise SystemExit(
        f"Validation script {script!r} exited 0, but this scenario expects it to "
        "reject its inputs with a nonzero exit. The inputs were accepted "
        "unexpectedly; either the validation regressed or the scenario inputs no "
        "longer trip it."
    )

if expected_message and expected_message not in output:
    raise SystemExit(
        f"Validation script {script!r} failed as expected (exit {result.returncode}), "
        f"but its output did not contain the required message {expected_message!r}. "
        "A different validation path fired than the one under test.\n"
        f"--- captured output ---\n{output}"
    )

detail = f" Output contained {expected_message!r}." if expected_message else ""
print(f"Validation correctly rejected the inputs (exit {result.returncode}).{detail}")
