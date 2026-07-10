"""Build the requested paper flavors with the pinned openjournals/inara image.

Modelled exactly on pandoc's run-pandoc.py: every input arrives through
os.environ, the docker argv is assembled programmatically (never a shell
string), and subprocess.run is called without a shell. For each requested flavor
the pinned image is run once, then that flavor's fixed inara outputs are moved
into <paper-output-directory>/<flavor>/ BEFORE the next flavor runs, so the
paper.pdf that both draft-pdf and final-pdf write can never collide. The
artifact-upload channel then uploads the whole output directory as one artifact.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import common


def main() -> int:
    config = common.parse_and_validate(os.environ, require_source_exists=True)
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()

    source_path = (workspace / config.source_relative).resolve()
    source_directory = source_path.parent
    output_directory = (workspace / config.output_relative).resolve()

    if output_directory.exists() and any(output_directory.iterdir()):
        raise SystemExit(
            "paper-output-directory already exists and is not empty: "
            f"{config.output_relative}. Refusing to merge a prior run's outputs."
        )

    for flavor_name in config.flavors:
        flavor = common.FLAVORS[flavor_name]
        command = [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{workspace}:/data",
            "--workdir",
            "/data",
            "--env",
            f"JOURNAL={config.journal_env}",
            config.image,
            *flavor.argv,
            *config.extra_arguments,
            config.source_relative,
        ]
        print(f"Building flavor {flavor_name}: {' '.join(command)}")
        subprocess.run(command, check=True)
        _collect(flavor_name, flavor, source_directory, output_directory)

    _write_outputs(config)
    return 0


def _collect(
    flavor_name: str,
    flavor: common.Flavor,
    source_directory: Path,
    output_directory: Path,
) -> None:
    """Move a flavor's fixed inara outputs into <output>/<flavor>/."""
    destination_root = output_directory / flavor_name
    destination_root.mkdir(parents=True, exist_ok=True)
    for output in flavor.outputs:
        produced = source_directory / output.name
        if not produced.exists():
            if output.required:
                raise SystemExit(
                    f"flavor {flavor_name} did not produce its expected output "
                    f"{output.name!r} next to the paper source."
                )
            continue
        destination = destination_root / output.name
        shutil.move(str(produced), str(destination))
        print(f"Collected {flavor_name}: {output.name} -> {destination}")


def _write_outputs(config: common.Config) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as handle:
        handle.write(f"paper-output-directory={config.output_relative}\n")
        handle.write("flavors-built<<DEVFLOWS_EOF\n")
        handle.write("\n".join(config.flavors))
        handle.write("\nDEVFLOWS_EOF\n")


if __name__ == "__main__":
    sys.exit(main())
