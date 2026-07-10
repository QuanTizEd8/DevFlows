#!/usr/bin/env bash
set -euo pipefail

# Lint shell scripts with shellcheck and shfmt from the pixi environment. Invoking
# the tools via `pixi run --` keeps this script self-contained: it behaves the same
# whether run directly, via `task lint`, or from a git hook, regardless of PATH.
mapfile -t files < <(find scripts -type f -name "*.sh" | sort)
if ((${#files[@]} > 0)); then
  pixi run -- shellcheck "${files[@]}"
  pixi run -- shfmt -d "${files[@]}"
fi
