from __future__ import annotations

import json
import os
import subprocess


def main() -> int:
    image = _required("IMAGE_NAME")
    tag = _required("IMAGE_TAG")
    matrix = json.loads(_required("BUILD_MATRIX"))
    if not isinstance(matrix, list) or not matrix:
        raise SystemExit("BUILD_MATRIX must be a nonempty JSON array.")

    platform_tags = []
    for index, entry in enumerate(matrix):
        if not isinstance(entry, dict):
            raise SystemExit(f"BUILD_MATRIX[{index}] must be an object.")
        platform_tag = str(entry.get("platform_tag") or "").strip()
        if not platform_tag:
            raise SystemExit(f"BUILD_MATRIX[{index}].platform_tag is required.")
        platform_tags.append(platform_tag)

    arch_images = [f"{image}:{tag}-{platform_tag}" for platform_tag in platform_tags]
    image_ref = f"{image}:{tag}"
    _imagetools_create(image_ref, arch_images)

    sha_image_ref = ""
    if _truthy(os.environ.get("IMAGE_SHA_TAG_ENABLED", "")):
        sha = _required("SOURCE_SHA")
        sha_prefix = os.environ.get("IMAGE_SHA_TAG_PREFIX", "sha-")
        sha_image_ref = f"{image}:{sha_prefix}{sha}"
        _imagetools_create(sha_image_ref, arch_images)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            output.write(f"image-ref={image_ref}\n")
            output.write(f"sha-image-ref={sha_image_ref}\n")
    return 0


def _imagetools_create(tag: str, sources: list[str]) -> None:
    subprocess.run(
        ["docker", "buildx", "imagetools", "create", "-t", tag, *sources],
        check=True,
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
