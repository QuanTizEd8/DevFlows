from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def main() -> int:
    image = _required("IMAGE_NAME")
    tags = _tags(_required("IMAGE_TAGS"))
    matrix = json.loads(_required("BUILD_MATRIX"))
    digest_dir = Path(_required("DIGEST_DIR"))

    platform_tags = _platform_tags(matrix)
    sources = _digest_sources(image, digest_dir, platform_tags)

    # Tag the merged multi-arch manifest with every requested tag, all pointing at
    # the same immutable per-platform digests. The first (primary) tag names the
    # image-ref output.
    for tag in tags:
        _imagetools_create(f"{image}:{tag}", sources)
    image_ref = f"{image}:{tags[0]}"

    sha_image_ref = ""
    if _truthy(os.environ.get("IMAGE_SHA_TAG_ENABLED", "")):
        sha = _required("SOURCE_SHA")
        sha_prefix = os.environ.get("IMAGE_SHA_TAG_PREFIX", "sha-")
        sha_image_ref = f"{image}:{sha_prefix}{sha}"
        _imagetools_create(sha_image_ref, sources)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            _emit(output, "image-ref", image_ref)
            _emit(output, "sha-image-ref", sha_image_ref)
    return 0


def _tags(raw: str) -> list[str]:
    """Parse the image-tags newline list (validated already in the validate job)."""
    tags = [line.strip() for line in raw.splitlines() if line.strip()]
    if not tags:
        raise SystemExit("IMAGE_TAGS resolved to an empty list; nothing to tag.")
    return tags


def _platform_tags(matrix: object) -> list[str]:
    if not isinstance(matrix, list) or not matrix:
        raise SystemExit("BUILD_MATRIX must be a nonempty JSON array.")
    platform_tags: list[str] = []
    for index, entry in enumerate(matrix):
        if not isinstance(entry, dict):
            raise SystemExit(f"BUILD_MATRIX[{index}] must be an object.")
        platform_tag = str(entry.get("platform_tag") or "").strip()
        if not platform_tag:
            raise SystemExit(f"BUILD_MATRIX[{index}].platform_tag is required.")
        platform_tags.append(platform_tag)
    return platform_tags


def _digest_sources(image: str, digest_dir: Path, platform_tags: list[str]) -> list[str]:
    """Build immutable ``image@sha256:...`` source refs from per-platform digests.

    Each build job captured the digest of its pushed image and handed it over
    through a per-platform artifact. Merging over these digests (instead of the
    mutable ``image:tag-platform`` tags) makes the manifest correct-by-content
    even under concurrent runs.
    """
    sources: list[str] = []
    for platform_tag in platform_tags:
        digest_file = digest_dir / platform_tag
        if not digest_file.is_file():
            raise SystemExit(
                f"missing digest for platform {platform_tag!r}; expected {digest_file}"
            )
        digest = digest_file.read_text(encoding="utf-8").strip()
        if not digest.startswith("sha256:"):
            raise SystemExit(f"invalid digest for platform {platform_tag!r}: {digest!r}")
        sources.append(f"{image}@{digest}")
    # Preserve order while dropping any duplicate digests.
    return list(dict.fromkeys(sources))


def _imagetools_create(tag: str, sources: list[str]) -> None:
    subprocess.run(
        ["docker", "buildx", "imagetools", "create", "-t", tag, *sources],
        check=True,
    )


def _emit(output, name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise SystemExit(f"{name} value must not contain newline characters: {value!r}")
    output.write(f"{name}={value}\n")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
