"""GitHub Release driver for the release job (gh CLI, built-in GITHUB_TOKEN).

Creates or updates a GitHub Release from release-tag per release-existing-mode
(fail/update/skip), attaching the assets prepare resolved and wiring the draft /
prerelease / latest / generate-notes / discussion-category flags. Ordered after
zenodo-deposit so the minted or reserved DOI can be appended to the notes. NO
checkout (prepare already read any notes file into the release-body output) and NO
secret: gh authenticates with the workflow's GITHUB_TOKEN, never a token secret.
The gh runner is injected so the flow is unit-tested against a fake gh.
"""

from __future__ import annotations

import os
import secrets as _secrets
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

GhResult = subprocess.CompletedProcess
GhRunner = Callable[[list[str]], GhResult]


def _real_gh(args: list[str]) -> GhResult:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def _checked(gh: GhRunner, args: list[str]) -> str:
    result = gh(args)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result.stdout or ""


def release_exists(gh: GhRunner, tag: str) -> bool:
    return gh(["release", "view", tag, "--json", "url"]).returncode == 0


def compose_body(base_body: str, *, append_doi: bool, doi: str, concept: str, state: str) -> str:
    if not append_doi or not doi:
        return base_body
    label = "reserved" if state == "draft" else "registered"
    footer = ["", "---", f"Zenodo DOI ({label}): {doi}"]
    if concept:
        footer.append(f"Concept DOI: {concept}")
    prefix = base_body.rstrip("\n")
    return (prefix + "\n" if prefix else "") + "\n".join(footer) + "\n"


def _create_args(tag: str, notes_file: str, assets: list[str]) -> list[str]:
    args = ["release", "create", tag]
    args += assets
    args += ["--notes-file", notes_file]
    title = os.environ.get("RELEASE_TITLE", "").strip() or tag
    args += ["--title", title]
    target = os.environ.get("RELEASE_TARGET", "").strip()
    if target:
        args += ["--target", target]
    if _bool("RELEASE_DRAFT_ENABLED"):
        args.append("--draft")
    if _bool("RELEASE_PRERELEASE_ENABLED"):
        args.append("--prerelease")
    args += ["--latest" if _bool("RELEASE_LATEST_ENABLED") else "--latest=false"]
    if _bool("RELEASE_GENERATE_NOTES_ENABLED"):
        args.append("--generate-notes")
    category = os.environ.get("RELEASE_DISCUSSION_CATEGORY", "").strip()
    if category:
        args += ["--discussion-category", category]
    return args


def _edit_args(tag: str, notes_file: str) -> list[str]:
    args = ["release", "edit", tag, "--notes-file", notes_file]
    title = os.environ.get("RELEASE_TITLE", "").strip() or tag
    args += ["--title", title]
    args += ["--draft" if _bool("RELEASE_DRAFT_ENABLED") else "--draft=false"]
    args += ["--prerelease" if _bool("RELEASE_PRERELEASE_ENABLED") else "--prerelease=false"]
    args += ["--latest" if _bool("RELEASE_LATEST_ENABLED") else "--latest=false"]
    return args


def perform_release(gh: GhRunner, *, base_body: str) -> str:
    tag = os.environ.get("RELEASE_TAG", "").strip()
    mode = os.environ.get("RELEASE_EXISTING_MODE", "fail").strip() or "fail"
    exists = release_exists(gh, tag)
    if exists and mode == "fail":
        raise SystemExit(
            f"a GitHub release already exists for {tag!r} and release-existing-mode is "
            "'fail'; set 'update' or 'skip' to proceed."
        )
    if exists and mode == "skip":
        return _release_url(gh, tag)

    body = compose_body(
        base_body,
        append_doi=_bool("RELEASE_APPEND_DOI_ENABLED"),
        doi=os.environ.get("ZENODO_DOI", "").strip(),
        concept=os.environ.get("ZENODO_CONCEPT_DOI", "").strip(),
        state=os.environ.get("ZENODO_STATE", "").strip(),
    )
    assets = [
        line.strip()
        for line in os.environ.get("RELEASE_ASSET_LIST", "").splitlines()
        if line.strip()
    ]

    with tempfile.TemporaryDirectory() as tmp:
        notes_file = str(Path(tmp) / "notes.md")
        Path(notes_file).write_text(body, encoding="utf-8")
        if exists:
            _checked(gh, _edit_args(tag, notes_file))
            if assets:
                _checked(gh, ["release", "upload", tag, *assets, "--clobber"])
        else:
            _checked(gh, _create_args(tag, notes_file, assets))
    return _release_url(gh, tag)


def _release_url(gh: GhRunner, tag: str) -> str:
    return _checked(gh, ["release", "view", tag, "--json", "url", "-q", ".url"]).strip()


def main() -> int:
    if _bool("PUBLISH_DRY_RUN_ENABLED"):
        print("publish-dry-run-enabled: the release job creates no GitHub release.")
        return 0
    url = perform_release(_real_gh, base_body=os.environ.get("RELEASE_BODY", ""))
    _emit_outputs({"release-url": url})
    print(f"zenodo-release: GitHub release available at {url}")
    return 0


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_outputs(outputs: dict[str, str]) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            delimiter = f"ghadelim_{_secrets.token_hex(16)}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


if __name__ == "__main__":
    raise SystemExit(main())
