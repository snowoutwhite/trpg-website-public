"""本机开发配置：SQLite、控制台邮件、宽松 Host 限制。绝不用于生产。"""

from .base import *  # noqa: F403
from .base import env  # noqa: F401

DEBUG = env.bool("DJANGO_DEBUG", default=True)

# 开发环境允许缺省一个固定的不安全密钥，方便直接 `uv run python manage.py runserver`。
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-do-not-use-in-production")

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "0.0.0.0", "[::1]"],
)
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"],
)

EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# 开发期方便调试：允许 DRF 可浏览 API。
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}
