from __future__ import annotations

import re

from devflows.actions import ACTION_PINS, PINS_BY_REF, annotate_pins, ref


def test_registry_refs_are_full_shas() -> None:
    for pin in ACTION_PINS.values():
        assert re.fullmatch(r"[0-9a-f]{40}", pin.sha), pin
        assert pin.version.startswith("v")
    # No two names collide on the same ref.
    assert len(PINS_BY_REF) == len(ACTION_PINS)


def test_annotate_pins_appends_version_comment() -> None:
    text = f"      - uses: {ref('checkout')}\n"
    annotated = annotate_pins(text)

    assert annotated == f"      - uses: {ref('checkout')}  # v7.0.0\n"


def test_annotate_pins_leaves_unknown_refs_untouched() -> None:
    text = "      - uses: some/action@0000000000000000000000000000000000000000\n"

    assert annotate_pins(text) == text


def test_annotate_pins_is_idempotent() -> None:
    once = annotate_pins(f"    uses: {ref('upload-artifact')}\n")
    twice = annotate_pins(once)

    assert once == twice
