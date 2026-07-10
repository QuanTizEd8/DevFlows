from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from devflows.errors import DevflowsError
from devflows.yaml import load_yaml

CONFIG_RELATIVE_PATH = Path(".config/project.yaml")
_REQUIRED_KEYS = ("owner", "repo", "default_branch", "license", "docs_url")


@dataclass(frozen=True)
class Project:
    """Central public identity for the catalog, loaded from .config/project.yaml."""

    owner: str
    repo: str
    default_branch: str
    license: str
    docs_url: str

    @property
    def slug(self) -> str:
        """`owner/repo`, as used in `uses:` references."""
        return f"{self.owner}/{self.repo}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.slug}"

    def uses_reference(self, workflow_id: str, ref: str) -> str:
        """A copy-pasteable `uses:` target for a published workflow."""
        return f"{self.slug}/.github/workflows/{workflow_id}.yaml@{ref}"


def find_root(root: Path | None = None, *, start: Path | None = None) -> Path:
    """Resolve the catalog root.

    If ``root`` is given it is used directly (the CLI ``--root`` override).
    Otherwise walk up from ``start`` (or the current working directory) until a
    directory containing ``.config/project.yaml`` is found.
    """
    if root is not None:
        candidate = root.resolve()
        if not (candidate / CONFIG_RELATIVE_PATH).is_file():
            raise DevflowsError(
                f"{candidate} is not a DevFlows catalog root (missing {CONFIG_RELATIVE_PATH})."
            )
        return candidate
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / CONFIG_RELATIVE_PATH).is_file():
            return candidate
    raise DevflowsError(
        f"Could not find a DevFlows catalog root: no {CONFIG_RELATIVE_PATH} in {origin} "
        "or any parent directory. Run from inside the catalog or pass --root."
    )


@cache
def _load_project_cached(config_path: str) -> Project:
    data = load_yaml(Path(config_path))
    missing = [key for key in _REQUIRED_KEYS if not data.get(key)]
    if missing:
        raise DevflowsError(
            f"{config_path}: missing required project keys: {', '.join(sorted(missing))}."
        )
    return Project(
        owner=str(data["owner"]),
        repo=str(data["repo"]),
        default_branch=str(data["default_branch"]),
        license=str(data["license"]),
        docs_url=str(data["docs_url"]),
    )


def load_project(root: Path | None = None) -> Project:
    """Load the project identity for the catalog rooted at ``root`` (or discovered)."""
    resolved = find_root(root)
    return _load_project_cached(str(resolved / CONFIG_RELATIVE_PATH))
