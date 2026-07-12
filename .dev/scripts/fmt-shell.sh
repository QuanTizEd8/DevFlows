#!/usr/bin/env bash
set -euo pipefail

# Format shell scripts with shfmt from the pixi environment. Invoking the tool via
# `pixi run --` keeps this script self-contained: it behaves identically whether
# run directly, via `task fmt`, or from a git hook, regardless of what is on PATH.
mapfile -t files < <(find .dev/scripts -type f -name "*.sh" | sort)
if ((${#files[@]} > 0)); then
  pixi run -- shfmt -w "${files[@]}"
fi
