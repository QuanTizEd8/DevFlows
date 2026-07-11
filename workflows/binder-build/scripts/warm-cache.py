"""Best-effort mybinder.org cache warm (warm-binder-cache job).

Triggers a BinderHub build of the repository so the first interactive launch is warm.
The job is continue-on-error at the JOB level, so mybinder downtime can never fail the
caller's pipeline. A connect success (curl exit 0 = already built) or a long-poll
timeout (curl exit 28 = build triggered) both count as success. Holds no credential and
binds no environment; the URL is assembled from the environment and passed to curl as
an argument list (never shell-interpolated).
"""

from __future__ import annotations

import os
import subprocess


def main() -> int:
    endpoint = os.environ["BINDER_CACHE_ENDPOINT"].strip().rstrip("/")
    provider = os.environ["BINDER_CACHE_PROVIDER"].strip()
    repository = os.environ["BINDER_CACHE_REPOSITORY"].strip()
    ref = os.environ["BINDER_CACHE_REF"].strip()
    url = f"{endpoint}/build/{provider}/{repository}/{ref}"
    print(f"Warming mybinder cache: {url}")

    result = subprocess.run(
        ["curl", "-fsSL", "--connect-timeout", "20", "--max-time", "600", url],
        check=False,
    )
    if result.returncode == 0:
        print("mybinder reports the image is already built.")
        return 0
    if result.returncode == 28:
        print("Triggered a new mybinder image build (long-poll timeout).")
        return 0
    print(
        f"::warning title=mybinder.org::Could not warm the cache (curl exit {result.returncode})."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
