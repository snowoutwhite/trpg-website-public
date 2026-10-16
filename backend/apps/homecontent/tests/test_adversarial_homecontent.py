"""业务规则与安全约束。"""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.homecontent.tests.conftest import image_upload, png_bytes

pytestmark = pytest.mark.django_db


def code_of(response) -> str:
    return response.json()["error"]["code"]


# --------------------------------------------------------------------------
# 1. 越权
# --------------------------------------------------------------------------

WRITE_ENDPOINTS = [
    ("patch", "/api/v1/home/admin/config/", {"site_name": "被改了"}),
    ("post", "/api/v1/home/admin/rule-presets/", {"name": "偷建的"}),
    ("post", "/api/v1/home/admin/quick-entries/", {"key": "x", "label": "偷建的", "route": "/"}),
    ("post", "/api/v1/home/admin/announcements/", {"title": "假公告", "body": "全站可见"}),
    ("post", "/api/v1/home/admin/featured-photos/", {"photo": 1, "is_featured": True}),
    ("get", "/api/v1/home/admin/", None),
]


@pytest.mark.parametrize(("method", "url", "payload"), WRITE_ENDPOINTS)
def test_游客写站长内容一律401(api_client, method, url, payload):
    call = getattr(api_client, method)
    response = call(url, payload, format="json") if payload else call(url)
    assert response.status_code == 401, url
    assert code_of(response) == "not_authenticated"


@pytest.mark.parametrize(("method", "url", "payload"), WRITE_ENDPOINTS)
def test_普通登录用户写站长内容一律403(api_client, user_factory, method, url, payload):
    api_client.force_authenticate(user_factory(nickname="路人"))
    call = getattr(api_client, method)
    response = call(url, payload, format="json") if payload else call(url)
    assert response.status_code == 403, url


def test_GM身份不等于站主(api_client, user_factory):
    gm = user_factory(nickname="想改首页的GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    api_client.force_authenticate(gm)
    assert api_client.patch("/api/v1/home/admin/config/", {"site_name": "GM的站"}, format="json").status_code == 403


def test_被封禁的站主也写不了(api_client, staff_user):
    from apps.accounts.services import ban_user

    ban_user(staff_user, reason="滥用")
    api_client.force_authenticate(staff_user)
    response = api_client.patch("/api/v1/home/admin/config/", {"site_name": "封了还改"}, format="json")
    assert response.status_code == 403
    assert code_of(response) == "account_banned"


def test_站主也改不了运维参数(api_client, staff_user, site_config):
    """`HomeConfigWriteSerializer` 只开首页那几格：自动结团天数、五档边界不在其中。"""
    api_client.force_authenticate(staff_user)
    before = site_config.auto_close_days
    response = api_client.patch(
        "/api/v1/home/admin/config/",
        {"auto_close_days": 999, "level_mostly_negative_dislike_min": "0.999", "home_section3_title": "正常字段"},
        format="json",
    )
    assert response.status_code == 200
    assert "auto_close_days" not in response.json()
    site_config.refresh_from_db()
    assert site_config.auto_close_days == before


def test_上传图片接口同样拦非站主(api_client, user_factory):
    from apps.homecontent.models import RuleSystemPreset

    preset = RuleSystemPreset.objects.first()
    api_client.force_authenticate(user_factory(nickname="想换图的"))
    response = api_client.post(
        f"/api/v1/home/admin/rule-presets/{preset.pk}/image/",
        {"file": image_upload()},
        format="multipart",
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# 2. 图片上传
# --------------------------------------------------------------------------


@pytest.fixture
def upload_url(db):
    from apps.homecontent.models import RuleSystemPreset

    return f"/api/v1/home/admin/rule-presets/{RuleSystemPreset.objects.first().pk}/image/"


def _post(api_client, url, uploaded):
    return api_client.post(url, {"file": uploaded}, format="multipart")


def test_扩展名对魔数不对一律拒(api_client, staff_user, upload_url):
    api_client.force_authenticate(staff_user)
    fake = SimpleUploadedFile("木马.jpg", b"MZ\x90\x00this is a PE binary", content_type="image/jpeg")
    response = _post(api_client, upload_url, fake)
    assert response.status_code == 400
    assert code_of(response) == "invalid_image"


def test_魔数对扩展名不对也拒(api_client, staff_user, upload_url):
    """一张货真价实的 GIF 改名成 .png 拦在扩展名闸；真 PNG 改名成 .txt 也拦。"""
    api_client.force_authenticate(staff_user)
    response = _post(api_client, upload_url, SimpleUploadedFile("图.txt", png_bytes(), "image/png"))
    assert response.status_code == 400
    assert code_of(response) == "invalid_image"


def test_gif不在白名单里(api_client, staff_user, upload_url):
    api_client.force_authenticate(staff_user)
    buffer = io.BytesIO()
    Image.new("P", (32, 32)).save(buffer, format="GIF")
    response = _post(api_client, upload_url, SimpleUploadedFile("动图.gif", buffer.getvalue(), "image/gif"))
    assert response.status_code == 400
    assert code_of(response) == "invalid_image"


def test_svg伪装成图片被拒(api_client, staff_user, upload_url):
    """SVG 里能塞 <script>，而且它连 Pillow 的魔数校验都过不了 —— 两道都要挡住。"""
    api_client.force_authenticate(staff_user)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    response = _post(api_client, upload_url, SimpleUploadedFile("图.svg", svg, "image/svg+xml"))
    assert response.status_code == 400


def test_超过体积上限被拒(api_client, staff_user, upload_url, settings):
    from apps.homecontent.models import SITE_IMAGE_MAX_BYTES

    api_client.force_authenticate(staff_user)
    oversize = SimpleUploadedFile(
        "巨图.png", b"\x89PNG\r\n\x1a\n" + b"0" * (SITE_IMAGE_MAX_BYTES + 1), "image/png"
    )
    response = _post(api_client, upload_url, oversize)
    assert response.status_code == 400
    assert code_of(response) == "image_too_large"


def test_解压炸弹被像素闸拦下(api_client, staff_user, upload_url):
    """一张几百字节的纯色 PNG 可以声称自己有上亿像素，体积闸拦不住它。"""
    api_client.force_authenticate(staff_user)
    buffer = io.BytesIO()
    Image.new("L", (9000, 9000), 0).save(buffer, format="PNG", compress_level=9)
    response = _post(api_client, upload_url, SimpleUploadedFile("炸弹.png", buffer.getvalue(), "image/png"))
    assert response.status_code == 400
    assert code_of(response) == "image_too_large"


def test_超宽全景图不会打成500(api_client, staff_user, upload_url):
    """libwebp 单边超 16383 直接拒编、抛 ValueError；`to_webp` 自己封顶，不能 500。"""
    api_client.force_authenticate(staff_user)
    buffer = io.BytesIO()
    Image.new("RGB", (17000, 200), (9, 9, 9)).save(buffer, format="PNG", compress_level=9)
    response = _post(api_client, upload_url, SimpleUploadedFile("长图.png", buffer.getvalue(), "image/png"))
    assert response.status_code < 500


def test_文件名不进存储路径(api_client, staff_user, upload_url):
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    evil = SimpleUploadedFile("../../../../etc/passwd.jpg", png_bytes(), "image/jpeg")
    # 扩展名是 .jpg、内容是真 PNG，魔数闸会放行（PNG 在白名单里），走到存名这一步
    response = _post(api_client, upload_url, evil)
    assert response.status_code == 200
    preset = RuleSystemPreset.objects.get(pk=upload_url.split("/")[-3])
    for field in (preset.image_full, preset.image_card, preset.image_thumb):
        assert field.name.startswith("homecontent/")
        assert ".." not in field.name and "passwd" not in field.name
        assert field.name.endswith(".webp")


# --------------------------------------------------------------------------
# 3. `__other__` 的花样
# --------------------------------------------------------------------------

OTHER_TRICKS = [
    "__OTHER__",
    "__Other__",
    "__other__ ",  # 两端空白会被 strip 成哨兵 —— 这条期望是「能匹配」，单独测
]


@pytest.mark.parametrize("value", ["__OTHER__", "__Other__", "_other_", "__other", "other"])
def test_哨兵大小写与变体不被当成其他(api_client, user_factory, value):
    """哨兵只认一模一样的 `__other__`。变体一律当普通规则名 → 匹配不到任何团。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.games import services

    gm = user_factory(nickname="花样GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    services.create_game(
        gm, title="自定义规则团", rule_system="PBTA",
        start_at=timezone.now() + timedelta(days=1), min_players=1, max_players=3,
    )
    response = api_client.get(f"/api/v1/games/?rule_system={value}")
    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        "' OR 1=1 --",
        "\" OR \"\"=\"",
        "__other__' OR '1'='1",
        "%",
        "_",
        "__other__;DROP TABLE games_game;--",
        "\\",
    ],
)
def test_规则筛选参数注入打不穿(api_client, payload):
    """ORM 全程参数化：注入串只会被当成一个普通的规则名，结果为空且不报错。"""
    response = api_client.get("/api/v1/games/", {"rule_system": payload})
    assert response.status_code == 200
    assert response.json()["count"] == 0

    pool = api_client.get("/api/v1/charactercards/pool/", {"rule_system": payload})
    assert pool.status_code == 200
    assert pool.json()["count"] == 0


def test_预设名里的通配符不会变成模糊匹配(api_client, user_factory):
    """预设名含 `%` 时，`__iexact` 必须按字面量比，不能退化成 LIKE 通配。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.games import services
    from apps.homecontent.models import RuleSystemPreset

    RuleSystemPreset.objects.create(name="100%规则", sort=80)
    gm = user_factory(nickname="通配GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    services.create_game(
        gm, title="别的团", rule_system="别的规则",
        start_at=timezone.now() + timedelta(days=1), min_players=1, max_players=3,
    )
    titles = {
        row["title"] for row in api_client.get("/api/v1/games/?rule_system=__other__").json()["results"]
    }
    assert titles == {"别的团"}


def test_标签其他不会被自建标签绕过(api_client, user_factory):
    """GM 自己建一个叫「战役」大小写变体的标签，也不能让带预设标签的团混进「其他」。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.games import services

    gm = user_factory(nickname="标签GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    services.create_game(
        gm, title="真战役团", rule_system="COC", tags=["战役"],
        start_at=timezone.now() + timedelta(days=1), min_players=1, max_players=3,
    )
    titles = {
        row["title"] for row in api_client.get("/api/v1/games/?tag=__other__").json()["results"]
    }
    assert "真战役团" not in titles


# --------------------------------------------------------------------------
# 4. 公告
# --------------------------------------------------------------------------


def test_公告重复发布不重复推通知(db, announcement_factory, user_factory):
    from apps.homecontent import services
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="只该收一次的")
    announcement = announcement_factory(title="只推一次")

    assert services.publish_announcement(announcement) > 0
    for _ in range(3):
        assert services.publish_announcement(announcement) == 0

    assert Notification.objects.filter(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).count() == 1


def test_反复切换生效状态也不重推(api_client, staff_user, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="被反复切的")
    api_client.force_authenticate(staff_user)
    pk = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "开关公告", "body": "正文"}, format="json"
    ).json()["id"]

    for is_active in (False, True, False, True):
        api_client.patch(
            f"/api/v1/home/admin/announcements/{pk}/", {"is_active": is_active}, format="json"
        )

    assert Notification.objects.filter(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).count() == 1


def test_改标题不会再推一轮(api_client, staff_user, user_factory):
    from apps.notifications import events
    from apps.notifications.models import Notification

    reader = user_factory(nickname="不该被轰炸的")
    api_client.force_authenticate(staff_user)
    pk = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "初版", "body": "正文"}, format="json"
    ).json()["id"]
    for i in range(5):
        api_client.patch(
            f"/api/v1/home/admin/announcements/{pk}/", {"title": f"第{i}版"}, format="json"
        )
    assert Notification.objects.filter(
        recipient=reader, event=events.SITE_ANNOUNCEMENT
    ).count() == 1


def test_公告与文案字段不收HTML(api_client, staff_user):
    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/announcements/",
        {"title": "正常", "body": "<img src=x onerror=alert(1)>"},
        format="json",
    )
    assert response.status_code == 400
    assert "body" in response.json()["error"]["detail"]

    copy = api_client.patch(
        "/api/v1/home/admin/config/",
        {"home_section3_lead": "<script>alert(1)</script>"},
        format="json",
    )
    assert copy.status_code == 400


def test_公告正文原样保存不被转义(api_client, staff_user):
    """拒 HTML 不等于乱改内容：普通文本里的 & < 之类字符要原样存原样回。"""
    api_client.force_authenticate(staff_user)
    body = "规则：A & B 的比较（3 < 5），详见群公告"
    created = api_client.post(
        "/api/v1/home/admin/announcements/", {"title": "口径", "body": body}, format="json"
    )
    assert created.status_code == 201
    assert created.json()["body"] == body


# --------------------------------------------------------------------------
# 5. 精选照片
# --------------------------------------------------------------------------


def _take_down(photo):
    from apps.gallery import services

    return services.take_down_photo(photo, reason="站主下架")


def test_非公开照片不能被勾成精选(api_client, staff_user, public_photo):
    from apps.gallery.models import PHOTO_PENDING_REVIEW

    photo = public_photo()
    photo.status = PHOTO_PENDING_REVIEW
    photo.save(update_fields=["status"])

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/", {"photo": photo.pk, "is_featured": True}, format="json"
    )
    assert response.status_code == 400
    assert code_of(response) == "photo_not_public"
    photo.refresh_from_db()
    assert photo.is_featured is False


def test_已下架的照片不能被勾成精选(api_client, staff_user, public_photo):
    photo = _take_down(public_photo())
    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/", {"photo": photo.pk, "is_featured": True}, format="json"
    )
    assert response.status_code == 400
    assert code_of(response) == "photo_not_public"


def test_数据库层也拦住精选非公开照片(db, public_photo):
    """绕过 service 直接写库同样写不进去 —— `featured_photo_must_be_public` 约束。"""
    from django.db import IntegrityError, transaction

    from apps.gallery.models import Photo

    photo = _take_down(public_photo())
    with pytest.raises(IntegrityError), transaction.atomic():
        Photo.objects.filter(pk=photo.pk).update(is_featured=True)


def test_举报后下架会把照片撤出首页(db, public_photo, user_factory, site_config):
    """业务规则与安全约束。"""
    from apps.gallery import services as gallery_services
    from apps.homecontent import services
    from apps.siteconfig.models import GALLERY_MODE_POST_REPORT

    site_config.gallery_moderation_mode = GALLERY_MODE_POST_REPORT
    site_config.featured_photos_enabled = True
    site_config.save()

    photo = public_photo()
    services.set_photo_featured(photo, True)
    assert services.featured_photos().count() == 1

    gallery_services.report_photo(
        user_factory(nickname="照片里的人"), photo, reason="in_photo", reason_text="我在照片里"
    )
    photo.refresh_from_db()
    assert photo.status == "taken_down"
    assert photo.is_featured is False
    assert services.featured_photos().count() == 0


def test_下架后字节出口立刻关门(api_client, public_photo, site_config):
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()
    url = f"/api/v1/home/featured-photos/{photo.pk}/file/"
    assert api_client.get(url).status_code == 200

    _take_down(photo)
    assert api_client.get(url).status_code == 404


def test_字节出口不给原图档(api_client, public_photo, site_config):
    """首页只需要 thumb/preview；原图仍只在需登录的相册里拿得到。"""
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    asked = api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/?size=original")
    fallback = api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/?size=thumb")
    assert asked.status_code == 200
    assert b"".join(asked.streaming_content) == b"".join(fallback.streaming_content)


def test_站级开关关着时字节出口也关着(api_client, public_photo, site_config):
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = False
    site_config.featured_photos_visibility = "public"
    site_config.save()
    assert api_client.get(f"/api/v1/home/featured-photos/{photo.pk}/file/").status_code == 404


def test_members范围下游客拿不到字节(api_client, public_photo, site_config, user_factory):
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True  # visibility 默认 members
    site_config.save()
    url = f"/api/v1/home/featured-photos/{photo.pk}/file/"

    assert api_client.get(url).status_code == 404
    api_client.force_authenticate(user_factory(nickname="登录成员"))
    assert api_client.get(url).status_code == 200


def test_封禁用户按游客处理(api_client, public_photo, site_config, user_factory):
    from apps.accounts.services import ban_user
    from apps.homecontent import services

    photo = public_photo()
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.save()

    banned = user_factory(nickname="被封的看客")
    ban_user(banned)
    api_client.force_authenticate(banned)
    assert api_client.get("/api/v1/home/").json()["featured_photos"]["visible"] is False


# --------------------------------------------------------------------------
# 6. `/home/` 的泄露面
# --------------------------------------------------------------------------


def test_首页对游客不泄露任何邮箱(api_client, user_factory, staff_user, public_photo, site_config, announcement_factory):
    """公告作者、照片上传者都可能是真人账号；响应体里一个邮箱都不许出现。"""
    from apps.homecontent import services

    secret = "home-leak-probe@example.com"
    author = user_factory(nickname="公告作者", email=secret)
    announcement_factory(title="有作者的公告", author=author)

    photo_gm = user_factory(nickname="传图的GM", email="photo-gm-probe@example.com")
    photo_gm.is_gm = True
    photo_gm.save(update_fields=["is_gm"])
    photo = public_photo(gm=photo_gm)
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.featured_photos_visibility = "public"
    site_config.save()

    raw = api_client.get("/api/v1/home/").content.decode()
    assert secret not in raw
    assert "photo-gm-probe@example.com" not in raw
    assert "@example.com" not in raw
    # 精选照片那一格连上传者身份都不给
    assert "uploader" not in raw


def test_首页对游客不泄露members限定的照片(api_client, public_photo, site_config):
    from apps.homecontent import services

    photo = public_photo(caption="只给成员看的合影")
    services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True  # visibility 默认 members
    site_config.save()

    raw = api_client.get("/api/v1/home/").content.decode()
    assert "只给成员看的合影" not in raw
    assert str(photo.pk) not in [
        str(row["id"]) for row in api_client.get("/api/v1/home/").json()["featured_photos"]["results"]
    ]


def test_公告历史页对游客不泄露邮箱(api_client, user_factory, announcement_factory):
    secret = "announce-leak@example.com"
    announcement_factory(author=user_factory(nickname="作者", email=secret))
    assert secret not in api_client.get("/api/v1/announcements/").content.decode()


def test_游客读不到未生效的公告(api_client, announcement_factory):
    announcement_factory(title="内部草稿", body="还没发", is_active=False)
    raw = api_client.get("/api/v1/announcements/").content.decode()
    assert "内部草稿" not in raw and "还没发" not in raw
    assert api_client.get("/api/v1/home/").json()["announcement"] is None


def test_别人的已读状态问不出来(api_client, user_factory, staff_user, announcement_factory):
    """`is_read` 永远只反映**当前请求者**的那条通知。"""
    from apps.homecontent import services

    a = user_factory(nickname="已读的")
    b = user_factory(nickname="没读的")
    announcement = announcement_factory(title="谁读了")
    services.publish_announcement(announcement)

    api_client.force_authenticate(a)
    api_client.post("/api/v1/notifications/read/", {}, format="json")
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is True

    api_client.force_authenticate(b)
    assert api_client.get("/api/v1/home/").json()["announcement"]["is_read"] is False


# --------------------------------------------------------------------------
# 7. 站内路由不得被改成站外跳转
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "https://evil.example.com/phish",
        "//evil.example.com",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "recruit",
        "",
        "/\\evil.example.com",
    ],
)
def test_快速选择的路由只收站内路径(api_client, staff_user, route):
    from apps.homecontent.models import QuickEntry

    entry = QuickEntry.objects.get(key="recruit")
    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        f"/api/v1/home/admin/quick-entries/{entry.pk}/", {"route": route}, format="json"
    )
    assert response.status_code == 400, route
    entry.refresh_from_db()
    assert entry.route == "/recruit"


def test_路由两端留白被trim掉而不是原样入库(api_client, staff_user):
    """`\n/recruit` 这类输入会被 trim 成合法的 `/recruit`，不会把换行符带进属性值。"""
    from apps.homecontent.models import QuickEntry

    entry = QuickEntry.objects.get(key="recruit")
    api_client.force_authenticate(staff_user)
    response = api_client.patch(
        f"/api/v1/home/admin/quick-entries/{entry.pk}/", {"route": "\n  /guide  "}, format="json"
    )
    assert response.status_code == 200
    entry.refresh_from_db()
    assert entry.route == "/guide"


def test_官方链接只收http与https(api_client, staff_user):
    from apps.homecontent.models import RuleSystemPreset

    preset = RuleSystemPreset.objects.get(name="FU")
    api_client.force_authenticate(staff_user)
    for bad in ("javascript:alert(1)", "ftp://example.com/x", "file:///etc/passwd"):
        response = api_client.patch(
            f"/api/v1/home/admin/rule-presets/{preset.pk}/", {"official_url": bad}, format="json"
        )
        assert response.status_code == 400, bad


def test_规则名不分大小写地唯一(api_client, staff_user):
    """允许两条 `COC` / `coc` 会让「其他」筛选出现两条等价筹码。"""
    api_client.force_authenticate(staff_user)
    response = api_client.post("/api/v1/home/admin/rule-presets/", {"name": "coc"}, format="json")
    assert response.status_code == 400
    assert "name" in response.json()["error"]["detail"]


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------

# 口径与昵称、标签一致（architecture 第 6 节第 6 条）：直接 400，不静默剥离。
BIDI_CONTROLS = [
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # 嵌入 / 覆盖 / PDF
    "\u2066", "\u2067", "\u2068", "\u2069",  # 隔离
]


@pytest.mark.parametrize("ch", BIDI_CONTROLS)
def test_规则预设名含双向控制字符一律400(api_client, staff_user, ch):
    """`name` 公开下发、还是全站分类轴：RTL override 能让它在列表里视觉倒序冒充别的规则。"""
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/rule-presets/", {"name": f"坏{ch}规则"}, format="json"
    )
    assert response.status_code == 400, repr(ch)
    assert "name" in response.json()["error"]["detail"]
    assert not RuleSystemPreset.objects.filter(name__contains=ch).exists()


@pytest.mark.parametrize(
    ("url_kind", "field"),
    [("rule-presets", "title"), ("quick-entries", "label"), ("config", "site_name")],
)
def test_站长短文本字段都不收RTL覆盖(api_client, staff_user, site_config, url_kind, field):
    """同一个入口（`PlainTextField`）管全部站长文案，不是只补 `name` 一格。"""
    from apps.homecontent.models import QuickEntry, RuleSystemPreset

    api_client.force_authenticate(staff_user)
    if url_kind == "config":
        url = "/api/v1/home/admin/config/"
    elif url_kind == "rule-presets":
        url = f"/api/v1/home/admin/rule-presets/{RuleSystemPreset.objects.get(name='FU').pk}/"
    else:
        url = f"/api/v1/home/admin/quick-entries/{QuickEntry.objects.get(key='recruit').pk}/"
    response = api_client.patch(url, {field: "正常\u202e文案"}, format="json")
    assert response.status_code == 400, (url, field)
    assert field in response.json()["error"]["detail"]


def test_站长文案里的普通换行与emoji不受影响(api_client, staff_user):
    """误伤检查：只拦双向控制字符，ZWJ 组合 emoji 与换行照常放行。"""
    from apps.homecontent.models import RuleSystemPreset

    preset = RuleSystemPreset.objects.get(name="FU")
    api_client.force_authenticate(staff_user)
    body = "第一行\n第二行 \U0001F468\u200d\U0001F469\u200d\U0001F467"
    response = api_client.patch(
        f"/api/v1/home/admin/rule-presets/{preset.pk}/", {"intro_body": body}, format="json"
    )
    assert response.status_code == 200, response.content


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------

INT32_OVERFLOW = 2**31  # 2147483648：SQLite 静默接受，PostgreSQL integer 存不下


@pytest.mark.parametrize("kind", ["rule-presets", "quick-entries"])
def test_sort超出32位上界回400(api_client, staff_user, kind):
    from apps.homecontent.models import QuickEntry, RuleSystemPreset

    api_client.force_authenticate(staff_user)
    if kind == "rule-presets":
        obj = RuleSystemPreset.objects.get(name="FU")
    else:
        obj = QuickEntry.objects.get(key="recruit")
    before = obj.sort
    url = f"/api/v1/home/admin/{kind}/{obj.pk}/"
    response = api_client.patch(url, {"sort": INT32_OVERFLOW}, format="json")
    assert response.status_code == 400, response.content
    assert "sort" in response.json()["error"]["detail"]
    obj.refresh_from_db()
    assert obj.sort == before

    # 上界本身合法
    assert api_client.patch(url, {"sort": INT32_OVERFLOW - 1}, format="json").status_code == 200


def test_新建规则预设sort越界同样400(api_client, staff_user):
    from apps.homecontent.models import RuleSystemPreset

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/rule-presets/", {"name": "越界", "sort": INT32_OVERFLOW}, format="json"
    )
    assert response.status_code == 400, response.content
    assert not RuleSystemPreset.objects.filter(name="越界").exists()
