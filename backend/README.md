# Backend

Django 5.2, Django REST Framework, and django-allauth headless authentication. Email is the account identifier. Production uses PostgreSQL and Redis.

For local development, install uv and use Python 3.12:

```sh
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

The default local URL is `http://127.0.0.1:8000`; administration is at `/manage-console/`. Local development defaults to SQLite and console email. Optional local settings belong in `backend/.env`, using `.env.example` as a template. Never commit real configuration or user data.

Checks:

```sh
uv run pytest
uv run ruff check .
```

See [deployment instructions](../docs/dev/deploy.md) for Docker Compose and production configuration.
