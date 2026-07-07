# DevFlows

DevFlows develops and maintains reusable GitHub Actions workflows as modular,
versioned building blocks.

## Development

Use the devcontainer or install Pixi locally, then run:

```bash
task lint
task test
task docs
```

Promoted workflows live in `workflows/<workflow-id>` and are synced into
`.github/workflows` with:

```bash
devflows sync
```

The inherited workflows copied from the older project are parked in
`workflows/_drafts` until they are reviewed, documented, tested, and promoted.
