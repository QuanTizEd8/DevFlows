"""Fail-fast input validation for binder-build (validate job).

Env maps ONLY ``inputs.*`` (no secrets, no needs, no github.*), so the
validation-failure test harness can reconstruct the identical env from the scenario
inputs and defaults and exercise every rejection without a reusable-workflow call.
The non-ghcr-registry-without-docker-password check is NOT here: validate cannot
inspect secret presence, so that loud failure lives in the push job's tokenless
preflight (preflight-push.py) and is covered by a unit test.
"""

from __future__ import annotations

import os

import parsing


def main() -> int:
    # image identity ------------------------------------------------------------
    _guard(lambda: parsing.validate_image_name(os.environ.get("IMAGE_NAME", "")))
    _guard(lambda: parsing.validate_tag_list(os.environ.get("IMAGE_TAGS", ""), field="image-tags"))
    if _bool("IMAGE_SHA_TAG_ENABLED"):
        _guard(
            lambda: parsing.validate_tag_prefix(
                os.environ.get("IMAGE_SHA_TAG_PREFIX", ""), field="image-sha-tag-prefix"
            )
        )

    # repo2docker build ---------------------------------------------------------
    _guard(
        lambda: parsing.validate_source_path(
            os.environ.get("REPO2DOCKER_SOURCE_PATH", ""), field="repo2docker-source-path"
        )
    )
    _guard(
        lambda: parsing.validate_version(
            os.environ.get("REPO2DOCKER_VERSION", ""), field="repo2docker-version"
        )
    )
    _guard(
        lambda: parsing.parse_repo2docker_arguments(
            os.environ.get("REPO2DOCKER_ARGUMENTS", ""), field="repo2docker-arguments"
        )
    )
    _validate_positive("REPO2DOCKER_TIMEOUT_MINUTES", "repo2docker-timeout-minutes")
    _validate_positive("PUSH_TIMEOUT_MINUTES", "push-timeout-minutes")

    # reproducibility Dockerfile artifact --------------------------------------
    if _bool("DOCKERFILE_ARTIFACT_ENABLED"):
        _guard(
            lambda: parsing.validate_artifact_name(
                os.environ.get("DOCKERFILE_ARTIFACT_NAME", ""), field="dockerfile-artifact-name"
            )
        )

    # best-effort mybinder cache warm ------------------------------------------
    if _bool("BINDER_CACHE_WARM_ENABLED"):
        _guard(
            lambda: parsing.validate_provider(
                os.environ.get("BINDER_CACHE_PROVIDER", ""), field="binder-cache-provider"
            )
        )
        _guard(
            lambda: parsing.validate_https_url(
                os.environ.get("BINDER_CACHE_ENDPOINT", ""), field="binder-cache-endpoint"
            )
        )
        _guard(
            lambda: parsing.validate_non_empty(
                os.environ.get("BINDER_CACHE_REPOSITORY", ""), field="binder-cache-repository"
            )
        )
        _guard(
            lambda: parsing.validate_non_empty(
                os.environ.get("BINDER_CACHE_REF", ""), field="binder-cache-ref"
            )
        )

    # environment-gated push ----------------------------------------------------
    # The push job is skipped entirely in dry-run, so an environment is only required
    # for a real push. This is the only unguarded credentialed side effect, so refuse
    # to push into an unnamed (unprotected) environment.
    if not _bool("PUBLISH_DRY_RUN_ENABLED"):
        _guard(
            lambda: parsing.validate_non_empty(
                os.environ.get("PUSH_ENVIRONMENT_NAME", ""), field="push-environment-name"
            ),
            hint=(
                " Set push-environment-name to a protected GitHub Environment, or run with "
                "publish-dry-run-enabled to build without pushing."
            ),
        )
    return 0


def _guard(call, *, hint: str = "") -> None:
    try:
        call()
    except parsing.SpecError as error:
        raise SystemExit(f"{error}{hint}") from error


def _validate_positive(env_name: str, field: str) -> None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return
    try:
        value = int(raw)
    except ValueError as error:
        raise SystemExit(f"{field} must be an integer; got {raw!r}.") from error
    if value <= 0:
        raise SystemExit(f"{field} must be a positive integer; got {value}.")


def _bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
