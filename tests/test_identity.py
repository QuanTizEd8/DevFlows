"""Identity-consistency guard (item 14 / D7).

Roughly two dozen tracked files hard-code the ``QuanTizEd8/DevFlows`` owner/repo
slug (and its ghcr / GitHub Pages URL forms) with nothing tying them to
``.config/project.yaml``. This test scans the known identity-bearing files and
asserts every project reference matches the config, so an org migration becomes
"edit .config/project.yaml, then fix every failure this test lists".

Maintainability: one canonical regex list below, each yielding the owner/repo it
found; the failure message names the file, line, and the mismatch. Only
references that clearly point at *this* project (owner or repo already matches)
are checked, so third-party slugs and doc placeholders (``ghcr.io/owner/...``)
are ignored.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from devflows.project import load_project

# Slug references that carry BOTH an owner and a repo component.
_USES_REF = re.compile(
    r"(?<![\w.-])([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)/\.github/workflows/"
)
_GITHUB_URL = re.compile(
    r"(?<![\w.-])github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+?)(?=[/)\s\"'.]|$)"
)
_PAGES_URL = re.compile(r"https?://([a-z0-9-]+)\.github\.io/([A-Za-z0-9._-]+)")
_OWNER_REPO_FORMS = (
    ("uses-ref", _USES_REF),
    ("github-url", _GITHUB_URL),
    ("pages-url", _PAGES_URL),
)


def _identity_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    named = {"README.md", "SECURITY.md", "CONTRIBUTING.md", "renovate.json5", ".act/push.json"}
    named.add(".devcontainer/devcontainer.json")
    keep: list[Path] = []
    for rel in tracked:
        if (
            rel in named
            or (rel.startswith("docs/") and rel.endswith(".md"))
            or rel.startswith("tests/fixtures/")
            or re.match(r"\.github/workflows/_[^/]*\.ya?ml$", rel)
        ):
            keep.append(Path(rel))
    return keep


def test_identity_bearing_files_match_config() -> None:
    project = load_project(Path.cwd())
    owner, repo = project.owner.lower(), project.repo.lower()
    # ghcr images are owner-lowercased; anchor on the repo-derived image name so
    # unrelated same-owner images (e.g. ghcr.io/<owner>/devfeats/*) are ignored.
    ghcr_ref = re.compile(rf"ghcr\.io/([a-z0-9][a-z0-9-]*)/{re.escape(repo)}[a-z0-9-]*")

    failures: list[str] = []
    checked = 0
    for path in _identity_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for form, pattern in _OWNER_REPO_FORMS:
                for match in pattern.finditer(line):
                    found_owner, found_repo = match.group(1).lower(), match.group(2).lower()
                    if found_owner != owner and found_repo != repo:
                        continue  # not a reference to this project
                    checked += 1
                    if found_owner != owner or found_repo != repo:
                        failures.append(
                            f"{path}:{lineno}: {form} '{match.group(1)}/{match.group(2)}' "
                            f"!= config '{project.owner}/{project.repo}'"
                        )
            for match in ghcr_ref.finditer(line):
                checked += 1
                if match.group(1) != owner:
                    failures.append(f"{path}:{lineno}: ghcr owner '{match.group(1)}' != '{owner}'")

    assert not failures, "identity drift from .config/project.yaml:\n" + "\n".join(failures)
    # Guard against a regex regression silently matching nothing (vacuous pass).
    assert checked > 10, f"expected many identity references, only scanned {checked}"


def test_act_push_event_identity_matches_config() -> None:
    project = load_project(Path.cwd())
    data = json.loads(Path(".act/push.json").read_text(encoding="utf-8"))
    repository = data["repository"]

    assert repository["full_name"] == project.slug
    assert repository["name"] == project.repo
    assert repository["owner"]["login"] == project.owner
