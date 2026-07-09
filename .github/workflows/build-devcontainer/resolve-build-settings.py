from __future__ import annotations

import os


def main() -> int:
    image_name = _required("IMAGE_NAME")
    platform_tag = _required("MATRIX_PLATFORM_TAG")
    cache_key_prefix = _required("CACHE_KEY_PREFIX")
    dependency_hash = os.environ.get("CACHE_DEPENDENCY_HASH", "")

    cache_path = _optional("CACHE_PATH") or _required("DEVCONTAINER_USER_DATA_FOLDER")
    cache_key = _optional("CACHE_KEY") or f"{cache_key_prefix}-{platform_tag}-{dependency_hash}"
    cache_restore_keys = _optional("CACHE_RESTORE_KEYS") or f"{cache_key_prefix}-{platform_tag}-"
    cache_from = _optional("DEVCONTAINER_CACHE_FROM") or (
        f"{image_name}:{cache_key_prefix}-{platform_tag}"
    )
    cache_to = _optional("DEVCONTAINER_CACHE_TO") or (
        f"type=registry,ref={image_name}:{cache_key_prefix}-{platform_tag},mode=max"
    )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            output.write(f"cache-path={cache_path}\n")
            output.write(f"cache-key={cache_key}\n")
            output.write(f"cache-restore-keys={cache_restore_keys}\n")
            output.write(f"cache-from={cache_from}\n")
            output.write(f"cache-to={cache_to}\n")
    return 0


def _required(name: str) -> str:
    value = _optional(name)
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _optional(name: str) -> str:
    return os.environ.get(name, "").strip()


if __name__ == "__main__":
    raise SystemExit(main())
