# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Eine selbst gehostete Website für Pen-&-Paper-Rollenspielgruppen. Spielleitungen veröffentlichen Spielrunden; Spieler melden sich an, reichen Charakterbögen ein und geben nach dem Spiel anonyme Bewertungen ab.

E-Mail-Registrierung und -Bestätigung, Spieler- und Spielleitungsprofile, Ausschreibungen und Anmeldungen, Charakterbögen, Bewertungen und Reputationsstufen, Fotogalerien, Spielberichte, Ressourcen, Einsteigerhilfen, Glossar, Ankündigungen und Bearbeitung der Startseite.

> Die Links wechseln die Sprache der Dokumentation. Die Anwendung ist derzeit überwiegend auf Chinesisch; diese Übersetzungen ergeben keine sechssprachige Benutzeroberfläche.

Python 3.12, Django 5.2, Django REST Framework, django-allauth; Vue 3, TypeScript, Vite; PostgreSQL und Redis im Produktivbetrieb. Docker Compose umfasst Caddy, Nginx, Gunicorn und geplante Aufgaben.

Benötigt werden uv, Python 3.12, Node.js 22.13+ (22.x) und npm. Für Container werden außerdem Docker und Compose benötigt.

## Lokale Entwicklung

Jeden Befehlsblock im Stammverzeichnis des Repositorys beginnen. Standardmäßig nutzt die Entwicklung SQLite und Konsolen-E-Mails; Bestätigungslinks erscheinen im Backend-Terminal. Entwicklungsserver nicht im Internet bereitstellen.

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Das Frontend in einem weiteren Terminal vom Stammverzeichnis aus starten:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

`http://localhost:5173` öffnen. Das Backend läuft standardmäßig unter `http://127.0.0.1:8000`, die Verwaltung unter `/manage-console/` (über `DJANGO_ADMIN_URL` änderbar), die Statusprüfung unter `/api/v1/health/`.

## Produktivbetrieb

Die öffentlichen Konfigurationsvorlagen kopieren und eigene Werte eintragen:

[Vollständige Bereitstellungskonfiguration](../dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Vor dem Start einen eigenen zufälligen `DJANGO_SECRET_KEY`, Datenbankzugangsdaten, `DJANGO_ALLOWED_HOSTS`, HTTPS-Adressen für `DJANGO_CSRF_TRUSTED_ORIGINS`, E-Mail-Versand und `SITE_DOMAIN` in der Stammkonfiguration setzen. `DATABASE_URL` muss zum PostgreSQL-Dienst in Compose passen; `POSTGRES_DB`, `POSTGRES_USER` und `POSTGRES_PASSWORD` gehören in `deploy/django.env`. Compose konfiguriert Redis für die Anwendung.

Produktionseinstellungen und HTTPS verwenden; PostgreSQL und Redis nicht öffentlich zugänglich machen. Bei Änderungen der Proxy-Struktur `DRF_NUM_PROXIES` und `ALLAUTH_TRUSTED_PROXY_COUNT` prüfen. Keine echten Konfigurationen, Datenbanken, Uploads, Sicherungen oder Protokolle einchecken. Sicherung und Wiederherstellung für Datenbank und Medien sowie Regeln für Fotomoderation und personenbezogene Daten festlegen.

Zuerst das Frontend bauen. Beim Containerstart werden Migrationen ausgeführt und statische Dateien gesammelt. Nach dem ersten Start einen Administrator anlegen:

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## Entwicklungsprüfungen

Jeden Block vom Stammverzeichnis aus ausführen. Dies sind verfügbare Prüfbefehle, keine Zusicherung, dass diese Version alle Prüfungen bestanden hat.

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

Die XSS-Prüfung in `npm run security` benötigt Chrome/Chromium. Falls die Erkennung fehlschlägt, `XSS_CHECK_BROWSER` auf die Browserdatei setzen.

## Lizenz

[MIT](../../LICENSE)
