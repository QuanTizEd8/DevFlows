# User Guide

Reusable workflows are published from `.github/workflows` and should be called
from consuming repositories with an explicit version reference.

```yaml
jobs:
  example:
    uses: owner/devflows/.github/workflows/hello-world.yaml@hello-world/v1
```

Prefer exact workflow release tags such as `hello-world/v1.2.3` for reproducible
builds. Use moving major tags such as `hello-world/v1` when you want compatible
updates without changing each caller.
