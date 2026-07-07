from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal devcontainers.
    yaml = None


if yaml is not None:

    class GitHubActionsLoader(yaml.SafeLoader):
        """YAML loader that keeps GitHub Actions keys like `on` as strings."""

    GitHubActionsLoader.yaml_implicit_resolvers = {
        key: value[:] for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    for first_char, mappings in list(GitHubActionsLoader.yaml_implicit_resolvers.items()):
        GitHubActionsLoader.yaml_implicit_resolvers[first_char] = [
            (tag, regexp) for tag, regexp in mappings if tag != "tag:yaml.org,2002:bool"
        ]

    GitHubActionsLoader.add_implicit_resolver(
        "tag:yaml.org,2002:bool",
        re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
        list("tTfF"),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        data = _load_with_yq(path)
    else:
        with path.open(encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=GitHubActionsLoader)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the document root.")
    return data


def _load_with_yq(path: Path) -> Any:
    result = subprocess.run(
        ["yq", "-o=json", ".", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)
