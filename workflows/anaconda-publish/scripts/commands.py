"""anaconda-client argv builders (pure; every mutation is an explicit argv list)."""

from __future__ import annotations

# Pinned default anaconda-client version installed ephemerally (``uvx --from``) when
# publish-client-version is empty. Registered for Renovate via a custom pep440
# manager in renovate.json5 keyed on the inline comment below; a unit test asserts
# the manager regex still matches this constant so the pin stays auto-updated.
# renovate: datasource=pypi depName=anaconda-client
ANACONDA_CLIENT_VERSION = "1.13.0"

# upload-existing-mode enum mapped onto anaconda-client's mutually-exclusive group.
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
    """Wrap an anaconda-client argv in an ephemeral, pinned ``uvx --from`` runner."""
    return ["uvx", "--from", f"anaconda-client=={client_version}", *argv]


def resolve_client_version(override: str) -> str:
    """The anaconda-client version to install: an explicit override or the pin."""
    override = override.strip()
    return override or ANACONDA_CLIENT_VERSION
