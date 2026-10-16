# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Un sito autogestito per comunità di giochi di ruolo da tavolo (TRPG). Riunisce reclutamento, iscrizioni, schede, valutazioni e resoconti, con ruoli distinti per amministratore, GM e giocatori.

> Le sei lingue riguardano la documentazione. L’interfaccia applicativa è prevalentemente in cinese.

## Funzionalità

| Modulo | Funzioni |
| --- | --- |
| Account e profili | Registrazione, verifica e recupero via email; profili separati per giocatori e GM con presentazione, preferenze e statistiche. |
| Gestione delle sessioni | Sessioni online o dal vivo, regole, orari, posti e requisiti; iscrizioni in ordine di arrivo o selezione manuale, consegna schede, approvazione, ritiro e chiusura. |
| Schede personaggio | File pubblici o privati e cronologia di utilizzo; consultazione delle schede pubbliche e download dopo accesso. |
| Valutazioni | Valutazioni anonime con testo obbligatorio per voti positivi e negativi; le mancate valutazioni entrano nel calcolo secondo le regole. Fasce separate per giocatori e GM, pubblicazione differita e visibilità controllata. |
| Registri delle attività | Album per sessione, moderazione e segnalazioni; resoconti Markdown con allegati, revisione e importazione del testo da DOCX/TXT. |
| Risorse e guide | Articoli, file, collegamenti, guide iniziali, glossario e FAQ, con permessi distinti di download e gestione. |
| Notifiche e amministrazione | Notifiche interne ed email opzionali, annunci, modifica di testi e immagini della home e pannello amministrativo. |

Flusso tipico: registrazione e profilo → ricerca e iscrizione → scheda e approvazione → conferma presenze e chiusura → valutazioni, foto e resoconti.

## Tecnologie

| Modulo | Funzioni |
| --- | --- |
| Backend | Python 3.12, Django 5.2, Django REST Framework, django-allauth headless; email e sessioni |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router |
| Contenuti | marked e DOMPurify; Mammoth e markdownify; Pillow |
| Dati e cache | PostgreSQL e Redis in produzione; SQLite locale predefinito |
| Distribuzione | Docker Compose: Caddy → Nginx → Gunicorn/Django, PostgreSQL, Redis e scheduler |

## Struttura del progetto

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

Domini: `accounts` / `profiles` (account), `games` (sessioni), `reviews` (valutazioni), `gallery` / `reports` (attività), `charactercards` / `resources` / `content` (contenuti), `notifications` / `homecontent` / `siteconfig` (notifiche e impostazioni). `points` offre un registro dei punti, non una completa interfaccia di livelli, titoli o riscatti.

## Requisiti

Sviluppo: uv, Python 3.12, Node.js 22.13+ (22.x) e npm. Container: Docker Engine, Compose e Buildx. Produzione: dominio e servizio SMTP.

## Sviluppo locale

Esegui ogni blocco dalla radice del repository. Lo sviluppo usa SQLite e posta su console per impostazione predefinita; i link di verifica compaiono nel terminale del backend. Non esporre i server di sviluppo a Internet.

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

In un altro terminale, avvia il frontend dalla radice:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Apri `http://localhost:5173`. Il backend usa `http://127.0.0.1:8000`; l'amministrazione si trova su `/manage-console/` (configurabile con `DJANGO_ADMIN_URL`) e lo stato su `/api/v1/health/`.

## Distribuzione in produzione

Copia i modelli pubblici e inserisci i valori della tua installazione:

[Configurazione completa del deployment](../dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Imposta una `DJANGO_SECRET_KEY` casuale e univoca, credenziali del database, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` con HTTPS, invio email e `SITE_DOMAIN` nella configurazione radice. `DATABASE_URL` deve corrispondere al servizio PostgreSQL di Compose; inserisci `POSTGRES_DB`, `POSTGRES_USER` e `POSTGRES_PASSWORD` in `deploy/django.env`. Compose configura Redis per l'applicazione.

Usa le impostazioni di produzione e HTTPS; non esporre PostgreSQL o Redis a Internet. Controlla `DRF_NUM_PROXIES` e `ALLAUTH_TRUSTED_PROXY_COUNT` quando cambia la struttura dei proxy. Non pubblicare configurazioni reali, database, caricamenti, backup o log. Definisci procedure di backup e ripristino per database e file, oltre a regole di moderazione delle foto e trattamento dei dati personali.

Compila prima il frontend. All'avvio, il container esegue le migrazioni e raccoglie i file statici. Dopo il primo avvio, crea un amministratore:

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## Controlli di sviluppo

Esegui ogni blocco dalla radice. Questi sono comandi disponibili, non una dichiarazione che la versione abbia superato tutti i controlli.

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

Il controllo XSS di `npm run security` richiede Chrome/Chromium. Se non viene rilevato, imposta `XSS_CHECK_BROWSER` sul percorso dell'eseguibile.

## Licenza

[MIT](../../LICENSE)
