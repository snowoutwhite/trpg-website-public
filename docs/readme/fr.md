# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Un site auto-hébergé pour les communautés de jeux de rôle sur table. Les organisateurs publient des parties ; les joueurs s'inscrivent, déposent leurs fiches et échangent des évaluations anonymes après les parties.

Inscription et vérification par courriel, profils de joueurs et de MJ, recrutement et inscriptions, fiches de personnages, évaluations et niveaux de réputation, galeries, comptes rendus, ressources, guides pour débutants, glossaire, annonces et modification de la page d'accueil.

> Les liens changent la langue de la documentation. L'interface de l'application est actuellement principalement en chinois ; ces traductions ne constituent pas une interface en six langues.

Python 3.12, Django 5.2, Django REST Framework, django-allauth ; Vue 3, TypeScript, Vite ; PostgreSQL et Redis en production. Docker Compose comprend Caddy, Nginx, Gunicorn et des tâches planifiées.

Installez uv, Python 3.12, Node.js 22.13+ (22.x) et npm. Le déploiement par conteneurs nécessite aussi Docker et Compose.

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
