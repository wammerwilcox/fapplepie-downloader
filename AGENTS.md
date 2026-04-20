# AI Coding Agent Guidelines

Guidelines for AI coding agents working on Fapplepie Downloader.

## Project Context

- Language: Python 3.11+
- Deployment: Docker, Docker Compose, cron, or standalone Python
- Architecture: single-file Python app with shell wrappers and Docker orchestration
- Runtime state: generated URL lists, cache, logs, and downloads are local-only and ignored by Git

## Repository Layout

```text
fapplepie-downloader/
├── app/
│   ├── scraper.py
│   ├── daily_download.sh
│   ├── entrypoint.sh
│   ├── requirements.in
│   ├── requirements.txt
│   ├── processed_cache.example.json
│   └── video_urls.example.txt
├── docs/
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
└── README.md
```

## Critical Files

Do not commit active runtime state or secrets:

- `app/cache/processed_cache.json`
- `app/video_urls.txt`
- `app/cache/`
- `app/downloads/`
- `app/logs/`
- `.env` files

Safe source templates are kept in:

- `app/processed_cache.example.json`
- `app/video_urls.example.txt`

## Code Standards

- Follow PEP 8 with 4-space indentation.
- Prefer type hints for new function signatures.
- Keep network failures recoverable and logged with context.
- Use module-level logging rather than ad hoc prints for new operational messages.
- Keep shell scripts on `#!/usr/bin/env bash` with `set -euo pipefail`.

## Testing

Run these checks before publishing changes:

```bash
python3 -m py_compile app/scraper.py
python3 -m pytest
docker build -t fapplepie-downloader-public-test .
docker compose config
```

When changing scraper behavior, also test invalid URLs, cache loading/saving, proxy configuration, and network failure paths where practical.

## Security

- Never commit credentials, tokens, cookies, target lists, generated caches, logs, or downloaded media.
- Keep proxy credentials in environment variables.
- Search staged changes for likely secrets before committing.

```bash
git diff --staged | grep -E "(password|api[_-]?key|secret|token|bearer)" -i
```

## Git Workflow

- Use short-lived branches for features, fixes, refactors, and documentation updates.
- Use Conventional Commits where practical.
- Keep commits focused and avoid mixing unrelated docs, behavior, and configuration changes.
- Before opening a public PR, confirm the branch does not contain private registry URLs, personal identifiers, runtime state, or credentials.
