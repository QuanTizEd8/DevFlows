# Testing Guide

DevFlows uses layered testing:

- Static validation checks catalog metadata, generated-file drift, GitHub
  Actions syntax, security findings, shell scripts, and formatting.
- Unit tests cover catalog loading, workflow interface extraction, generated
  documentation, and sync behavior.
- Local smoke tests use `act` for workflows that do not require hosted GitHub
  runner behavior.
- Hosted end-to-end tests call promoted reusable workflows from repository CI.

Some workflows, especially release and publishing workflows, require secrets or
GitHub-hosted services. Those tests should be secrets-gated and documented in
the workflow metadata.
