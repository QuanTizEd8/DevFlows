"""Tiny importable module used by the DevFlows python-test scenarios."""

from __future__ import annotations

__all__ = ["greeting"]


def greeting() -> str:
    """Return a stable marker string the fixture tests assert on."""
    return "devflows python-test fixture ok"
