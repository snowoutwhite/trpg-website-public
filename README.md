# trpg-website

[中文](README.md) · [English](docs/readme/en.md) · [Español](docs/readme/es.md) · [Italiano](docs/readme/it.md) · [Deutsch](docs/readme/de.md) · [Français](docs/readme/fr.md)

面向桌面角色扮演（TRPG）社群的自托管网站，将招募、报名、角色卡、结团后的评价与活动记录放在同一套系统中。适合由站主管理、GM 组织活动、玩家持续参与的社群。

> 本项目适用于至少5人的跑团社群，若活用标签定制功能，也可用于桌游店组团等使用场景。

## 主要功能

| 模块 | 功能 |
| --- | --- |
| 账号与个人资料 | 邮箱注册、验证与密码重置；玩家卡和 GM 卡分别记录个人介绍、偏好、参团或主持经历。 |
| 招募与团务 | 发布线上或线下活动，设置规则、时间、人数和报名门槛；支持先到先得或候选玩家池审核，以及交卡、审批、退出和结团。 |
| 角色卡 | 上传具体人物的角色卡文件，设置公开或私密，记录使用情况；公开卡池支持浏览及登录后下载。 |
| 团后评价 | 同团成员匿名互评，赞与倒赞需附文字；未评价按规则计入统计，GM 与玩家侧分开计算赞级别，并有延迟展示与可见性限制。 |
| 活动记录 | 团相册、照片审核与举报；Markdown 战报、附件、发布审核，以及 DOCX/TXT 导入正文。 |
| 资源与知识 | 文章、文件和链接资源；新人指南、术语表及 FAQ；资源下载与管理权限分开控制。 |
| 通知与管理 | 站内通知、可选邮件通知、站点公告；站主可在首页直接改字换图，并通过管理后台维护内容、成员和站级设置。 |

典型流程：注册并完善资料 → 浏览招募并报名 → 提交角色卡并由 GM 审核 → 确认到场与结团 → 团后评价、相册与战报。

## 技术栈

| 模块 | 功能 |
| --- | --- |
| 后端 | Python 3.12、Django 5.2、Django REST Framework、django-allauth headless（邮箱登录、会话认证） |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Vue Router |
| 内容处理 | marked 与 DOMPurify 渲染 Markdown；Mammoth 与 markdownify 导入文档；Pillow 处理图片 |
| 数据与缓存 | 生产使用 PostgreSQL 和 Redis；本地开发默认 SQLite |
| 部署 | Docker Compose：Caddy → Nginx → Gunicorn/Django，另含 PostgreSQL、Redis 与定时任务容器 |

## 项目结构

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

后端按业务域拆分：`accounts` / `profiles`（账号与资料）、`games`（团务）、`reviews`（评价）、`gallery` / `reports`（相册与战报）、`charactercards` / `resources` / `content`（角色卡、资源与知识）、`notifications` / `homecontent` / `siteconfig`（通知与站点配置）。`points` 提供积分记录基础，不代表已有完整的等级、称号或兑换界面。

## 环境要求

本地开发需要 uv、Python 3.12、Node.js 22.13+（22.x）与 npm；容器部署另需 Docker Engine、Compose 和 Buildx。生产部署需准备域名和 SMTP 发信服务。

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
