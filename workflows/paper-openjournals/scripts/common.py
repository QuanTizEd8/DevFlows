"""Shared validation and flavor-table helpers for paper-openjournals.

Both validate-inputs.py (the fail-fast validate job) and run-inara.py (the build
job) parse and validate the caller inputs through parse_and_validate() so the two
jobs agree exactly on what is legal. Every input reaches this module only through
os.environ (mapped from inputs.* by the workflow), never interpolated into a
shell string, which is the whole point of the pandoc-modelled rewrite: the
draft workflow interpolated inputs straight into run: blocks.

DevFlows owns the flavor -> (inara argv, produced outputs) table below, so a
caller selects flavor NAMES but never supplies inara's -o/-p/-r itself. That is
why paper-arguments is an allowlist of only the cosmetic flags (-v, -l, -m).
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Syntactic image-reference grammar, identical to pandoc's run-pandoc.py: a
# well-formed [registry/]name[:tag][@digest] reference. Validation is syntactic
# only; the caller is trusted to supply an image they trust (it runs with the
# workspace mounted).
_ALNUM = r"[a-z0-9]+"
_SEPARATOR = r"(?:[._]|__|[-]+)"
_PATH_COMPONENT = rf"{_ALNUM}(?:{_SEPARATOR}{_ALNUM})*"
_NAME = rf"{_PATH_COMPONENT}(?:/{_PATH_COMPONENT})*"
_DOMAIN_COMPONENT = r"(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])"
_DOMAIN = rf"{_DOMAIN_COMPONENT}(?:\.{_DOMAIN_COMPONENT})*(?::[0-9]+)?"
_TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
_DIGEST = r"[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9A-Fa-f]{32,}"
_IMAGE_REFERENCE = re.compile(rf"^(?:{_DOMAIN}/)?{_NAME}(?::{_TAG})?(?:@{_DIGEST})?$")

# paper-journal enum -> the JOURNAL env value inara resolves against its
# resources/<JOURNAL>/defaults.yaml (verified against the upstream resources/
# listing at v1.3.1: joss, jose, resciencec).
JOURNALS: dict[str, str] = {
    "joss": "joss",
    "jose": "jose",
    "rescience-c": "resciencec",
}


@dataclass(frozen=True)
class Output:
    """One artifact a flavor produces, relative to the paper source directory."""

    name: str
    required: bool


@dataclass(frozen=True)
class Flavor:
    """A v1 output flavor: the inara argv it emits and the outputs it produces."""

    argv: tuple[str, ...]
    outputs: tuple[Output, ...]


# The DevFlows-owned flavor table. argv holds ONLY the inara output-selection
# flags (-o/-p); the caller never supplies these. outputs are the fixed
# filenames inara writes next to the source (verified against
# data/defaults/*.yaml at v1.3.1). draft-pdf and final-pdf both write paper.pdf,
# which is exactly why each flavor is collected into its own subdirectory.
FLAVORS: dict[str, Flavor] = {
    "draft-pdf": Flavor(("-o", "pdf"), (Output("paper.pdf", True),)),
    "final-pdf": Flavor(("-p", "-o", "pdf"), (Output("paper.pdf", True),)),
    "jats": Flavor(("-o", "jats"), (Output("jats", True),)),
    "crossref": Flavor(("-o", "crossref"), (Output("paper.crossref", True),)),
    "cff": Flavor(("-o", "cff"), (Output("CITATION.cff", True),)),
    "html": Flavor(
        ("-o", "html"),
        (Output("paper.html", True), Output("media", False)),
    ),
    "preprint": Flavor(("-o", "preprint"), (Output("paper.preprint.tex", True),)),
    "tex": Flavor(("-o", "tex"), (Output("paper.tex", True),)),
    "docx": Flavor(("-o", "docx"), (Output("paper.docx", True),)),
    "context-pdf": Flavor(("-o", "contextpdf"), (Output("paper.context.pdf", True),)),
}

# inara's getopt string is 'lo:m:prv'. DevFlows owns output selection, so -o, -p
# and -r are rejected in paper-arguments; the caller may add only the cosmetic
# flags. -m takes a value (an article-info YAML file), the others take none.
_OWNED_FLAGS = {"-o", "-p", "-r"}
_ALLOWED_BARE_FLAGS = {"-v", "-l"}
_ALLOWED_VALUE_FLAGS = {"-m"}


@dataclass(frozen=True)
class Config:
    """A fully validated invocation, shared by the validate and build jobs."""

    journal_env: str
    source_relative: str
    output_relative: str
    image: str
    flavors: tuple[str, ...]
    extra_arguments: tuple[str, ...]


def parse_and_validate(env: Mapping[str, str], *, require_source_exists: bool) -> Config:
    """Validate every input and return the resolved Config.

    require_source_exists is False in the validate job (no checkout, so the
    source file is not present) and True in the build job (checked out).
    """
    workspace = Path(env["GITHUB_WORKSPACE"]).resolve()

    journal_env = _validate_journal(env.get("PAPER_JOURNAL", ""))
    image = _validate_image(env.get("PAPER_IMAGE", ""))
    flavors = _validate_flavors(env.get("PAPER_FLAVORS", ""))
    extra_arguments = parse_extra_arguments(env.get("PAPER_ARGUMENTS", ""))

    source_relative = _validate_source_path(
        env.get("PAPER_SOURCE_PATH", ""),
        workspace,
        require_exists=require_source_exists,
    )
    output_relative = _validate_output_directory(
        env.get("PAPER_OUTPUT_DIRECTORY", ""),
        workspace,
    )

    return Config(
        journal_env=journal_env,
        source_relative=source_relative,
        output_relative=output_relative,
        image=image,
        flavors=tuple(flavors),
        extra_arguments=tuple(extra_arguments),
    )


def _validate_journal(value: str) -> str:
    journal = value.strip()
    if journal not in JOURNALS:
        allowed = ", ".join(JOURNALS)
        raise SystemExit(f"paper-journal must be one of {allowed}; got {value!r}.")
    return JOURNALS[journal]


def _validate_image(value: str) -> str:
    image = value.strip()
    if not _IMAGE_REFERENCE.match(image):
        raise SystemExit(
            f"paper-image is not a valid image reference: {value!r}. "
            "Expected [registry/]name[:tag][@digest]."
        )
    return image


def _validate_flavors(value: str) -> list[str]:
    names = [line.strip() for line in value.splitlines() if line.strip()]
    if not names:
        raise SystemExit("paper-flavors must list at least one paper flavor; got nothing to do.")
    resolved: list[str] = []
    for name in names:
        if name not in FLAVORS:
            allowed = ", ".join(FLAVORS)
            raise SystemExit(f"unknown paper flavor: {name}. Valid flavors are: {allowed}.")
        if name not in resolved:
            resolved.append(name)
    return resolved


def _validate_source_path(value: str, workspace: Path, *, require_exists: bool) -> str:
    if not value.strip():
        raise SystemExit("paper-source-path is required; it must not be empty.")
    relative = _workspace_relative(value, workspace, "paper-source-path")
    if require_exists:
        resolved = (workspace / relative).resolve()
        if not resolved.is_file():
            raise SystemExit(f"paper-source-path does not exist or is not a regular file: {value}")
    return relative


def _validate_output_directory(value: str, workspace: Path) -> str:
    if not value.strip():
        raise SystemExit("paper-output-directory is required; it must not be empty.")
    return _workspace_relative(value, workspace, "paper-output-directory")


def _workspace_relative(value: str, workspace: Path, field: str) -> str:
    """Return the workspace-relative POSIX path, rejecting escapes.

    Rejects absolute paths and any '..' component before resolving, then confirms
    the resolved path stays inside GITHUB_WORKSPACE.
    """
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise SystemExit(
            f"{field} must stay inside GITHUB_WORKSPACE (no absolute paths and no '..'): {value}"
        )
    resolved = (workspace / candidate).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise SystemExit(f"{field} must stay inside GITHUB_WORKSPACE: {value}")
    return resolved.relative_to(workspace).as_posix()


def parse_extra_arguments(raw: str) -> list[str]:
    """Shlex-split paper-arguments and enforce the strict allowlist.

    inara has only short flags (getopt 'lo:m:prv'), including clustered forms
    like -vl and attached values like -opdf, so this walks each option token
    character by character and rejects an owned flag (-o/-p/-r) in EVERY form as
    well as any bare positional (the source is owned by paper-source-path).
    """
    try:
        tokens = shlex.split(raw)
    except ValueError as error:
        raise SystemExit(f"Unable to parse paper-arguments: {error}") from error

    result: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--" or not token.startswith("-") or token == "-":
            raise SystemExit(
                "paper-arguments must not contain a bare positional argument "
                "(the paper source is controlled by paper-source-path): "
                f"{token!r}."
            )
        position = 1
        while position < len(token):
            flag = "-" + token[position]
            if flag in _OWNED_FLAGS:
                raise SystemExit(
                    f"paper-arguments must not contain {flag} "
                    "(output selection is controlled by paper-flavors)."
                )
            if flag in _ALLOWED_BARE_FLAGS:
                result.append(flag)
                position += 1
                continue
            if flag in _ALLOWED_VALUE_FLAGS:
                attached = token[position + 1 :]
                if attached:
                    value = attached
                else:
                    index += 1
                    if index >= len(tokens):
                        raise SystemExit(f"paper-arguments: {flag} requires a value.")
                    value = tokens[index]
                result.append(flag)
                result.append(value)
                position = len(token)
                continue
            raise SystemExit(
                f"paper-arguments contains an unsupported argument: {flag}. "
                "Only -v, -l, and -m <file> are allowed."
            )
        index += 1
    return result
