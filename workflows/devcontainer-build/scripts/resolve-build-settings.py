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

    registry_cache_enabled = _bool("DEVCONTAINER_CACHE_REGISTRY_ENABLED", default=True)
    push = _optional("DEVCONTAINER_PUSH").lower()
    default_cache_ref = f"{image_name}:{cache_key_prefix}-{platform_tag}"
    cache_from = _resolve_cache_from(registry_cache_enabled, push, default_cache_ref)
    cache_to = _resolve_cache_to(registry_cache_enabled, push, default_cache_ref)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            _emit(output, "cache-path", cache_path)
            _emit(output, "cache-key", cache_key)
            _emit(output, "cache-restore-keys", cache_restore_keys)
            _emit(output, "cache-from", cache_from)
            _emit(output, "cache-to", cache_to)
    return 0


def _resolve_cache_from(registry_cache_enabled: bool, push: str, default_ref: str) -> str:
    raw = _optional("DEVCONTAINER_CACHE_FROM")
    if raw.lower() == "none":
        return ""
    # An explicit caller-provided cache-from is always honored: cache-from is a
    # read, so it is safe even in build-only mode (e.g. type=gha).
    if raw:
        return raw
    # Do not derive the default registry cache ref when the registry cache is
    # opted out or the build does not push (build-only validation). Reading that
    # ref needs registry pull rights the run may not have -- buildx logs a noisy
    # "failed to configure registry cache importer: pull access denied" -- and it
    # is a cache-poisoning surface. Symmetric with _resolve_cache_to's push guard.
    if not registry_cache_enabled or push == "never":
        return ""
    return default_ref


def _resolve_cache_to(registry_cache_enabled: bool, push: str, default_ref: str) -> str:
    raw = _optional("DEVCONTAINER_CACHE_TO")
    if raw.lower() == "none":
        return ""
    # Never push a registry build cache when caching is disabled or the build
    # does not push images (build-only validation mode): a cache-to would fail
    # without push rights and is a cache-poisoning surface.
    if not registry_cache_enabled or push == "never":
        return ""
    if raw:
        return raw
    return f"type=registry,ref={default_ref},mode=max"


def _emit(output, name: str, value: str) -> None:
    # Caller-controlled inputs feed these values; a newline could forge or
    # inject additional step outputs. Single-line values are the only valid
    # form for cache paths, keys, and refs, so reject embedded newlines.
    if "\n" in value or "\r" in value:
        raise SystemExit(f"{name} value must not contain newline characters: {value!r}")
    output.write(f"{name}={value}\n")


def _required(name: str) -> str:
    value = _optional(name)
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _optional(name: str) -> str:
    return os.environ.get(name, "").strip()


def _bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
