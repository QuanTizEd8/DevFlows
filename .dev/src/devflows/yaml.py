from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from devflows.errors import DevflowsError

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
    if not path.is_file():
        raise DevflowsError(f"{path} does not exist.")
    if yaml is None:
        data = _load_with_yq(path)
    else:
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.load(handle, Loader=GitHubActionsLoader)
        except yaml.YAMLError as error:
            raise DevflowsError(f"{path}: invalid YAML: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DevflowsError(f"{path} must contain a YAML mapping at the document root.")
    return data


def load_yaml_text(text: str) -> dict[str, Any]:
    """Parse a YAML document from an in-memory string (mirrors ``load_yaml``)."""
    if yaml is None:
        raise RuntimeError("PyYAML is required to parse generated YAML text.")
    try:
        data = yaml.load(text, Loader=GitHubActionsLoader)
    except yaml.YAMLError as error:
        raise DevflowsError(f"invalid YAML: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DevflowsError("YAML text must contain a mapping at the document root.")
    return data


def dump_yaml(data: Any) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write generated YAML files.")
    # width=100 wraps long plain/folded scalars (chiefly the input `description:`
    # fields, previously emitted as single 300+ char lines) at word boundaries,
    # matching ruff's line-length and clearing yamllint's line-length warnings.
    # This is value-preserving: PyYAML folds the wrapped newlines back to single
    # spaces on parse, and `width` has NO effect on `|` literal block scalars, so
    # the inlined heredoc script bodies stay byte-identical (publish.py's
    # _assert_inlined_scripts_intact would fail generation otherwise).
    return yaml.dump(data, Dumper=GitHubActionsDumper, sort_keys=False, width=100)


if yaml is not None:

    class GitHubActionsDumper(yaml.SafeDumper):
        """YAML dumper with indentation and block strings suited to workflow files."""

        def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
            return super().increase_indent(flow=flow, indentless=False)

    def _represent_string(dumper: GitHubActionsDumper, value: str) -> Any:
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    GitHubActionsDumper.add_representer(str, _represent_string)


def _load_with_yq(path: Path) -> Any:
    result = subprocess.run(
        ["yq", "-o=json", ".", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)
