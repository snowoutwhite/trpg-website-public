"""公共配置。

分层约定：本文件只放「所有环境都一样」的东西，环境差异写进 dev/prod/test。
安全相关的值（SECRET_KEY、DEBUG、ALLOWED_HOSTS、数据库、邮件凭据）一律从环境变量读，
变量清单见 `backend/.env.example`。
"""

from pathlib import Path

import environ

# backend/ 目录（config/settings/base.py 往上三层）
BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
# 本机开发时可放 backend/.env；生产由容器环境变量注入。缺文件不报错。
environ.Env.read_env(BASE_DIR / ".env")

# --------------------------------------------------------------------------
# 基础安全项（默认取最严格值，宽松值由 dev/test 显式覆盖）
# --------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# 后台入口路径可配置，默认不是 /admin/，降低被扫描命中的概率。
ADMIN_URL = env("DJANGO_ADMIN_URL", default="manage-console/")

# --------------------------------------------------------------------------
# 应用
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.headless",
]

# 13 个业务域 app，全部注册；尚未实现的先留空壳，保持业务模块独立。
LOCAL_APPS = [
    "apps.siteconfig",
    "apps.homecontent",
    "apps.accounts",
    "apps.profiles",
    "apps.content",
    "apps.resources",
    "apps.charactercards",
    "apps.games",
    "apps.reviews",
    "apps.gallery",
    "apps.reports",
    "apps.points",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # 封禁/停用会话在 allauth headless 侧一律当游客看。必须排在
    # AuthenticationMiddleware 之后；缺了它，被封禁的人还能改密码、加邮箱
    # （认证后端现在允许把封禁号取回来，见 common/middleware.py 的说明）。
    "common.middleware.BlockedAccountAllauthGuard",
    # allauth 0.56+ 必需，缺失会在 system check 阶段报错。
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# 数据库
# --------------------------------------------------------------------------
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    # 自定义后端：在 allauth 基础上额外拒绝被封禁账号登录。
    "apps.accounts.auth_backends.BanAwareAuthenticationBackend",
]

# 只强制最短长度，不做复杂度强制。
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
]

# 会话 30 天。
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # 前端需要读 csrftoken 写进 X-CSRFToken 头
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------
# django-allauth（headless，仅邮箱，无社交登录，无 2FA）
# --------------------------------------------------------------------------
ACCOUNT_LOGIN_METHODS = {"email"}
# headless 的 SignupInput 依据 password1 是否在列表里决定暴露 password 字段。
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_CHANGE_EMAIL = True  # 改邮箱：新地址验证通过后生效
ACCOUNT_MAX_EMAIL_ADDRESSES = 2
ACCOUNT_EMAIL_SUBJECT_PREFIX = env("ACCOUNT_EMAIL_SUBJECT_PREFIX", default="")
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "apps.accounts.forms.SignupExtraFieldsForm"
# allauth 自己的限速也要知道「前面有几层可信代理」。默认 0 = 只认 REMOTE_ADDR，
# X-Forwarded-For 一律不信（allauth 的默认行为，正确但在 Nginx 后面会把全站算成一个 IP）。
ALLAUTH_TRUSTED_PROXY_COUNT = env.int("ALLAUTH_TRUSTED_PROXY_COUNT", default=0)
ACCOUNT_RATE_LIMITS = {
    # 注册限速：同 IP 每小时 N 次（需求 7c）。allauth 用 Django cache 计数。
    "signup": env("ACCOUNT_SIGNUP_RATE_LIMIT", default="5/h/ip"),
    "login": env("ACCOUNT_LOGIN_RATE_LIMIT", default="30/m/ip"),
    "reset_password": env("ACCOUNT_RESET_PASSWORD_RATE_LIMIT", default="20/m/ip,5/m/key"),
}

HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
HEADLESS_SERVE_SPECIFICATION = False  # 需要 headless-spec extra（pyyaml），暂不启用
# 邮件里指向前端 SPA 的路径；HEADLESS_ONLY 下这些键缺一不可。
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": "/auth/verify-email/{key}",
    "account_reset_password": "/auth/password/forgot",
    "account_reset_password_from_key": "/auth/password/reset/{key}",
    "account_signup": "/auth/signup",
}

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    # SessionAuthentication 的子类：只去掉「is_active=False 就当没认出人」那半句，
    # 让封禁/停用的真实会话能被认回来，由权限层给出 403 + 具体 code

    "DEFAULT_AUTHENTICATION_CLASSES": [
        "common.authentication.AccountStateSessionAuthentication",
    ],
    # 默认权限比 DRF 的 IsAuthenticated 多管一件事：账号状态（封禁/注销）。
    # 现存视图都显式写了 permission_classes，这里是给**将来新增的视图**兜底 ——
    # 忘了写权限类时落到的那一格必须也对账号状态把关，不能只有写接口把关。
    "DEFAULT_PERMISSION_CLASSES": [
        "common.permissions.IsAuthenticatedAndActive",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        # 游客限速的速率从 SiteConfig.anon_throttle_per_minute 读（站长后台可调），见 common/throttling.py
        "common.throttling.ConfigurableAnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        # 缺了这一条，视图上写的 throttle_scope（upload / gm_application /
        # nickname_change）不会被任何限速类读取，等于完全没有限速。
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="60/min"),  # 仅兜底：真值在 SiteConfig.anon_throttle_per_minute
        "user": env("THROTTLE_USER", default="300/min"),
        "upload": env("THROTTLE_UPLOAD", default="30/hour"),
        "gm_application": env("THROTTLE_GM_APPLICATION", default="5/day"),
        "nickname_change": env("THROTTLE_NICKNAME_CHANGE", default="10/day"),
    },
    # 可信反向代理层数。DRF 默认值是 None，此时它会把整个 X-Forwarded-For 当成
    # 客户端标识 —— 攻击者随手换个头就能把限速计数重置，等于没限速。
    # 0 = 只认 REMOTE_ADDR（本机直连）；生产在 Nginx 后面改成 1，见 prod.py。
    "NUM_PROXIES": env.int("DRF_NUM_PROXIES", default=0),
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DATETIME_FORMAT": "iso-8601",
}

# --------------------------------------------------------------------------
# 国际化 / 时区
# --------------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# 静态与媒体
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# 受保护文件（私密角色卡、待审照片等）放在这个子目录，绝不由 Nginx 直出。
PROTECTED_MEDIA_DIRNAME = "protected"
PROTECTED_MEDIA_ROOT = MEDIA_ROOT / PROTECTED_MEDIA_DIRNAME
# 生产由 Nginx internal location + X-Accel-Redirect 下发；开发期 Django 直出。
USE_X_ACCEL_REDIRECT = env.bool("USE_X_ACCEL_REDIRECT", default=False)
X_ACCEL_REDIRECT_PREFIX = env("X_ACCEL_REDIRECT_PREFIX", default="/media/protected/")

# 上传限额（单位：字节）
AVATAR_MAX_BYTES = env.int("AVATAR_MAX_BYTES", default=2 * 1024 * 1024)
AVATAR_MAX_SIDE = env.int("AVATAR_MAX_SIDE", default=256)
# 图片像素总数上限：体积挡不住解压炸弹（几百字节的 PNG 可声称有上亿像素）。
IMAGE_MAX_PIXELS = env.int("IMAGE_MAX_PIXELS", default=40_000_000)

DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=20 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int("FILE_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024)

# --------------------------------------------------------------------------
# 邮件
# --------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=465)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=True)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@example.invalid")
SERVER_EMAIL = env("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# --------------------------------------------------------------------------
# 缓存（allauth 限速与 siteconfig 单例缓存都依赖它）
# --------------------------------------------------------------------------
CACHES = {
    "default": env.cache_url(
        "CACHE_URL",
        default="locmemcache://trpg-default",
    )
}

# --------------------------------------------------------------------------
# 日志：只打必要信息，禁止把邮箱/评价人身份写进日志（用户数据红线）。
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", default="INFO")},
}
