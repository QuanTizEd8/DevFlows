from __future__ import annotations


class DevflowsError(Exception):
    """A user-facing error.

    Raised for expected failure conditions (missing catalog root, invalid
    metadata, delimiter collisions, and similar). The CLI catches these and
    prints a single clear message instead of a traceback.
    """
