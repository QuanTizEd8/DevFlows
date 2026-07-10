from __future__ import annotations

import re
from dataclasses import dataclass

_USES_LINE = re.compile(r"^(?P<indent>\s*(?:- )?)uses:\s*(?P<ref>\S+@[0-9a-fA-F]{7,40})\s*$")


@dataclass(frozen=True)
class ActionPin:
    """A SHA-pinned third-party action and the human-readable version it maps to."""

    action: str
    sha: str
    version: str

    @property
    def ref(self) -> str:
        return f"{self.action}@{self.sha}"


# Single source of truth for every third-party action pin the generator emits or
# that appears in the source workflows. Both publish.py and scenarios.py consume
# this registry so the SHAs are defined once. Dependency-update tooling can target
# this table, and generated YAML carries the version as a trailing comment.
ACTION_PINS: dict[str, ActionPin] = {
    "checkout": ActionPin(
        "actions/checkout",
        "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "v7.0.0",
    ),
    "download-artifact": ActionPin(
        "actions/download-artifact",
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "v8.0.1",
    ),
    "upload-artifact": ActionPin(
        "actions/upload-artifact",
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
    "docker-login": ActionPin(
        "docker/login-action",
        "af1e73f918a031802d376d3c8bbc3fe56130a9b0",
        "v4.4.0",
    ),
    "setup-buildx": ActionPin(
        "docker/setup-buildx-action",
        "bb05f3f5519dd87d3ba754cc423b652a5edd6d2c",
        "v4.2.0",
    ),
    "cache": ActionPin(
        "actions/cache",
        "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        "v6.1.0",
    ),
    "devcontainers-ci": ActionPin(
        "devcontainers/ci",
        "513af61f4de4f75d37e4438f184ba4358f0fc1ca",
        "v0.3.1900000450",
    ),
}

PINS_BY_REF: dict[str, ActionPin] = {pin.ref: pin for pin in ACTION_PINS.values()}


def pin(name: str) -> ActionPin:
    return ACTION_PINS[name]


def ref(name: str) -> str:
    return ACTION_PINS[name].ref


def annotate_pins(text: str) -> str:
    """Append a `# <version>` comment to every `uses: <action>@<sha>` line.

    PyYAML strips comments, so version annotations are re-applied to the dumped
    text. Consumers audit these pins, and the comment restores the version that
    the bare SHA hides.
    """
    lines = text.splitlines()
    annotated: list[str] = []
    for line in lines:
        match = _USES_LINE.match(line)
        if match:
            action_pin = PINS_BY_REF.get(match.group("ref"))
            if action_pin is not None:
                line = f"{line.rstrip()}  # {action_pin.version}"
        annotated.append(line)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(annotated) + trailing
