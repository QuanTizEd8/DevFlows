# Assemble the caller-mapped job-outputs JSON object for the job-output channel.
# Reads DEVFLOWS_JOB_OUTPUT_MAP (newline-delimited key=SOURCE) and writes one
# job-outputs GITHUB_OUTPUT entry. Values are JSON-encoded under a random heredoc
# delimiter, so no crafted value can inject an extra output line.
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _resolve(key: str, source: str) -> str:
    kind, sep, rest = source.partition(":")
    if not sep or kind not in {"env", "file"}:
        raise SystemExit(f"job-output-map key {key!r}: source must be 'env:VAR' or 'file:path'.")
    if kind == "env":
        return os.environ.get(rest, "")
    path = Path(rest)
    if not rest or rest == "." or path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"job-output-map key {key!r}: file path must be workspace-relative.")
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    outputs: dict[str, str] = {}
    for raw in os.environ.get("DEVFLOWS_JOB_OUTPUT_MAP", "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, source = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.match(key):
            raise SystemExit(f"job-output-map entry for key {key!r}: expected 'key=SOURCE'.")
        outputs[key] = _resolve(key, source.strip())

    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        raise SystemExit("GITHUB_OUTPUT is not set.")
    payload = json.dumps(outputs, separators=(",", ":"), sort_keys=True)
    delimiter = f"ghadelim_{secrets.token_hex(16)}"
    if delimiter in payload:  # pragma: no cover - astronomically unlikely
        raise SystemExit("output delimiter collision; retry.")
    with Path(github_output).open("a", encoding="utf-8") as handle:
        handle.write(f"job-outputs<<{delimiter}\n{payload}\n{delimiter}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
