# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

A self-hosted website for tabletop role-playing (TRPG) communities. It connects game recruitment, sign-ups, character sheets, post-game reviews, and activity records in one system, with separate responsibilities for the site administrator, game masters, and players.

> The six languages apply to project documentation. The application interface is currently mainly Chinese.

## Features

| Module | Capabilities |
| --- | --- |
| Accounts and profiles | Email registration, verification, and password resets; separate player and GM profiles for introductions, preferences, and participation statistics. |
| Game management | Online and offline games with rules, schedules, capacity, and entry requirements; first-come sign-ups or a reviewed player pool, sheet submission, approval, withdrawal, and completion. |
| Character sheets | Upload character files, choose public or private visibility, and track their use. Public sheets can be browsed and downloaded after sign-in. |
| Post-game reviews | Anonymous reviews between participants; positive and negative reviews require text. Missing reviews enter statistics under the rating rules; GM and player tiers are separate, with delayed disclosure and visibility controls. |
| Activity records | Game photo galleries, moderation and reports; Markdown session reports with attachments, publication review, and DOCX/TXT import into the report body. |
| Resources and guides | Articles, files, links, beginner guides, glossary, and FAQ, with separate download and management permissions. |
| Notifications and administration | In-app and optional email notifications, announcements, homepage text/image editing, and administrative tools for content, members, and site settings. |

Typical flow: register and complete a profile → find and join a game → submit a character sheet for GM approval → confirm attendance and finish the game → reviews, photos, and session reports.

## Technology stack

| Module | Capabilities |
| --- | --- |
| Backend | Python 3.12, Django 5.2, Django REST Framework, django-allauth headless (email login and session authentication) |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router |
| Content | marked and DOMPurify for Markdown; Mammoth and markdownify for document import; Pillow for images |
| Data and cache | PostgreSQL and Redis in production; SQLite by default for local development |
| Deployment | Docker Compose: Caddy → Nginx → Gunicorn/Django, plus PostgreSQL, Redis, and a scheduler service |

## Project structure

```text
.
├── backend/
│   ├── apps/
│   ├── common/
│   ├── config/
│   ├── manage.py
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── stores/
│   │   ├── styles/
│   │   └── views/
│   ├── public/
│   └── package.json
├── deploy/
├── docs/
│   ├── dev/deploy.md
│   └── readme/
└── docker-compose.yml
```

Backend domains: `accounts` / `profiles` for identity and profiles; `games` for game management; `reviews` for reviews; `gallery` / `reports` for activity records; `charactercards` / `resources` / `content` for shared content; `notifications` / `homecontent` / `siteconfig` for notifications and site configuration. `points` provides a points ledger foundation, not a complete level, title, or redemption interface.

## Requirements

Local development requires uv, Python 3.12, Node.js 22.13+ (22.x), and npm. Container deployment also needs Docker Engine, Compose, and Buildx. Prepare a domain and an SMTP service for production.

## Local development

Start each command block at the repository root. Development defaults to SQLite and console email; verification links appear in the backend terminal. Do not expose development servers to the internet.

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

In another terminal, start the frontend from the repository root:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://localhost:5173`. The backend defaults to `http://127.0.0.1:8000`, the admin path is `/manage-console/` (configurable with `DJANGO_ADMIN_URL`), and the health endpoint is `/api/v1/health/`.

## Production deployment

Copy the public configuration templates, then supply your own deployment values:

[Full deployment configuration](../dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Before starting, configure a unique random `DJANGO_SECRET_KEY`, database credentials, `DJANGO_ALLOWED_HOSTS`, HTTPS `DJANGO_CSRF_TRUSTED_ORIGINS`, email delivery, and `SITE_DOMAIN` in the root configuration. `DATABASE_URL` must match the Compose PostgreSQL service; put `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in `deploy/django.env`. Compose configures Redis for the application.

Use production settings and HTTPS; keep PostgreSQL and Redis off the public network. Review `DRF_NUM_PROXIES` and `ALLAUTH_TRUSTED_PROXY_COUNT` whenever the proxy topology changes. Never commit real configuration, databases, uploads, backups, or logs. Establish backup and restore procedures for database and media volumes, and configure photo moderation and personal-data handling for your community.

Build the frontend first. Container startup runs migrations and collects static files. After the first startup, create an administrator:

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## Development checks

Run each block from the repository root. These are available check commands, not a claim that this release has passed every check.

```sh
cd backend
uv run pytest
uv run ruff check .
```

```sh
cd frontend
npm run typecheck
npm run lint
npm run build
npm run security
```

The XSS check in `npm run security` requires Chrome/Chromium. If detection fails, set `XSS_CHECK_BROWSER` to the browser executable.

## License

[MIT](../../LICENSE)
