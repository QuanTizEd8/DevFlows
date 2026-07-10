"""A small, ruff-clean and type-correct module used by python-lint scenarios."""

from __future__ import annotations


def add(first: int, second: int) -> int:
    """Return the sum of two integers."""
    return first + second


def greet(name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"
