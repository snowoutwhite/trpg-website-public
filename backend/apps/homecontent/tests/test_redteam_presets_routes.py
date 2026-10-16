"""业务规则与安全约束。"""

from __future__ import annotations

import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db

ADMIN = "/" + settings.ADMIN_URL.strip("/") + "/"


@pytest.fixture
def admin_client(user_factory):
    from rest_framework.test import APIClient

    superuser = user_factory(nickname="后台站主", email="redteam-admin@example.com")
    superuser.is_staff = True
    superuser.is_superuser = True
    superuser.save(update_fields=["is_staff", "is_superuser"])
    client = APIClient()
    client.force_login(superuser)
    return client


# --------------------------------------------------------------------------
# 6a. 规则名的大小写不敏感唯一性
# --------------------------------------------------------------------------


def test_大小写重名在数据库层就该写不进去(db):
    """API 承诺「不分大小写地唯一」，那这条约束的真源必须在 DB。

    只靠 `validate_name` 的 `__iexact` 查询是「先查再写」：
    - 绕过 serializer（后台、数据迁移、shell、将来某个新写入点）一路畅通；
    - 两个站主同时点保存也会各自查到「没有重名」然后双双写进去。
    模型上 `name = CharField(unique=True)` 是**大小写敏感**的（Postgres 与 SQLite
    默认排序规则都如此），挡不住 `DND` / `dnd`。
    """
    from django.db import IntegrityError, transaction

    from apps.homecontent.models import RuleSystemPreset

    assert RuleSystemPreset.objects.filter(name="DND").exists(), "迁移应已预置 DND"
    with pytest.raises(IntegrityError), transaction.atomic():
        RuleSystemPreset.objects.create(name="dnd")


def test_后台也不该建出大小写重名的预设(admin_client):
    """后台是与 API 同级的第二条写入路径（A 方案），同一条唯一性必须守得住。"""
    from apps.homecontent.models import RuleSystemPreset

    response = admin_client.post(
        f"{ADMIN}homecontent/rulesystempreset/add/",
        {"name": "dnd", "kicker": "", "title": "", "tagline": "", "intro_hero": "",
         "intro_body": "", "intro_fit": "", "official_url": "", "image_alt": "",
         "tone": "dark", "sort": "0"},
    )
    assert not RuleSystemPreset.objects.filter(name="dnd").exists(), (
        "后台建出了与 DND 只差大小写的第二条预设"
    )
    assert response.status_code == 200, "表单校验不过应当原页重渲染（200），不是 302 跳走"


def test_大小写重名会把镜像和筛选一起搞坏(db, api_client, user_factory):
    """原版让 `create(name="dnd")` 成功后检查镜像，与上一条「必须抛 IntegrityError」互斥
    。改为：写入被拒后，镜像仍无大小写重名，
    前端筛选条不会出现两个同名筹码。"""
    import pytest
    from django.db import IntegrityError, transaction

    from apps.homecontent.models import RuleSystemPreset
    from apps.siteconfig.services import get_config

    with pytest.raises(IntegrityError), transaction.atomic():
        RuleSystemPreset.objects.create(name="dnd", sort=99)
    names = list(get_config().rule_system_presets)
    lowered = [n.lower() for n in names]
    assert len(lowered) == len(set(lowered)), f"站级预设镜像里出现了大小写重名：{names}"


# --------------------------------------------------------------------------
# 6b. 删预设不该动到引用它的团与卡
# --------------------------------------------------------------------------


def test_删预设后引用该规则名的团与卡都还在(api_client, staff_user, user_factory):
    from datetime import timedelta

    from django.utils import timezone

    from apps.charactercards.models import CharacterCard
    from apps.games import services as game_services
    from apps.homecontent.models import RuleSystemPreset

    gm = user_factory(nickname="删预设测试GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    start = timezone.now() + timedelta(days=7)
    game = game_services.create_game(
        gm, title="被删预设的团", rule_system="DND", start_at=start,
        card_deadline=start - timedelta(days=1), min_players=1, max_players=4,
    )
    card = CharacterCard.objects.create(owner=gm, name="卡", rule_system="DND")

    preset = RuleSystemPreset.objects.get(name="DND")
    api_client.force_authenticate(staff_user)
    assert api_client.delete(f"/api/v1/home/admin/rule-presets/{preset.pk}/").status_code == 204

    game.refresh_from_db()
    card.refresh_from_db()
    assert game.rule_system == "DND" and card.rule_system == "DND"

    # 删完之后 DND 不再是预设 → 此团应当立刻落进「其他」
    titles = [g["title"] for g in api_client.get("/api/v1/games/?rule_system=__other__").json()["results"]]
    assert "被删预设的团" in titles, "删掉预设后，原本命中它的团没有立刻落进「其他」"


# --------------------------------------------------------------------------
# 6c. official_url
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
        "ftp://evil.example.com/x",
        "file:///etc/passwd",
        " javascript:alert(1)",
        "java\tscript:alert(1)",
    ],
)
def test_官方链接拒绝非http协议(api_client, staff_user, url):
    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/rule-presets/", {"name": f"协议测试{abs(hash(url)) % 9999}", "official_url": url},
        format="json",
    )
    assert response.status_code == 400, f"{url!r} 被接受了：{response.content[:200]}"


def test_后台也拒绝非http协议的官方链接(admin_client):
    from apps.homecontent.models import RuleSystemPreset

    admin_client.post(
        f"{ADMIN}homecontent/rulesystempreset/add/",
        {"name": "后台协议测试", "kicker": "", "title": "", "tagline": "", "intro_hero": "",
         "intro_body": "", "intro_fit": "", "official_url": "javascript:alert(1)",
         "image_alt": "", "tone": "dark", "sort": "0"},
    )
    assert not RuleSystemPreset.objects.filter(official_url__startswith="javascript").exists()


# --------------------------------------------------------------------------
# 6d. QuickEntry.route 只能是站内路由
# --------------------------------------------------------------------------

OFFSITE_ROUTES = [
    "https://evil.example.com",
    "http://evil.example.com",
    "//evil.example.com",
    "/\\evil.example.com",
    "\\\\evil.example.com",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "recruit",
    "",
]


@pytest.mark.parametrize("route", OFFSITE_ROUTES)
def test_API拒绝站外路由(api_client, staff_user, route):
    from apps.homecontent.models import QuickEntry

    api_client.force_authenticate(staff_user)
    entry = QuickEntry.objects.first()
    response = api_client.patch(
        f"/api/v1/home/admin/quick-entries/{entry.pk}/", {"route": route}, format="json"
    )
    assert response.status_code == 400, f"{route!r} 被接受了"
    entry.refresh_from_db()
    assert entry.route != route


@pytest.mark.parametrize("route", ["https://evil.example.com", "//evil.example.com", "javascript:alert(1)"])
def test_模型层也该拒绝站外路由(db, route):
    """`full_clean()` 是后台 ModelForm 的必经之路，也是所有非 API 写入点的最后一道。

    对照组：同一个 app 里的 `official_url` 就是把 validator 挂在**模型字段**上
    （`models.URLField(validators=[https_url_validator])`），所以后台与 API 两条路
    都守得住。`route` 只在 `QuickEntryWriteSerializer.validate_route` 里守。
    """
    from django.core.exceptions import ValidationError

    from apps.homecontent.models import QuickEntry

    entry = QuickEntry(key=f"rt{abs(hash(route)) % 9999}", label="红队", route=route)
    with pytest.raises(ValidationError):
        entry.full_clean()


@pytest.mark.parametrize("route", ["https://evil.example.com", "//evil.example.com"])
def test_后台改不出跳站外的快速选择按钮(admin_client, route):
    """站主在 Django 后台把按钮的 `route` 改成站外地址 —— 首页那个按钮就成了外链。"""
    from apps.homecontent.models import QuickEntry

    entry = QuickEntry.objects.get(key="recruit")
    admin_client.post(
        f"{ADMIN}homecontent/quickentry/{entry.pk}/change/",
        {
            "key": entry.key, "label": entry.label, "description": entry.description,
            "icon": entry.icon, "sort": str(entry.sort), "kicker": entry.kicker,
            "title": entry.title, "body": entry.body, "button_text": entry.button_text,
            "route": route, "image_alt": entry.image_alt,
        },
    )
    entry.refresh_from_db()
    assert entry.route != route, f"后台把站内按钮改成了外链：{entry.route!r}"


def test_公开接口吐出的路由全都是站内路径(api_client):
    """最终防线：无论是谁、从哪条路写进去的，`/home/` 吐给前端的必须都是站内路径。"""
    body = api_client.get("/api/v1/home/").json()
    bad = [e["route"] for e in body["quick_entries"] if not (e["route"].startswith("/") and not e["route"].startswith("//"))]
    assert not bad, f"首页返回了站外路由：{bad}"
