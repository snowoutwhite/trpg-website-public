"""生产配置：默认关调试、强制安全 Cookie 与 HSTS，所有敏感值必须来自环境变量。"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import env  # noqa: F401

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured("生产环境必须设置 DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("生产环境必须设置 DJANGO_ALLOWED_HOSTS")

# 显式重读：dev.py 为本机 Vite dev server 预置了 http://localhost:5173 等来源，
# 这里重新从环境变量取一遍，保证那些开发来源绝不会顺着继承链漏进生产。
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# --- 缓存：多 worker 必须共享（缺陷 D1） ---
# 生产是 gunicorn 多 worker（compose 与 Dockerfile 都是 --workers 3）。
# 注册/登录限速计数（ACCOUNT_RATE_LIMITS）与 siteconfig 单例都存在 Django cache 里：
#   - locmem 每个 worker 一份 → `5/h/ip` 实际变成 `15/h/ip`，需求 7c 的注册限速直接打折；
#   - 站主在后台改开关只有处理那次请求的 worker 立刻生效，其余最长 300 秒后才跟上。
# 所以这里宁可拒绝启动，也不让它悄悄退化成 locmem。
_PER_PROCESS_CACHE_BACKENDS = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
)
if not env("CACHE_URL", default=""):
    raise ImproperlyConfigured(
        "生产环境必须设置 CACHE_URL（指向 Redis，例如 redis://redis:6379/1）："
        "多 worker 下进程内缓存会把注册限速放大成 N 倍，站级配置也不会立刻全站生效。"
        "docker-compose.yml 已内置 redis 服务。"
    )
CACHES = {"default": env.cache_url("CACHE_URL")}
if CACHES["default"]["BACKEND"] in _PER_PROCESS_CACHE_BACKENDS:
    raise ImproperlyConfigured(
        f"生产环境的 CACHE_URL 不能用进程内缓存（当前 {CACHES['default']['BACKEND']}）："
        "多 worker 之间不共享，限速与站级配置都会失真。请指向 Redis。"
    )

# --- Cookie ---
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False  # 前端要读它写 X-CSRFToken 头
CSRF_COOKIE_SAMESITE = "Lax"

# --- 传输安全 ---
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- 其他响应头 ---
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# 生产走 Nginx internal location 下发私密文件。
USE_X_ACCEL_REDIRECT = env.bool("USE_X_ACCEL_REDIRECT", default=True)

# --- 限速的客户端识别 ---
# 部署拓扑是 Caddy（TLS）→ Nginx → gunicorn，两层可信代理：REMOTE_ADDR 永远是 Nginx，
# X-Forwarded-For = "客户端, Caddy"（Caddy 丢弃外部自带的 XFF 后写入客户端 IP，Nginx 再追加一跳），
# 真实客户端 IP 在倒数第二段，所以两边都填 2。
# 不设这两项的后果：DRF 会信任整条伪造的 XFF（限速形同虚设），
# 而 allauth 会把全站所有人算成同一个 IP（注册限速被放大成全站 5 次/小时）。
# 改部署拓扑（去掉 Caddy 直接用别的终结点、多加一层 CDN/LB）时这两个数必须同步改。
NUM_PROXIES = env.int("DRF_NUM_PROXIES", default=2)
ALLAUTH_TRUSTED_PROXY_COUNT = env.int("ALLAUTH_TRUSTED_PROXY_COUNT", default=2)

# 生产不暴露可浏览 API。
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "NUM_PROXIES": NUM_PROXIES,
}
