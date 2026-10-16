# syntax=docker/dockerfile:1
# 后端镜像：uv 多阶段构建。第一阶段只装依赖（可被层缓存），第二阶段只带运行时产物。

# ---------- 构建阶段 ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先只拷依赖清单，源码变动不会让依赖层失效。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# 再拷源码并把项目本身装进虚拟环境。
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- 运行阶段 ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# libpq 供 psycopg 用；Pillow 的 wheel 自带依赖，无需额外系统库。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

RUN mkdir -p /app/media /app/staticfiles && chown -R appuser:appuser /app/media /app/staticfiles

USER appuser
EXPOSE 8000

# 两个头都不能省（2026-09-23 本机部署测试发现的假绿灯）：
#   - X-Forwarded-Proto: https —— 生产 SECURE_SSL_REDIRECT=True，裸 http 探测只拿到 301，
#     而 curl 不加 -L 时 301 也算成功；加了这个头 Django 才真的执行健康检查视图。
#   - Host 取 DJANGO_ALLOWED_HOSTS 的第一项 —— 否则 Host 是 127.0.0.1:8000，被 ALLOWED_HOSTS 拒成 400。
# 最后 grep 一下响应体里的 ok，确保拿到的是视图的 JSON 而不是别的 2xx。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS -H "X-Forwarded-Proto: https" -H "Host: ${DJANGO_ALLOWED_HOSTS%%,*}" \
        http://127.0.0.1:8000/api/v1/health/ | grep -q ok || exit 1

# 生产用 gunicorn；静态文件与媒体由 Nginx 直出，Django 不负责。
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
