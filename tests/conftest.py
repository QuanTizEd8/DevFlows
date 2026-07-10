from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

PROJECT_YAML = textwrap.dedent(
    """\
    owner: Example
    repo: Demo
    default_branch: main
    license: Apache-2.0
    docs_url: https://example.github.io/Demo/
    """
)

WORKFLOW_YAML = textwrap.dedent(
    """\
    name: Demo
    on:
      workflow_call:
        inputs:
          message:
            description: Message to print.
            type: string
            required: false
            default: hello
    jobs:
      demo:
        runs-on: ubuntu-latest
        steps:
          - name: Run demo
            shell: bash
            env:
              DEVFLOWS_SCRIPT_ROOT: ${{ steps.devflows-runtime.outputs.script-root }}
            run: python "${DEVFLOWS_SCRIPT_ROOT}/demo/run.py"
    """
)

DEVFLOW_YAML = textwrap.dedent(
    """\
    id: demo
    name: Demo
    summary: Demo workflow.
    status: active
    owners:
      - Demo maintainers
    release:
      type: simple
      major: 1
    io:
      job: demo
      runtime: true
    tests:
      scenarios: []
    """
)


@pytest.fixture
def make_catalog(tmp_path: Path):
    """Factory building a minimal, self-contained catalog root under tmp_path."""

    def _make(
        *,
        script_body: str = 'print("ok")\n',
        devflow_yaml: str = DEVFLOW_YAML,
        workflow_yaml: str = WORKFLOW_YAML,
    ) -> Path:
        root = tmp_path / "repo"
        (root / ".config").mkdir(parents=True, exist_ok=True)
        (root / ".config/project.yaml").write_text(PROJECT_YAML, encoding="utf-8")

        demo = root / "workflows/demo"
        (demo / "scripts").mkdir(parents=True, exist_ok=True)
        (demo / "workflow.yaml").write_text(workflow_yaml, encoding="utf-8")
        (demo / "devflow.yaml").write_text(devflow_yaml, encoding="utf-8")
        (demo / "scripts/run.py").write_text(script_body, encoding="utf-8")

        (root / ".github/workflows").mkdir(parents=True, exist_ok=True)
        release = root / ".github/release-please"
        release.mkdir(parents=True, exist_ok=True)
        (release / "config.json").write_text(
            json.dumps(
                {
                    "tag-separator": "/",
                    "packages": {
                        "workflows/demo": {
                            "component": "demo",
                            "package-name": "demo",
                            "release-type": "simple",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (release / "manifest.json").write_text(
            json.dumps({"workflows/demo": "1.0.0"}), encoding="utf-8"
        )
        return root

    return _make
