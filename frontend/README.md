# Frontend

A Vue 3, TypeScript, and Vite single-page application. It uses session cookies and CSRF protection with a Django backend served from the same origin in production.

Use a Node.js version compatible with the pinned dependencies in `package-lock.json`:

```sh
npm ci
npm run dev
```

Open `http://localhost:5173`. The development proxy forwards API and media requests to `http://127.0.0.1:8000` by default. To change the target, copy `.env.example` to `.env` and set `VITE_API_TARGET`. Never place secrets in frontend environment variables: values used by the application may be included in public browser assets.

Checks and production build:

```sh
npm run typecheck
npm run lint
npm run build
npm run security
```

The build output is `dist/`. The browser-based security checks require Chromium or Chrome. Set `XSS_CHECK_BROWSER` to its executable path if automatic detection does not find it; unavailable browser tooling makes the check fail instead of reporting a pass. See [deployment instructions](../docs/dev/deploy.md) for serving the build with Nginx and Django.
