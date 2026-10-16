"""测试配置：内存 SQLite、locmem 邮件、快速密码哈希。"""

from .base import *  # noqa: F403
from .base import BASE_DIR, REST_FRAMEWORK, env  # noqa: F401

DEBUG = False
SECRET_KEY = "test-only-secret-key"  # nosec - 仅测试进程内使用
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# 加速测试：不走 PBKDF2。
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# 每个测试用独立的内存缓存，避免限速计数跨用例串味（配合 conftest 的 cache.clear）。
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "trpg-test",
    }
}

MEDIA_ROOT = BASE_DIR / ".pytest-media"
PROTECTED_MEDIA_ROOT = MEDIA_ROOT / PROTECTED_MEDIA_DIRNAME  # noqa: F405
USE_X_ACCEL_REDIRECT = False

# 测试里不希望 DRF 的通用限速干扰功能用例；注册限速由 allauth 自己的计数负责，单独测。
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "anon": None,
        "user": None,
        "upload": None,
        "gm_application": None,
        "nickname_change": None,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
