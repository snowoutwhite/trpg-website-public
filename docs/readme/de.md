# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Eine selbst gehostete Website für Pen-&-Paper-Rollenspielgemeinschaften (TRPG). Sie verbindet Ausschreibungen, Anmeldungen, Charakterbögen, Bewertungen und Spielberichte mit getrennten Rollen für Administration, Spielleitung und Spieler.

> Die sechs Sprachen betreffen die Dokumentation. Die Anwendung ist überwiegend auf Chinesisch.

## Funktionen

| Modul | Funktionen |
| --- | --- |
| Konten und Profile | Registrierung, Bestätigung und Passwortwiederherstellung per E-Mail; getrennte Spieler- und Spielleitungsprofile mit Vorstellung, Vorlieben und Statistiken. |
| Spielverwaltung | Online- und Präsenzrunden mit Regeln, Terminen, Plätzen und Anforderungen; Anmeldung nach Eingangsreihenfolge oder manueller Auswahl, Charakterabgabe, Freigabe, Rücktritt und Abschluss. |
| Charakterbögen | Öffentliche oder private Dateien mit Nutzungshistorie; öffentliche Bögen ansehen und nach Anmeldung herunterladen. |
| Bewertungen | Anonyme Bewertungen mit Pflichttext bei positiven und negativen Stimmen; fehlende Bewertungen fließen gemäß den Regeln ein. Getrennte Stufen für Spieler und Spielleitung, verzögerte Anzeige und Sichtbarkeitsregeln. |
| Aktivitätsberichte | Fotoalben je Runde, Moderation und Meldungen; Markdown-Spielberichte mit Anhängen, Freigabe und Textimport aus DOCX/TXT. |
| Ressourcen und Anleitungen | Artikel, Dateien, Links, Einsteigerhilfen, Glossar und FAQ mit getrennten Download- und Verwaltungsrechten. |
| Benachrichtigungen und Verwaltung | Interne und optionale E-Mail-Mitteilungen, Ankündigungen, Bearbeitung von Startseitentexten und Bildern sowie Verwaltungsoberfläche. |

Ablauf: registrieren und Profil ergänzen → Runde finden und anmelden → Charakterbogen einreichen → Anwesenheit bestätigen und abschließen → Bewertungen, Fotos und Berichte.

## Technologien

| Modul | Funktionen |
| --- | --- |
| Backend | Python 3.12, Django 5.2, Django REST Framework, django-allauth headless; E-Mail und Sitzungen |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router |
| Inhalte | marked und DOMPurify; Mammoth und markdownify; Pillow |
| Daten und Cache | PostgreSQL und Redis im Produktivbetrieb; lokal standardmäßig SQLite |
| Bereitstellung | Docker Compose: Caddy → Nginx → Gunicorn/Django, PostgreSQL, Redis und Scheduler |

## Projektstruktur

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

Domänen: `accounts` / `profiles` (Konten), `games` (Runden), `reviews` (Bewertungen), `gallery` / `reports` (Aktivitäten), `charactercards` / `resources` / `content` (Inhalte), `notifications` / `homecontent` / `siteconfig` (Mitteilungen und Einstellungen). `points` stellt ein Punktekonto bereit, keine vollständige Oberfläche für Level, Titel oder Einlösungen.

## Voraussetzungen

Entwicklung: uv, Python 3.12, Node.js 22.13+ (22.x) und npm. Container: Docker Engine, Compose und Buildx. Produktion: Domain und SMTP-Dienst.

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
