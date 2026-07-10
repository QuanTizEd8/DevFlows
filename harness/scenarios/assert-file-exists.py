from __future__ import annotations

import glob
import os
from pathlib import Path

path = os.environ["ASSERT_PATH"]
# When ASSERT_GLOB is set the path is a shell glob pattern that must match at
# least one file (the file-glob-exists assertion). This exists because some
# producers emit non-deterministic filenames -- e.g. auditwheel stamps every
# compatibility tag it can satisfy onto a repaired wheel, so the exact wheel name
# varies -- and an exact file-exists assertion would be inherently brittle.
if os.environ.get("ASSERT_GLOB"):
    matches = [match for match in glob.glob(path, recursive=True) if Path(match).is_file()]
    if not matches:
        raise SystemExit(f"Expected at least one file matching glob: {path}")
elif not Path(path).is_file():
    raise SystemExit(f"Expected file to exist: {path}")
