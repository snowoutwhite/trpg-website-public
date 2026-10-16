"""对抗性测试 · 配置层：限速档是否真的生效、CSRF、未鉴权路由普查、后台路径、受保护媒体。"""

from __future__ import annotations

import importlib
import io

import pytest
from django.conf import settings as django_settings
from django.test import override_settings
from django.urls import URLPattern, URLResolver, clear_url_caches, get_resolver
from PIL import Image
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

ALLAUTH = "/_allauth/browser/v1"


@pytest.fixture
def throttle_rates(monkeypatch):
    """只打开指定的限速档。

    注意：`override_settings(REST_FRAMEWORK=...)` 对限速**无效** ——
    `SimpleRateThrottle.THROTTLE_RATES` 是在类定义时就绑定好的那个 dict，
    settings 换了它也不跟着换。必须直接替换这个类属性。
    """

    def apply(**rates):
        base = {
            "anon": None,
            "user": None,
            "upload": None,
            "gm_application": None,
            "nickname_change": None,
        }
        base.update(rates)
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", base)

    return apply


def _png(size=(32, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(name: str, data: bytes, content_type: str = "image/png"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, data, content_type=content_type)


# ------------------------------------------------- throttle_scope 是否真的生效


def test_scoped_throttle_class_is_installed():
    """视图上写了 throttle_scope，但默认限速类里没有 ScopedRateThrottle 的话，全是摆设。"""
    classes = django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]
    assert any("ScopedRateThrottle" in path for path in classes), (
        f"throttle_scope 不会被任何限速类读取：{classes}"
    )


def test_every_declared_throttle_scope_has_a_rate():
    """所有视图上声明的 throttle_scope 都必须在 DEFAULT_THROTTLE_RATES 里有配额，
    否则 DRF 会在运行期抛 ImproperlyConfigured（500），而不是限速。"""
    from rest_framework.settings import api_settings

    declared = set()
    for pattern in _flatten(get_resolver().url_patterns):
        view_class = getattr(pattern.callback, "cls", None) or getattr(
            pattern.callback, "view_class", None
        )
        scope = getattr(view_class, "throttle_scope", None)
        if isinstance(scope, str) and scope:
            declared.add(scope)

    assert declared, "没有采集到任何 throttle_scope，用例本身失效"
    missing = declared - set(api_settings.DEFAULT_THROTTLE_RATES)
    assert not missing, f"以下限速档没有配额定义：{sorted(missing)}"


def test_gm_application_scope_actually_throttles(api_client, user_factory, throttle_rates):
    throttle_rates(gm_application="2/day")
    user = user_factory(nickname="刷申请")
    api_client.force_authenticate(user)
    codes = [
        api_client.post(
            "/api/v1/accounts/me/gm-application/", {"reason": f"第{i}次"}, format="json"
        ).status_code
        for i in range(4)
    ]
    assert 429 in codes, f"gm_application 限速档没有生效：{codes}"


def test_upload_scope_actually_throttles(api_client, user_factory, throttle_rates):
    throttle_rates(upload="2/hour")
    user = user_factory(nickname="刷头像")
    api_client.force_authenticate(user)
    codes = []
    for i in range(4):
        codes.append(
            api_client.post(
                "/api/v1/accounts/me/avatar/",
                {"avatar": _upload(f"a{i}.png", _png())},
                format="multipart",
            ).status_code
        )
    assert 429 in codes, f"upload 限速档没有生效：{codes}"


def test_nickname_scope_actually_throttles(api_client, user_factory, throttle_rates):
    throttle_rates(nickname_change="2/day")
    user = user_factory(nickname="刷改名")
    api_client.force_authenticate(user)
    codes = [
        api_client.post(
            "/api/v1/accounts/me/nickname/", {"nickname": f"改名{i}"}, format="json"
        ).status_code
        for i in range(4)
    ]
    assert 429 in codes, f"nickname_change 限速档没有生效：{codes}"


def test_anon_throttle_not_bypassed_by_forged_xff(api_client, throttle_rates):
    """游客限速必须锚在 REMOTE_ADDR（或可信代理数），不能被 X-Forwarded-For 任意重置。

    2026-09-22 起游客速率真值在 `SiteConfig.anon_throttle_per_minute`（站长后台可调），
    settings 里的 `anon` 只是开关与兜底，所以这里两处都设。
    """
    from apps.siteconfig.services import clear_config_cache, get_config

    throttle_rates(anon="3/min")
    config = get_config()
    config.anon_throttle_per_minute = 3
    config.save(update_fields=["anon_throttle_per_minute", "updated_at"])
    clear_config_cache()
    codes = []
    for i in range(6):
        codes.append(
            api_client.get(
                "/api/v1/siteconfig/", HTTP_X_FORWARDED_FOR=f"203.0.113.{i}"
            ).status_code
        )
    assert 429 in codes, f"伪造 XFF 绕过了 anon 限速：{codes}"


# ------------------------------------------------------------------- CSRF


def _login_with_csrf(client: APIClient, email: str, password: str = "testpass1234"):
    client.get(f"{ALLAUTH}/auth/session")  # 拿 csrftoken Cookie
    token = client.cookies["csrftoken"].value
    response = client.post(
        f"{ALLAUTH}/auth/login",
        {"email": email, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    return response, client.cookies["csrftoken"].value


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/v1/notifications/read/", {}),
        ("patch", "/api/v1/notifications/preference/", {"email_enabled": True}),
        ("patch", "/api/v1/accounts/me/", {"nickname": "跨站改名"}),
        ("post", "/api/v1/accounts/me/nickname/", {"nickname": "跨站改名"}),
        ("post", "/api/v1/accounts/me/gm-application/", {"reason": "跨站申请"}),
        ("post", "/api/v1/accounts/me/deactivate/", {}),
        ("patch", "/api/v1/profiles/me/player-card/", {"taboos": "跨站写入"}),
        ("delete", "/api/v1/accounts/me/avatar/", {}),
    ],
)
def test_unsafe_methods_require_csrf_token(user_factory, method, path, body):
    """会话认证下的写操作没有 CSRF token 一律必须被拒。"""
    user_factory(email="csrf@example.com", nickname="CSRF受害者")
    client = APIClient(enforce_csrf_checks=True)
    login, _ = _login_with_csrf(client, "csrf@example.com")
    assert login.status_code == 200

    response = getattr(client, method)(path, body, format="json")
    assert response.status_code == 403, f"{method} {path} 无 CSRF token 也通过了"


def test_write_succeeds_with_csrf_token(user_factory):
    """反证：带上正确的 token 同样的请求必须成功，否则上一条用例是假绿灯。"""
    user_factory(email="csrfok@example.com", nickname="CSRF正常")
    client = APIClient(enforce_csrf_checks=True)
    login, token = _login_with_csrf(client, "csrfok@example.com")
    assert login.status_code == 200

    response = client.post(
        "/api/v1/notifications/read/", {}, format="json", HTTP_X_CSRFTOKEN=token
    )
    assert response.status_code == 200


# ------------------------------------------------- 未鉴权访问整棵路由树


def _flatten(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _flatten(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            entry._full_prefix = prefix  # noqa: SLF001 - 仅测试内使用
            yield entry


# 明确公开的只读接口
PUBLIC_PREFIXES = (
    "/api/v1/health/",
    "/api/v1/siteconfig/",
    "/api/v1/content/",
    "/api/v1/profiles/users/",
    # 资源列表、招募列表、公开卡池对游客可见
    # （字段级隐私由各自的 app 负责；本文件只守「哪些路由能被游客读到」这条边界）
    "/api/v1/resources/",
    "/api/v1/charactercards/pool/",
    "/api/v1/games/",
    # —— 列表路由本身对游客开放，但只吐「精选 + 公开」的战报
    "/api/v1/reports/",

    # （精选照片那一格另有站级开关 + 可见范围把关，见 homecontent 的用例）
    "/api/v1/home/",
    "/api/v1/announcements/",
)


# 本轮对抗代理负责的骨架五 app + common（其他模块单独覆盖）
OWNED_PREFIXES = (
    "/api/v1/health/",
    "/api/v1/siteconfig/",
    "/api/v1/accounts/",
    "/api/v1/profiles/",
    "/api/v1/content/",
    "/api/v1/notifications/",
)


def test_no_api_route_is_readable_by_guests_unless_whitelisted(api_client, user_factory):
    """自动遍历路由树：/api/v1/ 下的接口除白名单外，游客一律不得拿到 200。"""
    user_factory(nickname="被围观的", email="watched@example.com")
    api_client.raise_request_exception = False  # 5xx 要当成响应收集，不能中断普查

    leaked, errored = [], []
    for pattern in _flatten(get_resolver().url_patterns):
        route = pattern._full_prefix + str(pattern.pattern)  # noqa: SLF001
        if not route.startswith("api/v1/"):
            continue
        url = "/" + route.replace("<int:user_id>", "1").replace("<slug:slug>", "x")
        if "<" in url:
            continue
        response = api_client.get(url)
        if response.status_code == 200 and not url.startswith(PUBLIC_PREFIXES):
            leaked.append(url)
        if response.status_code >= 500:
            errored.append((url, response.status_code))

    assert not leaked, f"以下接口对游客直接返回 200：{leaked}"
    mine = [item for item in errored if item[0].startswith(OWNED_PREFIXES)]
    assert not mine, f"本代理负责的接口对游客 5xx：{mine}（其余 5xx：{errored}）"


def test_no_guest_readable_route_leaks_any_email(api_client, user_factory):
    """把整棵路由树里游客能读到的接口全扫一遍，响应体里不许出现任何用户邮箱。"""
    secret = "leak-probe-unique@example.com"
    user = user_factory(nickname="邮箱探针", email=secret)
    user.is_gm = True
    user.save(update_fields=["is_gm"])

    api_client.raise_request_exception = False
    leaked = []
    for pattern in _flatten(get_resolver().url_patterns):
        route = pattern._full_prefix + str(pattern.pattern)  # noqa: SLF001
        if not route.startswith("api/v1/"):
            continue
        url = "/" + route.replace("<int:user_id>", str(user.pk)).replace("<slug:slug>", "x")
        if "<" in url:
            continue
        response = api_client.get(url)
        if response.status_code == 200 and secret in response.content.decode("utf-8", "ignore"):
            leaked.append(url)
    assert not leaked, f"以下游客可读接口泄露了邮箱：{leaked}"


def test_admin_is_not_at_default_path(client):
    assert client.get("/admin/").status_code == 404
    assert django_settings.ADMIN_URL != "admin/"


def test_default_permission_is_authenticated_and_active():
    """默认权限必须「要登录」**且**「账号状态正常」。

    2026-09-23 之前这里是 DRF 的 `IsAuthenticated`：忘写 `permission_classes`
    的新视图会落进一格只管登录、不管封禁/注销的兜底。现在兜底那一格也把关。
    """
    assert django_settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "common.permissions.IsAuthenticatedAndActive"
    ]


def test_only_session_authentication_is_enabled():
    """只有会话认证，不发 token。

    2026-09-23 起用的是 `SessionAuthentication` 的子类
    （`common.authentication.AccountStateSessionAuthentication`）——
    只去掉「`is_active=False` 就当没认出人」那半句，好让封禁/注销的真实会话
    落到权限层的 403 + code，而不是 401。
    这里同时钉住「它仍然是 SessionAuthentication 的子类」，防止哪天被换成别的认证方式。
    """
    from rest_framework.authentication import SessionAuthentication

    from common.authentication import AccountStateSessionAuthentication

    assert django_settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "common.authentication.AccountStateSessionAuthentication"
    ]
    assert issubclass(AccountStateSessionAuthentication, SessionAuthentication)


# ------------------------------------------------- 受保护媒体不得被直出


def test_debug_media_serving_does_not_expose_protected_dir(client, tmp_path):
    """开发期 Django 直出 MEDIA_ROOT 时，protected/ 子目录绝不能被直接下载。"""
    import config.urls

    media_root = tmp_path / "media"
    (media_root / "protected").mkdir(parents=True)
    (media_root / "protected" / "secret.txt").write_text("私密角色卡内容")
    (media_root / "avatars").mkdir()
    (media_root / "avatars" / "public.txt").write_text("公开头像")

    with override_settings(DEBUG=True, MEDIA_ROOT=media_root):
        importlib.reload(config.urls)
        clear_url_caches()
        try:
            protected = client.get("/media/protected/secret.txt")
            public = client.get("/media/avatars/public.txt")
            assert public.status_code == 200, "公开媒体在开发期应当可直出，否则用例失效"
            assert protected.status_code == 404, "受保护目录被 Django 直出了"
        finally:
            importlib.reload(config.urls)
            clear_url_caches()


# ------------------------------------------------- 生产配置


def _load_prod(monkeypatch=None, *, cache_url: str = "redis://redis-for-tests:6379/1"):
    """强制重新执行 config/settings/prod.py（它不是当前生效的 settings，重载安全）。

    `cache_url` 默认给一条合法的 Redis 串：缺陷 D1 之后 prod 会拒绝空缓存与进程内缓存，
    不补这一项的话所有 prod 用例都会卡在那道闸上，测不到自己要测的东西。
    """
    import sys

    if monkeypatch is not None:
        monkeypatch.setenv("CACHE_URL", cache_url)
    sys.modules.pop("config.settings.prod", None)
    return importlib.import_module("config.settings.prod")


def test_prod_settings_refuse_to_start_without_secret_key(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("DJANGO_SECRET_KEY", "")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    with pytest.raises(ImproperlyConfigured):
        _load_prod()


def test_prod_settings_refuse_to_start_without_allowed_hosts(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "")
    with pytest.raises(ImproperlyConfigured):
        _load_prod()


def test_prod_settings_are_hardened(monkeypatch):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    prod = _load_prod(monkeypatch)

    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_HTTPONLY is True
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS >= 60 * 60 * 24 * 365
    assert prod.X_FRAME_OPTIONS == "DENY"
    assert "BrowsableAPIRenderer" not in str(prod.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"])
    # 生产拓扑 Caddy → Nginx → gunicorn 两层可信代理：
    # 限速必须能看到真实客户端 IP，否则全站共用一个桶。
    assert prod.REST_FRAMEWORK.get("NUM_PROXIES") == 2
    assert prod.ALLAUTH_TRUSTED_PROXY_COUNT == 2


def test_prod_does_not_ship_dev_csrf_origins(monkeypatch):
    """dev 的 5173 来源绝不能被带进生产；生产只从环境变量读。"""
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    monkeypatch.delenv("DJANGO_CSRF_TRUSTED_ORIGINS", raising=False)
    prod = _load_prod(monkeypatch)
    assert prod.CSRF_TRUSTED_ORIGINS == []

    monkeypatch.setenv("DJANGO_CSRF_TRUSTED_ORIGINS", "https://example.com")
    prod = _load_prod(monkeypatch)
    assert prod.CSRF_TRUSTED_ORIGINS == ["https://example.com"]


# ------------------------------------------------- 生产缓存必须是共享的（缺陷 D1）
#
# compose 与 Dockerfile 都是 `gunicorn --workers 3`，而 allauth 的注册/登录限速计数
# 与 `siteconfig.services.get_config()` 的单例都存在 Django cache 里。缓存一旦落回
# 进程内 locmem：`5/h/ip` 实际变成 15/h/ip（每个 worker 各数各的），站主在后台改的
# 站级开关也只有处理那次请求的 worker 立刻生效。两条都是**静默**退化，跑起来一切正常，
# 只能靠启动时拒绝来挡。


def test_prod_refuses_to_start_without_cache_url(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    with pytest.raises(ImproperlyConfigured) as caught:
        _load_prod(monkeypatch, cache_url="")
    assert "CACHE_URL" in str(caught.value)


@pytest.mark.parametrize("cache_url", ["locmemcache://trpg-default", "dummycache://"])
def test_prod_refuses_per_process_cache(monkeypatch, cache_url):
    """光判空不够：显式填一个 locmem/dummy 的 URL 同样是多 worker 下的假共享。"""
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    with pytest.raises(ImproperlyConfigured) as caught:
        _load_prod(monkeypatch, cache_url=cache_url)
    assert "进程内缓存" in str(caught.value)


def test_prod_uses_shared_cache_backend_when_pointed_at_redis(monkeypatch):
    """反向保险：配置正确必须能加载，否则上面两条可能只是「prod 根本 import 不了」。"""
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    prod = _load_prod(monkeypatch, cache_url="redis://redis:6379/1")
    assert prod.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert prod.CACHES["default"]["LOCATION"] == "redis://redis:6379/1"


def test_dev_trusts_vite_dev_server_origins(monkeypatch):
    """本机经 Vite 代理（5173）发 POST 时，Origin 必须在受信来源里，否则一律 403。"""
    import sys

    monkeypatch.delenv("DJANGO_CSRF_TRUSTED_ORIGINS", raising=False)
    sys.modules.pop("config.settings.dev", None)
    dev = importlib.import_module("config.settings.dev")
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        assert origin in dev.CSRF_TRUSTED_ORIGINS, f"dev 缺少受信来源 {origin}"
    # 同站 Cookie 策略：Vite 代理下前后端同源，Lax 不会拦掉登录会话
    assert dev.SESSION_COOKIE_SAMESITE == "Lax"
    assert dev.CSRF_COOKIE_SAMESITE == "Lax"
    assert dev.CSRF_COOKIE_HTTPONLY is False  # 前端要读 csrftoken 写 X-CSRFToken


def test_csrf_origin_from_vite_proxy_is_accepted(user_factory, settings):
    """真打一发：带 Vite dev server 的 Origin 头做写操作，必须通过 CSRF 校验。"""
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
    user_factory(email="vite@example.com", nickname="Vite用户")

    client = APIClient(enforce_csrf_checks=True)
    client.get(f"{ALLAUTH}/auth/session", HTTP_ORIGIN="http://localhost:5173")
    token = client.cookies["csrftoken"].value
    login = client.post(
        f"{ALLAUTH}/auth/login",
        {"email": "vite@example.com", "password": "testpass1234"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://localhost:5173",
    )
    assert login.status_code == 200, login.content
    token = client.cookies["csrftoken"].value  # 登录会轮换 CSRF token

    response = client.post(
        "/api/v1/notifications/read/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://localhost:5173",
    )
    assert response.status_code == 200


def test_untrusted_origin_is_still_rejected(user_factory, settings):
    """反证：不在受信来源里的 Origin 即使带着正确 token 也必须被拒。"""
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:5173"]
    user_factory(email="evil-origin@example.com", nickname="外站用户")

    client = APIClient(enforce_csrf_checks=True)
    client.get(f"{ALLAUTH}/auth/session")
    token = client.cookies["csrftoken"].value
    client.post(
        f"{ALLAUTH}/auth/login",
        {"email": "evil-origin@example.com", "password": "testpass1234"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    token = client.cookies["csrftoken"].value  # 登录会轮换 CSRF token
    response = client.post(
        "/api/v1/notifications/read/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_ORIGIN="http://evil.example.com",
    )
    assert response.status_code == 403


def test_test_and_dev_settings_do_not_trust_forwarded_headers():
    """本机/测试没有反代，任何 XFF 都是伪造的，必须按 0 层可信代理处理。"""
    assert django_settings.REST_FRAMEWORK.get("NUM_PROXIES") == 0
    assert getattr(django_settings, "ALLAUTH_TRUSTED_PROXY_COUNT", 0) == 0
