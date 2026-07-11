# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability):

1. Go to the **Security** tab of the
   [DevFlows repository](https://github.com/QuanTizEd8/DevFlows/security).
2. Choose **Report a vulnerability**.

Do not open a public issue for a security report. We will acknowledge the
report, investigate, and coordinate a fix and disclosure with you.

## Scope and trust model

DevFlows publishes reusable GitHub Actions workflows that other repositories
call. Understanding what is trusted helps set expectations for reports.
Consumers should also read the catalog-wide
[security model](https://quantized8.github.io/DevFlows/user-guide/security-model.html),
which documents the injection-resistance, credential, and integrity guarantees
in detail.

- **Caller-supplied inputs and secrets are treated as untrusted.** Workflows
  pass untrusted strings through environment variables or structured arguments
  rather than interpolating them into shell commands, validate paths before
  writing files, and avoid `eval`.
- **Workflows run with least privilege.** They declare explicit top-level
  permissions and isolate write credentials (for example, repository writeback
  runs in a separate job with `contents: write` while the main tool job stays
  read-only).
- **Third-party actions are pinned** to specific commit SHAs.
- **The caller controls the security boundary.** A consumer is responsible for
  which repository and ref they check out, which secrets they pass, and how they
  gate the workflow on pull requests from forks. Sending broad or privileged
  secrets to a workflow that does not need them is outside our control.

Findings that are especially in scope include command or expression injection,
path-traversal in file handling, privilege escalation beyond a workflow's
declared permissions, secret exposure, forgery of build-provenance or PEP 740
attestations, and trusted-publisher or OIDC misconfiguration (for example a
workflow minting or accepting a token for an unintended audience or index).

## Supported versions

DevFlows is **pre-release**. Only the latest state of the `main` branch and the
latest published release line of each workflow receive security fixes. There are
no long-term support branches for older versions yet. Once versions are
published, this section will list the supported per-workflow release lines.
