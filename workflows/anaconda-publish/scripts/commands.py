"""anaconda-client argv builders (pure; every mutation is an explicit argv list)."""

from __future__ import annotations

# Pinned default anaconda-client, installed ephemerally via ``uvx --from`` when
# publish-client-version is empty. Kept current by Renovate (custom pep440 manager
# in renovate.json5); a unit test asserts the manager regex still matches this line.
# renovate: datasource=pypi depName=anaconda-client
ANACONDA_CLIENT_VERSION = "1.13.0"

_EXISTING_MODE_FLAGS = {"fail": [], "skip": ["--skip-existing"], "overwrite": ["--force"]}


def anaconda_base(server_url: str) -> list[str]:
    argv = ["anaconda"]
    server_url = server_url.strip()
    if server_url:
        argv += ["-s", server_url]
    return argv


def build_upload_argv(
    *,
    server_url: str,
    owner: str,
    label: str,
    mode: str,
    extra_arguments: list[str],
    file_path: str,
) -> list[str]:
    return (
        anaconda_base(server_url)
        + ["upload", "--user", owner, "--label", label]
        + list(_EXISTING_MODE_FLAGS[mode])
        + list(extra_arguments)
        + [file_path]
    )


def build_move_argv(*, server_url: str, from_label: str, to_label: str, target: str) -> list[str]:
    return anaconda_base(server_url) + [
        "move",
        "--from-label",
        from_label,
        "--to-label",
        to_label,
        target,
    ]


def build_remove_argv(*, server_url: str, target: str) -> list[str]:
    return anaconda_base(server_url) + ["remove", "--force", target]


def uvx_wrap(client_version: str, argv: list[str]) -> list[str]:
    return ["uvx", "--from", f"anaconda-client=={client_version}", *argv]


def resolve_client_version(override: str) -> str:
    override = override.strip()
    return override or ANACONDA_CLIENT_VERSION
