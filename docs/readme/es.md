# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Un sitio autohospedado para comunidades de juegos de rol de mesa. Los organizadores publican partidas; los jugadores se inscriben, envían fichas y realizan valoraciones anónimas después de jugar.

Registro y verificación por correo, perfiles de jugadores y directores, convocatorias e inscripciones, fichas de personaje, valoraciones y niveles de reputación, álbumes, crónicas, recursos, guías para principiantes, glosario, anuncios y edición de la portada.

> Los enlaces cambian el idioma de la documentación. La interfaz de la aplicación está principalmente en chino; estas traducciones no ofrecen una interfaz en seis idiomas.

Python 3.12, Django 5.2, Django REST Framework, django-allauth; Vue 3, TypeScript, Vite; PostgreSQL y Redis en producción. Docker Compose incluye Caddy, Nginx, Gunicorn y tareas programadas.

Instala uv, Python 3.12, Node.js 22.13+ (22.x) y npm. El despliegue con contenedores requiere Docker y Compose.

## Desarrollo local

Inicia cada bloque de comandos desde la raíz del repositorio. El desarrollo utiliza SQLite y correo en consola por defecto; los enlaces de verificación aparecen en la terminal del backend. No expongas los servidores de desarrollo a Internet.

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

En otra terminal, inicia el frontend desde la raíz:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Abre `http://localhost:5173`. El backend usa `http://127.0.0.1:8000`; la administración está en `/manage-console/` (configurable con `DJANGO_ADMIN_URL`) y el estado en `/api/v1/health/`.

## Despliegue en producción

Copia las plantillas públicas y configura tus propios valores:

[Configuración completa del despliegue](../dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

Configura una `DJANGO_SECRET_KEY` aleatoria y exclusiva, credenciales de base de datos, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` con HTTPS, envío de correo y `SITE_DOMAIN` en la configuración raíz. `DATABASE_URL` debe corresponder al servicio PostgreSQL de Compose; coloca `POSTGRES_DB`, `POSTGRES_USER` y `POSTGRES_PASSWORD` en `deploy/django.env`. Compose configura Redis para la aplicación.

Utiliza configuración de producción y HTTPS; no expongas PostgreSQL ni Redis a Internet. Revisa `DRF_NUM_PROXIES` y `ALLAUTH_TRUSTED_PROXY_COUNT` al cambiar los proxies. No publiques configuraciones reales, bases de datos, archivos subidos, copias de seguridad ni registros. Define procedimientos de copia y restauración de la base de datos y los archivos, además de normas de moderación de fotos y tratamiento de datos personales.

Compila primero el frontend. Al arrancar, el contenedor ejecuta migraciones y recopila archivos estáticos. Después del primer arranque, crea un administrador:

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## Comprobaciones de desarrollo

Ejecuta cada bloque desde la raíz. Son comandos disponibles, no una afirmación de que esta versión haya superado todas las comprobaciones.

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

La comprobación XSS de `npm run security` requiere Chrome/Chromium. Si no se detecta, configura `XSS_CHECK_BROWSER` con la ruta del ejecutable.

## Licencia

[MIT](../../LICENSE)
