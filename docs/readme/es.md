# trpg-website

[中文](../../README.md) · [English](en.md) · [Español](es.md) · [Italiano](it.md) · [Deutsch](de.md) · [Français](fr.md)

Un sitio autohospedado para comunidades de juegos de rol de mesa (TRPG). Reúne convocatorias, inscripciones, fichas, valoraciones y registros de partidas, con funciones diferenciadas para la administración, la dirección de juego y los jugadores.

> Los seis idiomas corresponden a la documentación. La aplicación está principalmente en chino.

## Funciones principales

| Módulo | Funciones |
| --- | --- |
| Cuentas y perfiles | Registro, verificación y recuperación por correo; perfiles separados de jugador y director con presentación, preferencias y estadísticas. |
| Gestión de partidas | Partidas presenciales o en línea, reglas, horarios, aforo y requisitos; inscripción por orden de llegada o selección manual, entrega de fichas, aprobación, retirada y cierre. |
| Fichas de personaje | Archivos públicos o privados e historial de uso; consulta de fichas públicas y descarga tras iniciar sesión. |
| Valoraciones | Valoraciones anónimas con texto obligatorio para votos positivos y negativos; las no enviadas entran en el cálculo según las reglas. Niveles separados de jugador y director, publicación diferida y controles de visibilidad. |
| Registros de actividad | Álbumes por partida, moderación y denuncias; crónicas Markdown con adjuntos, revisión e importación del texto desde DOCX/TXT. |
| Recursos y guías | Artículos, archivos, enlaces, guías iniciales, glosario y FAQ; permisos diferenciados de descarga y gestión. |
| Avisos y administración | Notificaciones internas y correo opcional, anuncios, edición de textos e imágenes de portada y panel de administración. |

Flujo habitual: registro y perfil → buscar e inscribirse → entregar ficha para aprobación → confirmar asistencia y cerrar → valoraciones, fotos y crónicas.

## Tecnologías

| Módulo | Funciones |
| --- | --- |
| Backend | Python 3.12, Django 5.2, Django REST Framework, django-allauth headless; correo y sesiones |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Vue Router |
| Contenido | marked y DOMPurify; Mammoth y markdownify; Pillow |
| Datos y caché | PostgreSQL y Redis en producción; SQLite local por defecto |
| Despliegue | Docker Compose: Caddy → Nginx → Gunicorn/Django, PostgreSQL, Redis y planificador |

## Estructura del proyecto

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

Dominios: `accounts` / `profiles` (cuentas y perfiles), `games` (partidas), `reviews` (valoraciones), `gallery` / `reports` (registros), `charactercards` / `resources` / `content` (contenido), `notifications` / `homecontent` / `siteconfig` (avisos y configuración). `points` aporta un registro de puntos, no una interfaz completa de niveles, títulos o canjes.

## Requisitos

Desarrollo: uv, Python 3.12, Node.js 22.13+ (22.x) y npm. Contenedores: Docker Engine, Compose y Buildx. Producción: dominio y servicio SMTP.

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
