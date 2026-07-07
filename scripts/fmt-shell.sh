#!/usr/bin/env bash
set -euo pipefail

mapfile -t files < <(find scripts -type f -name "*.sh" | sort)
if ((${#files[@]} > 0)); then
  shfmt -w "${files[@]}"
fi
