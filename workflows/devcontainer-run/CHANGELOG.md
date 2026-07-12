# Changelog

## 0.1.0 (2026-07-12)


### ⚠ BREAKING CHANGES

* **catalog:** replace writeback channel with patch-emit + patch-applying writeback + python-lint fix mode
* **catalog:** rename build-devcontainer to devcontainer-build

### Features

* **catalog:** replace writeback channel with patch-emit + patch-applying writeback + python-lint fix mode ([497e3ff](https://github.com/QuanTizEd8/DevFlows/commit/497e3ff634b2d8a71cd8de09420bd26660443815))
* **devcontainer-run:** add opt-in commit/push (writeback) channel ([404b972](https://github.com/QuanTizEd8/DevFlows/commit/404b97239e3ef7391b966548d878b01d4358dee1))
* **devcontainer-run:** add reusable workflow to run commands in a prebuilt devcontainer ([2dc537b](https://github.com/QuanTizEd8/DevFlows/commit/2dc537b4574de7e955c7e5d7dd53587bb23a18e2))
* **devcontainer-run:** add workspace caching and harden container-env injection ([5e8e103](https://github.com/QuanTizEd8/DevFlows/commit/5e8e10329fc89b1ecf06529e64a148548b43f674))
* **devcontainer-run:** inject caller secrets via masked run-secrets bundle ([cec890d](https://github.com/QuanTizEd8/DevFlows/commit/cec890d2ad4070ed7505351d427d14031aaedeb5))
* **devcontainer-run:** run commands in a prebuilt devcontainer (catalog [#14](https://github.com/QuanTizEd8/DevFlows/issues/14)) ([9157fbf](https://github.com/QuanTizEd8/DevFlows/commit/9157fbfd423b2a1d39d4be68663461be15181992))
* **generator:** add job-output io channel (single JSON job-outputs) ([cd5ee15](https://github.com/QuanTizEd8/DevFlows/commit/cd5ee1581778d7f688f46b980d26fe3e621010b8))
* **generator:** add job-output io channel (single JSON job-outputs) ([828cfec](https://github.com/QuanTizEd8/DevFlows/commit/828cfec9ac452d9a0db7ed4d523b7ec84b8dc04e))


### Code Refactoring

* **catalog:** rename build-devcontainer to devcontainer-build ([ed66bf6](https://github.com/QuanTizEd8/DevFlows/commit/ed66bf6ccaef0e431a98ca04f8aec8a0afe6ebd8))
