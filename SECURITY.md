# Security policy

Kochab is an experimental local research prototype and is not hardened for untrusted
multi-tenant execution.

## Supported versions

Only the current `main` branch receives security fixes.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository instead of a
public issue:

<https://github.com/hxaxd/kochab/security/advisories/new>

Include the affected command or adapter, a minimal reproduction, and the expected
security boundary. Do not include real API keys, production traces, or private model
inputs and outputs.

## Trust boundary

- Host evaluation commands are trusted code selected during onboarding.
- Evolution models can access only the declared tuning surface, train evaluation port,
  and normalized trace tools.
- Hidden holdout data must remain outside model-visible catalogs, outputs, and traces.
- OTLP input and evaluation output should still be treated as untrusted data at parser
  boundaries.
