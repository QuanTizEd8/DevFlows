from __future__ import annotations

from devflows_test_fixture import greeting


def test_greeting_marker() -> None:
    assert greeting() == "devflows python-test fixture ok"
