# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for anything security-related.

- Use GitHub's private vulnerability reporting on this repository
  (**Security → Report a vulnerability**), or
- email **support@shopivell.com** with the details.

Include what you did, what happened, and the impact you think it has. A minimal
reproduction against a local checkout is ideal. We will acknowledge the report and
tell you whether we consider it in scope.

## Handling of secrets

This repository must never contain credentials. That includes API keys, gateway
tokens, database passwords, SMTP credentials, session secrets and private keys —
in code, in tests, in fixtures, in documentation or in commit history.

- `.env` is git-ignored, and `.env.example` holds only empty or placeholder values.
- If you find a credential in the repository or its history, treat it as
  compromised: report it privately rather than opening an issue with the value.
- Never paste a real key into an issue, a pull request or a screenshot.

## Operational assumptions

If you deploy this yourself, you are responsible for the boundary around it:

- Set a real `SECRET_KEY`; the development fallback is not a secret.
- Keep the agent gateway on a private network. A gateway token that can reach an
  agent runtime is close to shell access inside that container — do not publish
  its port.
- Terminate TLS in front of the API and restrict CORS to the origins you serve.
- Payment provider webhooks must be signature-verified; `TEST_MODE` short-circuits
  payment providers and must not be enabled in production.
