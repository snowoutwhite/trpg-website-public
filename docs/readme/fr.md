# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Un site auto-hébergé pour les communautés de jeux de rôle sur table (TRPG). Il rassemble recrutement, inscriptions, fiches, évaluations et comptes rendus, avec des rôles distincts pour l’administration, les MJ et les joueurs.

> Ce projet s’adresse aux communautés de jeux de rôle d’au moins cinq personnes. Les étiquettes personnalisables permettent aussi d’organiser des groupes dans des boutiques de jeux de société et des contextes similaires.

## Fonctionnalités

| Module | Fonctions |
| --- | --- |
| Comptes et profils | Inscription, vérification et récupération par courriel ; profils séparés de joueur et de MJ, présentations, préférences et statistiques. |
| Gestion des parties | Parties en ligne ou en présentiel, règles, horaires, places et critères ; inscription par ordre d’arrivée ou sélection manuelle, dépôt de fiche, validation, retrait et clôture. |
| Fiches de personnages | Fichiers publics ou privés et historique d’utilisation ; consultation des fiches publiques et téléchargement après connexion. |
| Évaluations | Évaluations anonymes avec texte obligatoire pour les avis positifs et négatifs ; les absences d’avis entrent dans le calcul selon les règles. Niveaux distincts joueur/MJ, affichage différé et contrôles de visibilité. |
| Archives des activités | Albums par partie, modération et signalements ; comptes rendus Markdown avec pièces jointes, validation et import du texte DOCX/TXT. |
| Ressources et guides | Articles, fichiers, liens, guides débutants, glossaire et FAQ, avec permissions distinctes de téléchargement et de gestion. |
| Notifications et administration | Notifications internes et courriels facultatifs, annonces, édition des textes et images d’accueil et interface d’administration. |

Parcours : inscription et profil → recherche et inscription à une partie → fiche et validation → présence et clôture → évaluations, photos et comptes rendus.

## Technologies

| Module | Fonctions |
| --- | --- |
| Backend | Python 3.12, Django 5.2, Django REST Framework, django-allauth headless ; courriel et sessions |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router |
| Contenu | marked et DOMPurify ; Mammoth et markdownify ; Pillow |
| Données et cache | PostgreSQL et Redis en production ; SQLite local par défaut |
| Déploiement | Docker Compose : Caddy → Nginx → Gunicorn/Django, PostgreSQL, Redis et ordonnanceur |

## Structure du projet

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

Domaines : `accounts` / `profiles` (comptes), `games` (parties), `reviews` (évaluations), `gallery` / `reports` (activités), `charactercards` / `resources` / `content` (contenu), `notifications` / `homecontent` / `siteconfig` (notifications et réglages). `points` fournit un registre de points, sans interface complète de niveaux, titres ou échange.

## Prérequis

Développement : uv, Python 3.12, Node.js 22.13+ (22.x) et npm. Conteneurs : Docker Engine, Compose et Buildx. Production : domaine et service SMTP.

## Développement local

Commencez chaque bloc de commandes à la racine du dépôt. Le développement utilise par défaut SQLite et l'envoi des courriels dans la console ; les liens de vérification apparaissent dans le terminal du backend. N'exposez pas les serveurs de développement à Internet.

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Dans un autre terminal, lancez le frontend depuis la racine :

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Ouvrez `http://localhost:5173`. Le backend utilise par défaut `http://127.0.0.1:8000`, l'administration se trouve à `/manage-console/` (modifiable avec `DJANGO_ADMIN_URL`) et le contrôle d'état à `/api/v1/health/`.

## Déploiement en production

Copiez les modèles publics puis renseignez les valeurs propres à votre installation :

[Configuration complète du déploiement](../dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Avant le démarrage, configurez une `DJANGO_SECRET_KEY` aléatoire et unique, les identifiants de base de données, `DJANGO_ALLOWED_HOSTS`, les origines HTTPS de `DJANGO_CSRF_TRUSTED_ORIGINS`, l'envoi des courriels et `SITE_DOMAIN` dans la configuration racine. `DATABASE_URL` doit correspondre au service PostgreSQL de Compose ; placez `POSTGRES_DB`, `POSTGRES_USER` et `POSTGRES_PASSWORD` dans `deploy/django.env`. Compose configure Redis pour l'application.

Utilisez les paramètres de production et HTTPS ; ne rendez pas PostgreSQL ou Redis accessibles au public. Vérifiez `DRF_NUM_PROXIES` et `ALLAUTH_TRUSTED_PROXY_COUNT` lorsque la topologie des proxys change. Ne publiez pas de configurations réelles, bases de données, fichiers téléversés, sauvegardes ou journaux. Définissez la sauvegarde et la restauration des données et médias, ainsi que la modération des photos et le traitement des données personnelles.

Compilez d'abord le frontend. Au démarrage, le conteneur applique les migrations et collecte les fichiers statiques. Après le premier démarrage, créez un administrateur :

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## Vérifications de développement

Exécutez chaque bloc depuis la racine. Ce sont des commandes de vérification disponibles, pas une affirmation que cette version a réussi toutes les vérifications.

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

Le contrôle XSS de `npm run security` nécessite Chrome/Chromium. En cas d'échec de détection, définissez `XSS_CHECK_BROWSER` avec le chemin de l'exécutable.

## Licence

[MIT](../../LICENSE)
