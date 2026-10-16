"""角色卡对抗性测试：越权、隐私、文件攻击、状态机、CSRF、路由矩阵。

纪律（安全测试规则）：每一条都先写成能复现问题的用例，
修复后才转绿；「跑了一下没报错」不算通过。
"""

from __future__ import annotations

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.charactercards.models import (
    STATUS_ALIVE,
    STATUS_TORN,
    CharacterCard,
    CharacterCardFile,
)
from apps.charactercards.services import add_file_version, record_play

from .conftest import PDF_BYTES, PNG_BYTES, upload

pytestmark = pytest.mark.django_db

POOL_URL = "/api/v1/charactercards/pool/"
MINE_URL = "/api/v1/charactercards/mine/"


def detail_url(card: CharacterCard) -> str:
    return f"/api/v1/charactercards/{card.pk}/"


def download_url(card: CharacterCard) -> str:
    return f"/api/v1/charactercards/{card.pk}/download/"


def mine_detail_url(card: CharacterCard) -> str:
    return f"/api/v1/charactercards/mine/{card.pk}/"


def mine_files_url(card: CharacterCard) -> str:
    return f"/api/v1/charactercards/mine/{card.pk}/files/"


def with_file(card: CharacterCard, name: str = "卡.pdf", data: bytes = PDF_BYTES):
    return add_file_version(card, upload(name, data), uploaded_by=card.owner)


# --------------------------------------------------------------------------
# 1. 路由矩阵：未登录访问每条路由
# --------------------------------------------------------------------------


def test_未登录时每条路由的状态码都在预期内(api_client, card_factory):
    """只有明确公开（卡池 / 公开卡详情）的路由允许 200。"""
    card = card_factory(is_public=True)
    with_file(card)

    expected = {
        ("get", POOL_URL): 200,  # 卡池：明确对游客公开
        ("get", detail_url(card)): 200,  # 公开卡元数据：明确对游客公开
        ("get", download_url(card)): 401,  # 源文件：游客一律不给
        # W5 状态码统一：未登录访问需登录接口一律 401
        ("get", MINE_URL): 401,
        ("post", MINE_URL): 401,
        ("get", mine_detail_url(card)): 401,
        ("patch", mine_detail_url(card)): 401,
        ("get", mine_files_url(card)): 401,
        ("post", mine_files_url(card)): 401,
    }
    actual = {
        (method, url): getattr(api_client, method)(url).status_code
        for method, url in expected
    }
    assert actual == expected


def test_游客看不到私密卡的任何一条路由(api_client, card_factory):
    private = card_factory(is_public=False)
    with_file(private)

    # W5 状态码统一：看不见的对象一律 404（401 会暴露「这张私密卡存在」）
    assert api_client.get(detail_url(private)).status_code == 404
    assert api_client.get(download_url(private)).status_code == 404
    # 卡池里不得出现
    assert api_client.get(POOL_URL).json()["count"] == 0


# --------------------------------------------------------------------------
# 2. 越权与隐私
# --------------------------------------------------------------------------


def test_他人私密卡的元数据版本列表下载全部拒绝(api_client, card_factory, user_factory):
    private = card_factory(is_public=False, name="别人的私密卡")
    with_file(private)
    api_client.force_authenticate(user=user_factory(nickname="入侵者"))

    # W5 状态码统一：他人私密卡一律 404，与 mine/<别人的 id>/ 同口径
    assert api_client.get(detail_url(private)).status_code == 404
    assert api_client.get(download_url(private)).status_code == 404
    # mine/<别人的 id>/ 一律 404（不能靠状态码区分「不存在」与「不是你的」）
    assert api_client.get(mine_detail_url(private)).status_code == 404
    assert api_client.patch(mine_detail_url(private), {"name": "改名"}).status_code == 404
    assert api_client.get(mine_files_url(private)).status_code == 404
    assert api_client.post(mine_files_url(private), {"file": upload("x.pdf", PDF_BYTES)}, format="multipart").status_code == 404

    private.refresh_from_db()
    assert private.name == "别人的私密卡"
    assert private.files.count() == 1


def test_不能撕别人的卡也不能把别人的卡改成公开(api_client, card_factory, user_factory):
    victim_card = card_factory(is_public=False)
    api_client.force_authenticate(user=user_factory(nickname="入侵者"))

    for payload in ({"status": STATUS_TORN}, {"is_public": True}):
        assert api_client.patch(mine_detail_url(victim_card), payload).status_code == 404

    victim_card.refresh_from_db()
    assert victim_card.status == STATUS_ALIVE
    assert victim_card.is_public is False


def test_版本参数只能取本卡的版本号不能横跨到别人的卡(api_client, card_factory, user_factory):
    """`?version=` 是「本卡第几版」，不是全局文件主键。"""
    mine = card_factory(is_public=True)
    with_file(mine, "我的v1.pdf")
    with_file(mine, "我的v2.pdf")

    others = card_factory(is_public=False)
    secret = with_file(others, "别人的机密.pdf")

    api_client.force_authenticate(user=mine.owner)
    # 用别人文件版本的主键当 version 传进来
    response = api_client.get(f"{download_url(mine)}?version={secret.pk}")
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "机密" not in response["Content-Disposition"]
    # 只有 1 版的卡请求第 2 版：404，不得回落到「最新版」
    assert api_client.get(f"{download_url(others)}?version=2").status_code in (403, 404)


def test_已被prune掉的旧版本不能再下载(api_client, card_factory):
    card = card_factory(is_public=True)
    for index in range(1, 5):  # 保留最近 3 版，v1 会被 prune
        with_file(card, f"v{index}.pdf")
    api_client.force_authenticate(user=card.owner)

    response = api_client.get(f"{download_url(card)}?version=1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_file_missing"


@pytest.mark.parametrize("bad_version", ["²", "１２３", "9" * 25, "-1", " 1 ", "1;DROP", "0"])
def test_异常版本号不得把接口打成500(api_client, card_factory, bad_version):
    """`str.isdigit()` 对上标/全角数字为真，但 `int()` 会炸 —— 不能变成 500。"""
    card = card_factory(is_public=True)
    with_file(card)
    api_client.force_authenticate(user=card.owner)

    response = api_client.get(f"{download_url(card)}?version={bad_version}")
    assert response.status_code < 500, f"version={bad_version!r} 把接口打成了 {response.status_code}"


def test_卡池与详情不泄露邮箱与存储路径(api_client, card_factory, user_factory):
    owner = user_factory(nickname="持卡人", email="leak-me@example.com")
    card = card_factory(owner=owner, is_public=True)
    stored = with_file(card)
    api_client.force_authenticate(user=owner)

    for url in (POOL_URL, detail_url(card), MINE_URL, mine_detail_url(card), mine_files_url(card)):
        raw = api_client.get(url).content.decode()
        assert "leak-me@example.com" not in raw, url
        assert "protected/" not in raw, url
        assert "/media/" not in raw, url
        assert stored.file.name not in raw, url


def test_公开卡改回私密后立刻从卡池和他人视角消失(api_client, card_factory, user_factory):
    card = card_factory(is_public=True)
    api_client.force_authenticate(user=card.owner)
    assert api_client.patch(mine_detail_url(card), {"is_public": False}).status_code == 200

    stranger = user_factory(nickname="路人")
    api_client.force_authenticate(user=stranger)
    assert api_client.get(POOL_URL).json()["count"] == 0
    # W5 状态码统一：改回私密后对他人就是「不存在」
    assert api_client.get(detail_url(card)).status_code == 404
    assert api_client.get(download_url(card)).status_code == 404


def test_他人视角看不到备注字段(api_client, card_factory, user_factory):
    card = card_factory(is_public=True, note="这里写了团内黑话")
    api_client.force_authenticate(user=user_factory(nickname="路人"))
    body = api_client.get(detail_url(card)).json()
    assert "note" not in body
    assert "团内黑话" not in api_client.get(POOL_URL).content.decode()


# --------------------------------------------------------------------------
# 3. CSRF
# --------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "patch"])
def test_写接口缺少csrf_token时被拒(db, card_factory, method):
    from rest_framework.test import APIClient

    card = card_factory()
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=card.owner.email, password="testpass1234")

    url = MINE_URL if method == "post" else mine_detail_url(card)
    response = getattr(client, method)(url, {"name": "无 token"}, format="json")
    assert response.status_code == 403
    assert CharacterCard.objects.filter(name="无 token").count() == 0


def test_上传文件接口缺少csrf_token时被拒(db, card_factory):
    from rest_framework.test import APIClient

    card = card_factory()
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=card.owner.email, password="testpass1234")

    response = client.post(
        mine_files_url(card), {"file": upload("卡.pdf", PDF_BYTES)}, format="multipart"
    )
    assert response.status_code == 403
    assert card.files.count() == 0


# --------------------------------------------------------------------------
# 4. 文件攻击
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,data",
    [
        ("伪装.pdf", b"<html><script>alert(1)</script></html>"),
        ("伪装.png", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"),
        ("伪装.png", b"<?php system($_GET[0]); ?>"),
        ("伪装.jpg", b"GIF89a" + b"\x00" * 32),
        ("伪装.xls", b"PK\x03\x04" + b"\x00" * 32),
        ("空.pdf", b""),
        ("零字节.txt", b""),
        ("非utf8.txt", b"\xff\xfe\x00\x01\x80\x81"),
    ],
)
def test_伪造魔数与空文件一律被拒(api_client, card_factory, name, data):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(mine_files_url(card), {"file": upload(name, data)}, format="multipart")
    assert response.status_code == 400, response.content
    # 空文件被 DRF 的 FileField 先挡（validation_error），其余走白名单/魔数校验。
    assert response.json()["error"]["code"] in {
        "invalid_card_file",
        "card_file_too_large",
        "validation_error",
    }
    assert card.files.count() == 0


@pytest.mark.parametrize(
    "name",
    [
        "木马.exe",
        "木马.EXE",
        "卡.pdf.exe",
        "卡.pdf%00.exe",
        "卡.pdf\x00.exe",
        "脚本.js.txt.js",
        "页面.htm",
        "页面.html",
        "矢量.svg",
        "包.jar",
        "脚本.py",
        "脚本.ps1",
        "库.dll",
        "屏保.scr",
        "脚本.vbs",
        "卡.pdf.",
        "卡",
        ".pdf",
    ],
)
def test_白名单外的扩展名一律被拒(api_client, card_factory, name):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(
        mine_files_url(card), {"file": upload(name, PDF_BYTES)}, format="multipart"
    )
    assert response.status_code == 400, f"{name!r} 被放行了：{response.content}"
    assert card.files.count() == 0


@pytest.mark.parametrize("name", ["卡.pdf ", "卡.pdf\t", "卡.pdf\xa0"])
def test_扩展名后缀带空白时被归一化后按白名单判定(api_client, card_factory, name):
    """白名单是「先 strip 再比对」，尾随空白不会变成绕过通道（对照 resources 的黑名单）。"""
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(
        mine_files_url(card), {"file": upload(name, PDF_BYTES)}, format="multipart"
    )
    assert response.status_code == 201, response.content
    assert card.files.get().original_name.endswith(".pdf")


@pytest.mark.parametrize("name", ["卡.PDF", "卡.Pdf", "头像.PNG"])
def test_白名单扩展名大小写不影响放行(api_client, card_factory, name):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    data = PNG_BYTES if name.lower().endswith(".png") else PDF_BYTES
    response = api_client.post(
        mine_files_url(card), {"file": upload(name, data)}, format="multipart"
    )
    assert response.status_code == 201, response.content


def test_路径穿越与超长文件名不会逃出受保护目录(api_client, card_factory, settings):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    evil_names = ["../../../../etc/passwd.pdf", "..\\..\\windows\\system32\\x.pdf", "卡" * 400 + ".pdf"]
    for name in evil_names:
        response = api_client.post(
            mine_files_url(card), {"file": upload(name, PDF_BYTES)}, format="multipart"
        )
        assert response.status_code == 201, response.content
        version = CharacterCardFile.objects.filter(card=card).order_by("-version").first()
        assert version.file.name.startswith(f"{settings.PROTECTED_MEDIA_DIRNAME}/charactercards/")
        assert ".." not in version.file.name
        assert len(version.original_name) <= 255
        # 原名不得进入存储路径
        assert "passwd" not in version.file.name and "system32" not in version.file.name


@pytest.mark.parametrize(
    "original",
    [
        '恶意"; X-Injected: 1; filename="x.pdf',
        "换行\r\nX-Injected: 1.pdf",
        "中文名字.pdf",
        "a" * 200 + ".pdf",
    ],
)
def test_原始文件名不会造成响应头注入(api_client, card_factory, original):
    card = card_factory(is_public=True)
    api_client.force_authenticate(user=card.owner)
    version = CharacterCardFile(
        card=card, original_name=original, size=len(PDF_BYTES), mime="application/pdf", version=1
    )
    version.file.save("upload.pdf", SimpleUploadedFile("upload.pdf", PDF_BYTES), save=False)
    version.save()

    response = api_client.get(download_url(card))
    assert response.status_code == 200
    assert "X-Injected" not in response
    disposition = response["Content-Disposition"]
    assert "\n" not in disposition and "\r" not in disposition
    assert disposition.startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"


def test_pdf里夹带html仍按附件下发且不嗅探(api_client, card_factory):
    card = card_factory(is_public=True)
    payload = b"%PDF-1.7\n<html><script>alert(1)</script></html>\n%%EOF"
    add_file_version(card, upload("夹带.pdf", payload), uploaded_by=card.owner)
    api_client.force_authenticate(user=card.owner)

    response = api_client.get(download_url(card))
    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("attachment;")
    assert "text/html" not in response["Content-Type"]


def test_超过20MB边界被拒而恰好20MB放行(api_client, card_factory):
    from apps.charactercards.validators import CARD_FILE_MAX_BYTES

    card = card_factory()
    api_client.force_authenticate(user=card.owner)

    over = b"%PDF-" + b"\x00" * (CARD_FILE_MAX_BYTES - 4)
    assert len(over) == CARD_FILE_MAX_BYTES + 1
    response = api_client.post(mine_files_url(card), {"file": upload("大.pdf", over)}, format="multipart")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_file_too_large"

    exact = b"%PDF-" + b"\x00" * (CARD_FILE_MAX_BYTES - 5)
    assert len(exact) == CARD_FILE_MAX_BYTES
    assert api_client.post(
        mine_files_url(card), {"file": upload("刚好.pdf", exact)}, format="multipart"
    ).status_code == 201


def test_zip炸弹不会在服务端解压(api_client, card_factory):
    """OOXML 校验只读目录不解压：压缩比 1000 倍的包上传不应把服务端撑爆。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/bomb.bin", b"\x00" * (50 * 1024 * 1024))
    bomb = buffer.getvalue()
    assert len(bomb) < 1024 * 1024  # 压缩后很小

    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(
        mine_files_url(card), {"file": upload("炸弹.xlsx", bomb)}, format="multipart"
    )
    # 入库可以（内容确实是合法 OOXML 结构），但绝不能因为解压而 500/超时
    assert response.status_code in (201, 400)


# --------------------------------------------------------------------------
# 5. 状态机与计数
# --------------------------------------------------------------------------


def test_撕卡后不能用于报名但公开卡仍可下载(api_client, card_factory):
    from apps.charactercards.services import usable_cards_for_signup

    card = card_factory(is_public=True)
    with_file(card)
    api_client.force_authenticate(user=card.owner)
    assert api_client.patch(mine_detail_url(card), {"status": STATUS_TORN}).status_code == 200

    card.refresh_from_db()
    assert card.is_usable_for_signup is False
    assert card.pk not in [c.pk for c in usable_cards_for_signup(card.owner)]
    # 口径：撕卡后仍可公开下载
    assert api_client.get(download_url(card)).status_code == 200


def test_record_play幂等且play_count不漂移(card_factory):
    card = card_factory()
    for _ in range(5):
        record_play(card, 42)
    record_play(card, 43)
    card.refresh_from_db()
    assert card.play_records.count() == 2
    assert card.play_count == 2


def test_play_count不接受前端直接写入(api_client, card_factory):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.patch(mine_detail_url(card), {"play_count": 999, "owner": 1})
    assert response.status_code == 200
    card.refresh_from_db()
    assert card.play_count == 0


def test_并发上传版本时版本号不得撞车(card_factory, monkeypatch):
    """模拟 TOCTOU：算出 next_version 之后、落库之前，另一个请求先占了同号版本。

    插队动作挂在「文件落盘」这一步上，位于版本号读取之后、INSERT 之前，
    且不在 INSERT 的 savepoint 内 —— 回滚 savepoint 不会把它一起抹掉，才是真并发的样子。
    """
    card = card_factory()
    with_file(card, "v1.pdf")

    storage = CharacterCardFile._meta.get_field("file").storage
    original_save = storage.save
    state = {"fired": False}

    def racing_save(name, content, max_length=None):
        if not state["fired"]:
            state["fired"] = True
            CharacterCardFile.objects.create(
                card=card,
                original_name="并发.pdf",
                size=1,
                mime="application/pdf",
                version=2,  # 抢走我们正要用的下一个版本号
                uploaded_by=card.owner,
            )
        return original_save(name, content, max_length=max_length)

    monkeypatch.setattr(storage, "save", racing_save)
    add_file_version(card, upload("v2.pdf", PDF_BYTES), uploaded_by=card.owner)
    monkeypatch.undo()

    versions = list(
        CharacterCardFile.objects.filter(card=card).values_list("version", flat=True)
    )
    assert len(versions) == len(set(versions)), "同一张卡出现了重复版本号"
    assert sorted(versions) == [1, 2, 3]


def test_prune只删本卡的文件不碰别人的(card_factory):
    from apps.charactercards.services import prune_old_versions

    mine = card_factory()
    others = card_factory()
    kept = with_file(others, "别人的卡.pdf")
    for index in range(1, 5):
        with_file(mine, f"v{index}.pdf")

    prune_old_versions(mine)

    kept.refresh_from_db()
    assert CharacterCardFile.objects.filter(pk=kept.pk).exists()
    assert kept.file.storage.exists(kept.file.name), "prune 把别人的卡文件删了"
    assert CharacterCardFile.objects.filter(card=mine).count() == 3


# --------------------------------------------------------------------------
# 6. 存储与下发通道
# --------------------------------------------------------------------------


def test_生产模式下走X_Accel且不把字节交给Django(api_client, card_factory, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    card = card_factory(is_public=True)
    version = with_file(card)
    api_client.force_authenticate(user=card.owner)

    response = api_client.get(download_url(card))
    assert response.status_code == 200
    redirect = response["X-Accel-Redirect"]
    assert redirect.startswith(settings.X_ACCEL_REDIRECT_PREFIX)
    assert ".." not in redirect and "//" not in redirect.removeprefix("/")
    # 字节由 Nginx 发，Django 不读盘
    assert response.content == b""
    assert PDF_BYTES not in response.content
    assert version.file.name.split("/")[-1] in redirect


def test_落盘路径始终在受保护目录下且是uuid名(card_factory, settings):
    import re

    card = card_factory()
    version = with_file(card, "原始名字.pdf")
    prefix = f"{settings.PROTECTED_MEDIA_DIRNAME}/charactercards/"
    assert version.file.name.startswith(prefix)
    stem = version.file.name[len(prefix):]
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", stem), stem
    assert "原始名字" not in version.file.name


def test_被封禁或注销的用户不能下载源文件(api_client, card_factory, user_factory):
    """`mine/*` 用 IsAuthenticatedAndActive 挡住了封禁号，下载口不能是例外。

    对照组：资源区的下载接口用的就是 IsAuthenticatedAndActive。
    """
    card = card_factory(is_public=True)
    with_file(card)

    banned = user_factory(nickname="封禁号", is_banned=True)
    api_client.force_authenticate(user=banned)
    assert api_client.get(download_url(card)).status_code in (401, 403)

    deactivated = user_factory(nickname="注销号", is_active=False, is_deactivated=True)
    api_client.force_authenticate(user=deactivated)
    assert api_client.get(download_url(card)).status_code in (401, 403)


def test_不存在的超大主键不会把接口打成500(api_client):
    huge = "9" * 25
    for path in (f"/api/v1/charactercards/{huge}/", f"/api/v1/charactercards/{huge}/download/"):
        assert api_client.get(path).status_code < 500, path


def test_角色卡名含RTL覆盖字符一律400(api_client, card_factory):
    """业务规则与安全约束。"""
    card = card_factory(is_public=True, name="正常卡")
    api_client.force_authenticate(user=card.owner)
    response = api_client.patch(mine_detail_url(card), {"name": "坏\u202e卡"}, format="json")
    assert response.status_code == 400, response.content
    card.refresh_from_db()
    assert card.name == "正常卡"
