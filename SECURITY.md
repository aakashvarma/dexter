# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.0.x   | Yes       |

## Reporting a vulnerability

If you discover a security issue, please report it responsibly rather than opening a public issue.

**Preferred:** use [GitHub private vulnerability reporting](https://github.com/aakashvarma/dexter/security/advisories/new) on this repository.

**Alternative:** email the maintainer with a description of the issue, steps to reproduce, and any suggested fix. Allow reasonable time for a response before public disclosure.

## Scope

Dexter runs local tool scripts and calls third-party APIs (OpenAI, fal.ai) when you configure API keys. Reports are in scope when they involve:

- Credential leakage or unsafe handling of secrets in the repository or tool scripts
- Arbitrary code execution from untrusted pipeline inputs without user intent
- Supply-chain or dependency issues that affect users of this repository

General pipeline quality issues (bad placement, low critic scores) are not security vulnerabilities — please file a regular [bug report](https://github.com/aakashvarma/dexter/issues/new?template=bug_report.yml) instead.
