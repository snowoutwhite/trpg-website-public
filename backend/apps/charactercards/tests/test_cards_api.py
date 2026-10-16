"""角色卡接口：卡池可见性、隐私字段、下载鉴权、撕卡、我的卡 CRUD。"""

from __future__ import annotations

import pytest

from apps.charactercards.models import STATUS_TORN, CharacterCard, CharacterCardFile
from apps.charactercards.services import add_file_version

from .conftest import PDF_BYTES, upload

pytestmark = pytest.mark.django_db

POOL_URL = "/api/v1/charactercards/pool/"
MINE_URL = "/api/v1/charactercards/mine/"


def download_url(card: CharacterCard) -> str:
    return f"/api/v1/charactercards/{card.pk}/download/"


def with_file(card: CharacterCard) -> CharacterCardFile:
    return add_file_version(card, upload("卡.pdf", PDF_BYTES), uploaded_by=card.owner)


# --------------------------------------------------------------------------
# 卡池
# --------------------------------------------------------------------------


def test_游客可以浏览卡池(api_client, card_factory):
    card = card_factory(is_public=True, name="公开的调查员")
    card_factory(is_public=False, name="私密的调查员")

    response = api_client.get(POOL_URL)
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["results"]]
    assert names == ["公开的调查员"]
    assert card.name in names


def test_卡池不泄露持卡人邮箱(api_client, user_factory, card_factory):
    owner = user_factory(nickname="持卡人", email="secret@example.com")
    card_factory(owner=owner, is_public=True)

    response = api_client.get(POOL_URL)
    body = response.json()
    owner_payload = body["results"][0]["owner"]
    assert owner_payload["nickname"] == "持卡人"
    assert set(owner_payload) == {"id", "nickname", "avatar", "is_gm"}
    assert "secret@example.com" not in response.content.decode()


def test_卡池不回传文件存储路径(api_client, card_factory):
    card = card_factory(is_public=True)
    with_file(card)
    raw = api_client.get(POOL_URL).content.decode()
    assert "protected/" not in raw, "存储路径绝不能出现在任何列表里"
    assert "/media/" not in raw
    assert "file" not in api_client.get(POOL_URL).json()["results"][0]


def test_卡池只露约定字段(api_client, card_factory):
    card = card_factory(is_public=True, note="这里写了私人备注")
    with_file(card)
    item = api_client.get(POOL_URL).json()["results"][0]
    assert "note" not in item, "备注是自己看的，不进卡池"
    assert item["play_count"] == 0
    assert item["games_played"] == []
    assert item["rule_system"] == "COC"


def test_卡池可按规则筛选(api_client, card_factory):
    card_factory(is_public=True, rule_system="COC", name="甲")
    card_factory(is_public=True, rule_system="DND", name="乙")
    body = api_client.get(f"{POOL_URL}?rule_system=dnd").json()
    assert [item["name"] for item in body["results"]] == ["乙"]


# --------------------------------------------------------------------------
# 下载鉴权
# --------------------------------------------------------------------------


def test_游客对公开卡也不能下载(api_client, card_factory):
    """需求写「任何用户可查看下载」，本实现理解为登录用户；游客只能浏览卡池。"""
    card = card_factory(is_public=True)
    with_file(card)
    response = api_client.get(download_url(card))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_登录用户可以下载公开卡(api_client, card_factory, user_factory):
    card = card_factory(is_public=True)
    with_file(card)
    api_client.force_authenticate(user=user_factory(nickname="路人"))

    response = api_client.get(download_url(card))
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"%PDF-" in b"".join(response.streaming_content)


def test_私密卡他人404本人200(api_client, card_factory, user_factory):
    # W5 状态码统一：看不见的对象一律 404，不用 401/403 暴露「这张私密卡存在」。
    card = card_factory(is_public=False)
    with_file(card)

    api_client.force_authenticate(user=user_factory(nickname="外人"))
    denied = api_client.get(download_url(card))
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "not_found"

    api_client.force_authenticate(user=card.owner)
    assert api_client.get(download_url(card)).status_code == 200


def test_私密卡游客404(api_client, card_factory):
    # W5 状态码统一：看不见的对象一律 404，不用 401/403 暴露「这张私密卡存在」。
    card = card_factory(is_public=False)
    with_file(card)
    assert api_client.get(download_url(card)).status_code == 404


def test_没有文件的卡下载返回404(api_client, card_factory):
    card = card_factory(is_public=True)
    api_client.force_authenticate(user=card.owner)
    response = api_client.get(download_url(card))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "card_file_missing"


def test_下载走X_Accel下发不直出字节(api_client, card_factory, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    card = card_factory(is_public=True)
    version = with_file(card)
    api_client.force_authenticate(user=card.owner)

    response = api_client.get(download_url(card))
    assert response.status_code == 200
    assert response["X-Accel-Redirect"].startswith("/media/protected/charactercards/")
    assert response.content == b"", "生产模式下字节由 Nginx internal location 发出"
    # internal 路径就是存储相对路径，外部 URL 打不进这个 location（deploy/nginx.conf）
    assert response["X-Accel-Redirect"].endswith(version.file.name.rsplit("/", 1)[-1])


def test_可以下载指定版本(api_client, card_factory):
    card = card_factory()
    first = with_file(card)
    add_file_version(card, upload("新版.pdf", PDF_BYTES + b"NEW"), uploaded_by=card.owner)
    api_client.force_authenticate(user=card.owner)

    latest = api_client.get(download_url(card))
    assert b"NEW" in b"".join(latest.streaming_content)

    old = api_client.get(f"{download_url(card)}?version={first.version}")
    assert b"NEW" not in b"".join(old.streaming_content)


# --------------------------------------------------------------------------
# 我的卡 CRUD
# --------------------------------------------------------------------------


def test_建卡改元数据与切换公开(api_client, user_factory):
    user = user_factory(nickname="卡主")
    api_client.force_authenticate(user=user)

    created = api_client.post(
        MINE_URL, {"name": "  新调查员  ", "rule_system": "COC", "note": "备注"}, format="json"
    )
    assert created.status_code == 201
    card_id = created.json()["id"]
    assert created.json()["name"] == "新调查员"
    assert created.json()["is_public"] is False

    patched = api_client.patch(
        f"{MINE_URL}{card_id}/", {"is_public": True, "name": "改名后"}, format="json"
    )
    assert patched.status_code == 200
    card = CharacterCard.objects.get(pk=card_id)
    assert card.is_public is True
    assert card.name == "改名后"
    assert card.owner == user


def test_我的卡列表只有自己的(api_client, card_factory, user_factory):
    mine = card_factory(name="我的")
    card_factory(name="别人的", is_public=True)
    api_client.force_authenticate(user=mine.owner)
    body = api_client.get(MINE_URL).json()
    assert [item["name"] for item in body["results"]] == ["我的"]


def test_不能改别人的卡(api_client, card_factory, user_factory):
    card = card_factory(is_public=True)
    api_client.force_authenticate(user=user_factory(nickname="入侵者"))
    response = api_client.patch(f"{MINE_URL}{card.pk}/", {"name": "被改了"}, format="json")
    assert response.status_code == 404
    card.refresh_from_db()
    assert card.name != "被改了"


def test_缓存字段不可通过接口刷(api_client, card_factory):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    api_client.patch(f"{MINE_URL}{card.pk}/", {"play_count": 999}, format="json")
    card.refresh_from_db()
    assert card.play_count == 0


def test_游客与未登录者进不了我的卡(api_client, card_factory):
    assert api_client.get(MINE_URL).status_code in (401, 403)


def test_上传新版本与版本列表(api_client, card_factory):
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    url = f"{MINE_URL}{card.pk}/files/"

    response = api_client.post(url, {"file": upload("我的卡.pdf", PDF_BYTES)}, format="multipart")
    assert response.status_code == 201
    assert response.json()["version"] == 1
    assert response.json()["original_name"] == "我的卡.pdf"
    assert response.json()["uploaded_by_gm"] is False

    listed = api_client.get(url).json()["results"]
    assert [item["version"] for item in listed] == [1]
    assert "file" not in listed[0], "版本列表不得回传文件字段"


def test_上传接口拒绝非白名单格式(api_client, card_factory):
    from .conftest import EXE_BYTES

    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(
        f"{MINE_URL}{card.pk}/files/",
        {"file": upload("木马.exe", EXE_BYTES)},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_card_file"
    assert not CharacterCardFile.objects.filter(card=card).exists()


def test_上传接口拒绝超大文件(api_client, card_factory, monkeypatch):
    from apps.charactercards import validators

    monkeypatch.setattr(validators, "CARD_FILE_MAX_BYTES", 128)
    card = card_factory()
    api_client.force_authenticate(user=card.owner)
    response = api_client.post(
        f"{MINE_URL}{card.pk}/files/",
        {"file": upload("大卡.pdf", PDF_BYTES + b"0" * 512)},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_file_too_large"
    assert not CharacterCardFile.objects.filter(card=card).exists()


def test_不能往别人的卡上传文件(api_client, card_factory, user_factory):
    card = card_factory(is_public=True)
    api_client.force_authenticate(user=user_factory(nickname="入侵者"))
    response = api_client.post(
        f"{MINE_URL}{card.pk}/files/", {"file": upload("卡.pdf", PDF_BYTES)}, format="multipart"
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 撕卡
# --------------------------------------------------------------------------


def test_撕卡后不能用于报名但仍可公开下载(api_client, card_factory, user_factory):
    from apps.charactercards.services import usable_cards_for_signup

    card = card_factory(is_public=True)
    with_file(card)
    api_client.force_authenticate(user=card.owner)

    response = api_client.patch(f"{MINE_URL}{card.pk}/", {"status": STATUS_TORN}, format="json")
    assert response.status_code == 200
    assert response.json()["status_display"] == "撕卡"
    assert response.json()["is_usable_for_signup"] is False

    card.refresh_from_db()
    assert card.is_usable_for_signup is False
    assert list(usable_cards_for_signup(card.owner)) == []

    api_client.force_authenticate(user=user_factory(nickname="路人"))
    assert api_client.get(download_url(card)).status_code == 200


def test_单卡详情私密对非卡主一律404(api_client, card_factory, user_factory):
    # W5 状态码统一：看不见的对象一律 404，不用 401/403 暴露「这张私密卡存在」。
    card = card_factory(is_public=False)
    detail = f"/api/v1/charactercards/{card.pk}/"

    assert api_client.get(detail).status_code == 404
    api_client.force_authenticate(user=user_factory(nickname="外人"))
    assert api_client.get(detail).status_code == 404
    api_client.force_authenticate(user=card.owner)
    body = api_client.get(detail).json()
    assert body["note"] == ""


# --------------------------------------------------------------------------
# games 接线点
# --------------------------------------------------------------------------


def test_record_play幂等且递增参团次数(card_factory):
    from apps.charactercards.services import games_played_for, record_play

    card = card_factory()
    assert games_played_for(card) == []

    record_play(card, 7)
    record_play(card, 7)
    record_play(card, 8)

    card.refresh_from_db()
    assert card.play_count == 2
    assert {item["game_id"] for item in games_played_for(card)} == {7, 8}


def test_可注册额外的文件可见性判断(card_factory, user_factory):
    """games 阶段的「同团 GM 可看交上来的卡」走注册表，不改默认规则。"""
    from apps.charactercards import services

    card = card_factory(is_public=False)
    gm = user_factory(nickname="同团GM", is_gm=True)
    assert services.can_view_file(gm, card) is False

    def checker(user, target_card):
        return user.pk == gm.pk

    services.register_file_access_checker(checker)
    try:
        assert services.can_view_file(gm, card) is True
    finally:
        services._file_access_checkers.remove(checker)


# --------------------------------------------------------------------------
# W5：卡池 ?owner= 筛选（个人空间的「TA 的公开卡」）
# --------------------------------------------------------------------------


def test_卡池按owner筛选只出那个人的公开卡(api_client, card_factory, user_factory):
    mine = user_factory(nickname="卡主")
    other = user_factory(nickname="别人")
    card_factory(mine, is_public=True, name="我的公开卡")
    card_factory(mine, is_public=False, name="我的私密卡")
    card_factory(other, is_public=True, name="别人的公开卡")

    body = api_client.get(f"{POOL_URL}?owner={mine.pk}").json()

    assert [row["name"] for row in body["results"]] == ["我的公开卡"]
    assert body["count"] == 1


def test_卡池owner筛选不会把自己的私密卡带出来(api_client, card_factory, user_factory):
    """哪怕查的是自己：卡池永远只是公开卡的子集，私密卡走 `mine/`。"""
    mine = user_factory(nickname="卡主二")
    card_factory(mine, is_public=False, name="不该出现")
    api_client.force_authenticate(mine)

    assert api_client.get(f"{POOL_URL}?owner={mine.pk}").json()["count"] == 0


def test_卡池owner筛选收到非法值当作查不到(api_client, card_factory):
    """超长数字 / 全角数字 / 文本：一律空结果，不许送进 DB 打成 500。"""
    card_factory(is_public=True, name="公开卡")
    for raw in ("9" * 25, "１２３", "abc", "-1", "0", "1.5"):
        response = api_client.get(f"{POOL_URL}?owner={raw}")
        assert response.status_code == 200, raw
        assert response.json()["count"] == 0, raw


def test_卡池不带owner时照常全量(api_client, card_factory, user_factory):
    card_factory(user_factory(), is_public=True)
    card_factory(user_factory(), is_public=True)
    assert api_client.get(POOL_URL).json()["count"] == 2


# --------------------------------------------------------------------------
# 卡池 ?ordering=（前端「按参团次数」排序走服务端，不再本页排序）
# --------------------------------------------------------------------------


@pytest.fixture
def pool_by_plays(card_factory):
    """三张公开卡：创建顺序与参团次数**故意错开**，两种排序结果不会碰巧相同。"""
    many = card_factory(is_public=True, name="参团最多")
    none = card_factory(is_public=True, name="没参过团")
    few = card_factory(is_public=True, name="参团一次")
    tie = card_factory(is_public=True, name="也参团一次")
    # play_count 是缓存字段，接口不可写；测试里直接改库模拟结团后的状态。
    CharacterCard.objects.filter(pk=many.pk).update(play_count=5)
    CharacterCard.objects.filter(pk__in=[few.pk, tie.pk]).update(play_count=1)
    return many, none, few, tie


def _pool_names(api_client, query: str = "") -> list[str]:
    return [row["name"] for row in api_client.get(f"{POOL_URL}{query}").json()["results"]]


def test_卡池默认序是新建在前(api_client, pool_by_plays):
    assert _pool_names(api_client) == ["也参团一次", "参团一次", "没参过团", "参团最多"]


def test_卡池按参团次数排序同次数按默认序(api_client, pool_by_plays):
    assert _pool_names(api_client, "?ordering=plays") == [
        "参团最多",
        "也参团一次",
        "参团一次",
        "没参过团",
    ]


@pytest.mark.parametrize("ordering", ["-play_count", "owner__email", "name", "?", "plays,owner__email", "PLAYS"])
def test_卡池白名单外的排序回落默认且不报错(api_client, pool_by_plays, ordering):
    """排序参数是一条信道（理由同招募列表），认不出的值一律回落默认序。"""
    response = api_client.get(f"{POOL_URL}?ordering={ordering}")
    assert response.status_code == 200
    assert [row["name"] for row in response.json()["results"]] == [
        "也参团一次",
        "参团一次",
        "没参过团",
        "参团最多",
    ]


def test_卡池排序与筛选分页同时生效(api_client, pool_by_plays):
    body = api_client.get(f"{POOL_URL}?ordering=plays&rule_system=coc&page_size=2").json()
    assert body["count"] == 4
    assert [row["name"] for row in body["results"]] == ["参团最多", "也参团一次"]
