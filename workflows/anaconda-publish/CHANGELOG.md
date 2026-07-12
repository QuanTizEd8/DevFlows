# Changelog

## 0.1.0 (2026-07-12)


### ⚠ BREAKING CHANGES

* **repo:** move src/scripts/harness+pyproject to .dev, tool configs to .config, lefthook->task, reorganize tests

### Features

* **anaconda-publish:** add staged conda publishing workflow ([ee1d9db](https://github.com/QuanTizEd8/DevFlows/commit/ee1d9db48cf11d771501e35f9044b572ef5c8fee))
* **generator:** add job-output io channel (single JSON job-outputs) ([cd5ee15](https://github.com/QuanTizEd8/DevFlows/commit/cd5ee1581778d7f688f46b980d26fe3e621010b8))
* **generator:** add job-output io channel (single JSON job-outputs) ([828cfec](https://github.com/QuanTizEd8/DevFlows/commit/828cfec9ac452d9a0db7ed4d523b7ec84b8dc04e))


### Bug Fixes

* **publishing:** harden argument allowlists and cover credentialed paths ([faae144](https://github.com/QuanTizEd8/DevFlows/commit/faae1440ca6745eeb132c8c4ea3666c1b39ca488))
* **workflows:** ASCII-only inlined scripts; guard against YAML style flip ([fe84507](https://github.com/QuanTizEd8/DevFlows/commit/fe84507b60c01657d9e318c65bf158ed41080920))


### Performance Improvements

* **anaconda-publish:** shrink generated workflow under GitHub's size limit ([51e2253](https://github.com/QuanTizEd8/DevFlows/commit/51e2253b75a3d11af4967f21a1a3568a6e8415d8))


### Code Refactoring

* **repo:** move src/scripts/harness+pyproject to .dev, tool configs to .config, lefthook-&gt;task, reorganize tests ([0374937](https://github.com/QuanTizEd8/DevFlows/commit/0374937947cf8b184ff3640845e3044f434659c7))
