from __future__ import annotations

import re
from dataclasses import dataclass

_USES_LINE = re.compile(r"^(?P<indent>\s*(?:- )?)uses:\s*(?P<ref>\S+@[0-9a-fA-F]{7,40})\s*$")
# A mapping value that opens a YAML block scalar (`key: |`, `key: >-`, ...). Its
# content is literal text — including any inlined heredoc script body — and must
# never be treated as workflow structure to annotate.
_BLOCK_SCALAR_OPENER = re.compile(r":\s*[|>][+-]?[0-9]*\s*$")
_LINE_PREFIX = re.compile(r"^(?P<indent>\s*)(?P<dash>- )?")


def _key_column(line: str) -> int:
    """Column at which a mapping key starts, accounting for a `- ` list marker."""
    match = _LINE_PREFIX.match(line)
    assert match is not None
    return len(match.group("indent")) + (2 if match.group("dash") else 0)


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
    # Python toolchain (python-* and docs-build workflows). setup-uv, setup-python,
    # setup-micromamba, and setup-pixi are generic across the Python workflow family;
    # cibuildwheel and rattler-build-action are python-build-specific but registered
    # here so the generator annotates their version comments in the dumped output and
    # the adapter contract test (test_contract.py) verifies their emitted with: keys
    # on pin bumps.
    "cibuildwheel": ActionPin(
        "pypa/cibuildwheel",
        "294735312765b09d24a2fbec22660ce817587d55",
        "v4.1.0",
    ),
    "rattler-build": ActionPin(
        "prefix-dev/rattler-build-action",
        "1ca5f45832f419a46d1326ccc5861d7e14d67c44",
        "v0.2.39",
    ),
    "setup-micromamba": ActionPin(
        "mamba-org/setup-micromamba",
        "d7c9bd84e824b79d2af72a2d4196c7f4300d3476",
        "v3.0.0",
    ),
    "setup-pixi": ActionPin(
        "prefix-dev/setup-pixi",
        "a09b6247153796b190642a2b53fac4241043cf6f",
        "v0.10.0",
    ),
    "setup-python": ActionPin(
        "actions/setup-python",
        "ece7cb06caefa5fff74198d8649806c4678c61a1",
        "v6.3.0",
    ),
    "setup-uv": ActionPin(
        "astral-sh/setup-uv",
        "11f9893b081a58869d3b5fccaea48c9e9e46f990",
        "v8.3.2",
    ),
    # GitHub Pages chain (docs-build packages the artifact; deploy-pages
    # configures, packages, and deploys). Pinned together so the three actions
    # stay on a coherent generation: upload-pages-artifact v5 adds the
    # include-hidden-files input that v4 lacked (v4 always excluded dotfiles).
    "upload-pages-artifact": ActionPin(
        "actions/upload-pages-artifact",
        "fc324d3547104276b827a68afc52ff2a11cc49c9",
        "v5.0.0",
    ),
    "configure-pages": ActionPin(
        "actions/configure-pages",
        "45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "v6.0.0",
    ),
    "deploy-pages": ActionPin(
        "actions/deploy-pages",
        "cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
        "v5.0.0",
    ),
    # Python distribution publishing (pypi-publish). gh-action-pypi-publish is a
    # composite action that runs an inner Docker container for the twine upload;
    # pypi-publish invokes it OIDC-only (no user/password). The annotated tag
    # v1.14.0 (6733eb7d741f0b11ec6a39b58540dab7590f9b7d) dereferences to this
    # commit. Registered here so the generator annotates its version comment and
    # the adapter contract test verifies the emitted with: keys on pin bumps.
    "gh-action-pypi-publish": ActionPin(
        "pypa/gh-action-pypi-publish",
        "cef221092ed1bacb1cc03d23a2d87d1d172e277b",
        "v1.14.0",
    ),
}

PINS_BY_REF: dict[str, ActionPin] = {pin.ref: pin for pin in ACTION_PINS.values()}


def pin(name: str) -> ActionPin:
    return ACTION_PINS[name]


def ref(name: str) -> str:
    return ACTION_PINS[name].ref


def annotate_pins(text: str) -> str:
    """Append a `# <version>` comment to every step `uses: <action>@<sha>` line.

    PyYAML strips comments, so version annotations are re-applied to the dumped
    text. Consumers audit these pins, and the comment restores the version that
    the bare SHA hides.

    The pass is block-scalar aware: lines inside a `run: |` (or any block scalar)
    are literal content — for the generator that includes whole inlined heredoc
    script bodies — and are copied through untouched. Annotating them would
    corrupt an inlined script that happens to contain the literal
    ``uses: <action>@<sha>`` (reproduced with such a script).
    """
    lines = text.splitlines()
    annotated: list[str] = []
    # Key column of the currently-open block scalar, or None outside one.
    scalar_key_column: int | None = None
    for line in lines:
        if scalar_key_column is not None:
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() == "" or indent > scalar_key_column:
                annotated.append(line)  # literal block-scalar content
                continue
            scalar_key_column = None  # dedented out of the scalar; process normally
        match = _USES_LINE.match(line)
        if match:
            action_pin = PINS_BY_REF.get(match.group("ref"))
            if action_pin is not None:
                line = f"{line.rstrip()}  # {action_pin.version}"
        elif _BLOCK_SCALAR_OPENER.search(line):
            scalar_key_column = _key_column(line)
        annotated.append(line)
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(annotated) + trailing
