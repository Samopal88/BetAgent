# Security Policy

## Secrets

Never commit `.env`, databases, Telegram tokens, payment credentials, JWT secrets, cookies or exported logs. Use `.env.example` only as a list of variable names and safe defaults.

If a secret is exposed, revoke and replace it at the provider. Removing it from the latest commit is not sufficient because Git history and caches may retain the value.

## Reporting a vulnerability

Do not publish credentials or exploitable details in a public issue. Contact the repository owner privately through the GitHub profile before disclosure.

## Deployment baseline

- keep the panel behind HTTPS and strong Basic Auth;
- bind API/panel to localhost behind a reverse proxy;
- restrict PostgreSQL and SQLite filesystem access;
- validate YooKassa webhook authenticity at the network/application boundary;
- run pipeline processes as an unprivileged service account;
- back up databases and test restores;
- treat pickle model files as trusted-code artifacts and never load replacements from unknown sources.

The repository provides a research prototype, not a managed production security guarantee.
