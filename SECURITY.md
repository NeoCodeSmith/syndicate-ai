# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.x | ✅ |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Email: security@neocode.dev (replace with your contact)

We will respond within 72 hours and aim to release a patch within 14 days for critical issues.

## Security Design

- API keys are never logged
- LLM prompts never include raw user-supplied HTML
- All agent outputs are Pydantic-validated before DAG advancement
- Redis data is TTL-bounded
- Docker containers run as non-root (uid 1001)
- Secrets must use `.env` files or a secrets manager — never hardcoded
