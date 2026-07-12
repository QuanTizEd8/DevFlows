# Changelog

## 0.1.0 (2026-07-12)


### ⚠ BREAKING CHANGES

* **repo:** move src/scripts/harness+pyproject to .dev, tool configs to .config, lefthook->task, reorganize tests

### Features

* **generator:** add job-output io channel (single JSON job-outputs) ([cd5ee15](https://github.com/QuanTizEd8/DevFlows/commit/cd5ee1581778d7f688f46b980d26fe3e621010b8))
* **generator:** add job-output io channel (single JSON job-outputs) ([828cfec](https://github.com/QuanTizEd8/DevFlows/commit/828cfec9ac452d9a0db7ed4d523b7ec84b8dc04e))
* **python-build:** reusable Python distribution build workflow ([26bc3de](https://github.com/QuanTizEd8/DevFlows/commit/26bc3de72a7f5be99384f0cc7bbd166d7020fbe0))
* **scenarios:** add file-glob-exists assertion for non-deterministic filenames ([c1c48b5](https://github.com/QuanTizEd8/DevFlows/commit/c1c48b51069ac2fa4fb4bddeacd70dbe690b27c0))


### Bug Fixes

* **python-build:** add uv-cache-mode, reject dead artifact-download, cover cibw e2e ([b4dad1f](https://github.com/QuanTizEd8/DevFlows/commit/b4dad1f8a8581e51ded1afd5a743f741f908259d))
* **python-build:** reindex conda channel without a conda dependency ([9b12844](https://github.com/QuanTizEd8/DevFlows/commit/9b1284447c45544896446a7b7c02db5ad643231d))
* **workflows:** ASCII-only inlined scripts; guard against YAML style flip ([fe84507](https://github.com/QuanTizEd8/DevFlows/commit/fe84507b60c01657d9e318c65bf158ed41080920))


### Code Refactoring

* **repo:** move src/scripts/harness+pyproject to .dev, tool configs to .config, lefthook-&gt;task, reorganize tests ([0374937](https://github.com/QuanTizEd8/DevFlows/commit/0374937947cf8b184ff3640845e3044f434659c7))
