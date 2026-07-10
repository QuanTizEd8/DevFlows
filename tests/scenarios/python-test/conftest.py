"""Keep the DevFlows unit-test run from collecting the fixture package's tests.

The repo pytest config sets ``testpaths = ["tests"]`` and recurses here. The
fixture package under ``pkg/`` has its own tests that import a package installed
only inside a scenario's ephemeral environment, so collecting them in the repo
suite would fail. Scenario runs point pytest at ``pkg/pyproject.toml`` as their
rootdir, which lives below this conftest, so this ignore never applies to them.
"""

from __future__ import annotations

collect_ignore = ["pkg"]
