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


def test_annotate_pins_ignores_uses_inside_block_scalar() -> None:
    # A `uses: <pinned-ref>` line living inside an inlined heredoc script body
    # (a `run: |` block scalar) is literal content, not workflow structure, and
    # must not be annotated — otherwise the materialized script is corrupted.
    text = (
        "      - name: Materialize\n"
        "        run: |\n"
        "          cat > script.py <<'EOF'\n"
        f"          # uses: {ref('checkout')}\n"
        "          print('hi')\n"
        "          EOF\n"
        "      - name: Real step\n"
        f"        uses: {ref('upload-artifact')}\n"
    )
    annotated = annotate_pins(text)

    # The script line is untouched (no version comment appended)...
    assert f"          # uses: {ref('checkout')}\n" in annotated
    assert "# uses:" in annotated and "checkout" in annotated
    assert "# v7.0.0" not in annotated
    # ...while a real step `uses:` outside the scalar is still annotated.
    assert f"        uses: {ref('upload-artifact')}  # v7.0.1\n" in annotated


def test_annotate_pins_resumes_after_block_scalar() -> None:
    text = (
        "        run: |\n"
        "          echo done\n"
        "      - name: After\n"
        f"        uses: {ref('checkout')}\n"
    )
    annotated = annotate_pins(text)

    assert f"        uses: {ref('checkout')}  # v7.0.0\n" in annotated
