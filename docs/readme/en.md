# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

A self-hosted website for tabletop role-playing communities. Organizers publish games; players sign up, submit character sheets, and exchange anonymous reviews after games.

Email registration and verification, player and GM profiles, recruitment and sign-ups, character-sheet sharing, post-game reviews and reputation tiers, photo galleries, session reports, resources, beginner guides, glossary, announcements, and homepage editing.

> The links switch documentation languages. The application interface is currently mainly Chinese; these translations do not provide a six-language interface.

Python 3.12, Django 5.2, Django REST Framework, django-allauth; Vue 3, TypeScript, Vite; PostgreSQL and Redis for production. Docker Compose includes Caddy, Nginx, Gunicorn, and scheduled jobs.

Install uv, Python 3.12, Node.js 22.13+ (22.x), and npm. Container deployment also requires Docker and Compose.

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
