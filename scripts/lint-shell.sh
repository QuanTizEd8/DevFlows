#!/usr/bin/env bash
set -euo pipefail

mapfile -t files < <(find scripts -type f -name "*.sh" | sort)
if ((${#files[@]} > 0)); then
  shellcheck "${files[@]}"
  shfmt -d "${files[@]}"
fi
