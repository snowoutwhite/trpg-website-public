# trpg-website

[中文](README.md) · [English](docs/readme/en.md) · [Español](docs/readme/es.md) · [Italiano](docs/readme/it.md) · [Deutsch](docs/readme/de.md) · [Français](docs/readme/fr.md)

面向桌面角色扮演社群的自托管网站。组织者可以发布团务，玩家报名、提交角色卡，并在结团后参与匿名互评。

邮箱注册与验证、玩家及 GM 资料卡、招募与报名管理、角色卡池、团后评价与赞级别、活动相册、战报、资源下载、新人指南、术语表、站点公告及首页编辑。

> 本导航切换的是项目文档语言。当前应用界面主要为中文，不代表已提供六语言界面。

Python 3.12、Django 5.2、Django REST Framework、django-allauth；Vue 3、TypeScript、Vite；生产环境使用 PostgreSQL 与 Redis。Docker Compose 包含 Caddy、Nginx、Gunicorn 和定时任务服务。

安装 uv、Python 3.12、Node.js 22.13+（22.x）及 npm。容器部署另需 Docker 与 Compose。

## 本地启动

以下命令均从仓库根目录开始。开发配置默认使用 SQLite 和控制台邮件；邮箱验证链接显示在后端终端。不要将开发服务器暴露到公网。

```sh
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

另开终端，从仓库根目录启动前端：

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

浏览器访问 `http://localhost:5173`。后端默认监听 `http://127.0.0.1:8000`，管理后台位于 `/manage-console/`（可通过 `DJANGO_ADMIN_URL` 修改），健康检查为 `/api/v1/health/`。

## 生产部署

复制公开配置模板，然后填写属于自己部署的值：

[完整部署配置](docs/dev/deploy.md)

```sh
cp .env.example .env
cp backend/.env.example deploy/django.env
```

启动前设置独立随机的 `DJANGO_SECRET_KEY`、数据库凭据、`DJANGO_ALLOWED_HOSTS`、HTTPS 的 `DJANGO_CSRF_TRUSTED_ORIGINS`、邮件发送配置和根配置的 `SITE_DOMAIN`。`DATABASE_URL` 必须匹配 Compose PostgreSQL 服务；`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 放在 `deploy/django.env`。Compose 已为应用配置 Redis。

仅使用生产配置与 HTTPS；保持数据库和 Redis 不对公网开放。改变代理层级时同步核对 `DRF_NUM_PROXIES` 和 `ALLAUTH_TRUSTED_PROXY_COUNT`。不要提交真实配置、数据库、上传文件、备份或日志。为数据库和媒体卷制定备份与恢复流程，按实际用途设置照片审核及用户数据处理规则。

前端先构建；容器启动时自动迁移数据库并收集静态文件。首次启动后创建管理员：

```sh
(cd frontend && npm ci && npm run build)
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

## 开发检查

下面两组命令分别从仓库根目录运行。它们是可执行的检查入口，并非本版本已经通过全部检查的声明。

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

`npm run security` 的 XSS 检查需要 Chrome/Chromium；若自动检测失败，用 `XSS_CHECK_BROWSER` 指定浏览器可执行文件。

## 许可证

[MIT](LICENSE)
