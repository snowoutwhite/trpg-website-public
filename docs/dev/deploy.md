# Deployment

Run the application on one host with Docker Compose. Requests pass through Caddy (HTTPS), Nginx (static assets and protected file delivery), and Django. PostgreSQL stores application data; Redis shares caches and rate limits between workers. A scheduler runs maintenance commands hourly.

## Requirements

- Docker Engine with the Compose and Buildx plugins.
- uv with Python 3.12 for the secret-generation example and local development.
- Node.js compatible with the pinned Vite dependency (see `frontend/package-lock.json`) and npm.
- A domain pointing to the host, with TCP ports 80 and 443 reachable for HTTPS.
- An SMTP service for account verification and password reset email.

Only Caddy publishes host ports. Keep PostgreSQL, Redis, Nginx, and Django on the internal Compose network. Do not expose the development server to the internet.

## Configuration

From the repository root:

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Edit both local files before starting containers. Never commit them.

The root `.env` controls Compose interpolation: set `SITE_DOMAIN` to your domain, `HTTP_PORT=80`, and `HTTPS_PORT=443`. If you change the PostgreSQL database or user, also set `POSTGRES_DB` and `POSTGRES_USER` here for the health check.

`deploy/django.env` supplies application and PostgreSQL settings:

| Variable | Value |
| --- | --- |
| `DJANGO_SECRET_KEY` | A newly generated random secret; for example, generate one with `uv run --python 3.12 python -c 'import secrets; print(secrets.token_urlsafe(50))'` |
| `DJANGO_ALLOWED_HOSTS` | Your domain, without a URL scheme; comma separate additional hosts |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Your HTTPS origin, for example `https://example.com` |
| `DATABASE_URL` | PostgreSQL URL using service hostname `postgres`; URL encode special characters in credentials |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database, user, and a unique strong password matching `DATABASE_URL` |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`, `EMAIL_PORT` | Your SMTP host and port |
| `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | Match your provider; do not enable both |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP credentials |
| `DEFAULT_FROM_EMAIL` | Sender address verified by your SMTP provider |
| `ACCOUNT_EMAIL_SUBJECT_PREFIX` | An optional site name prefix |

The Compose configuration sets `CACHE_URL=redis://redis:6379/1` for Django and the scheduler. Production settings reject an absent or process-local cache. Use PostgreSQL for production: SQLite does not provide the row locking required for concurrent signups.

`backend/.env` is for local development only; it is not the Compose configuration file. Do not copy production credentials into a development checkout.

If changing `DJANGO_ADMIN_URL` from `manage-console/`, update the corresponding Nginx location in `deploy/nginx.conf` too. Keep its trailing slash. If changing proxy topology, review `DRF_NUM_PROXIES` and `ALLAUTH_TRUSTED_PROXY_COUNT` together; the supplied two-proxy topology uses `2`.

## Build and start

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose ps
docker compose exec django python manage.py check --deploy
docker compose exec django python manage.py createsuperuser
```

Django applies migrations and collects static files on startup. Open your HTTPS domain and sign in. The default administration URL is `/manage-console/`. Confirm that Django, PostgreSQL, and Redis become healthy, and inspect service logs for startup errors.

Initialize a clean site by applying migrations and creating your administrator account. Do not run development data scripts in production. Migrations install default homepage text and rule/tag presets, but do not create member accounts, games, or uploaded media. Use site administration and the homepage editing tools to configure site text, moderation, registration, and content.

Before inviting users, verify registration email, email verification, password reset, sign-in, game signup, file access permissions, and photo removal requests. Test with separate accounts to confirm that private files and anonymous reviews remain private. Verify the health endpoint at `https://example.com/api/v1/health/` and check that plain HTTP redirects to HTTPS.

## Local Compose preview

For an isolated local preview, use `SITE_DOMAIN=127.0.0.1`, `HTTP_PORT=8080`, and `HTTPS_PORT=8443` in the root `.env`. Set matching allowed hosts and trusted origins in `deploy/django.env`. Use a separate database password and secret, and the console email backend only for this local environment. Caddy uses a local certificate; trust its local CA through your operating system or browser for this preview.

Console email logs contain verification and reset links. Treat those logs as sensitive and never publish them.

## Operations

- Update: pull a reviewed revision, rebuild the frontend, then run `docker compose up -d --build`.
- Inspect logs: `docker compose logs -f django` or substitute `caddy`, `nginx`, or `scheduler`.
- Stop: `docker compose down` preserves named volumes. `docker compose down -v` destroys stored data and certificates.
- Back up PostgreSQL, uploaded media, and configuration separately. Encrypt backups, keep a copy off the host, restrict access, and test restoration before relying on them. Never commit database dumps, media archives, logs, or secrets.
- The scheduler runs `games_autoclose`, `reviews_window_closing`, and `announcements_publish_due` hourly. Monitor its logs for failures.
- After a relevant rating calculation update, run `docker compose exec django python manage.py reviews_recalc_levels` to recalculate existing profiles.
- Caddy manages certificate renewal. Preserve its data volume and monitor renewal errors.

Configuration changes, backups, and deployment hardening depend on the hosting environment. Validate changes on a separate installation before applying them to a live community.
