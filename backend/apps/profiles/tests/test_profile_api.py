"""个人空间与自己的卡片接口：公开面绝不含邮箱。"""

from __future__ import annotations

import pytest

from apps.profiles.models import GMCard, PlayerCard

pytestmark = pytest.mark.django_db


def test_注册即建玩家卡(user_factory):
    user = user_factory(nickname="新人")
    assert PlayerCard.objects.filter(user=user).exists()
    assert not GMCard.objects.filter(user=user).exists()


def test_置为GM时建GM卡(user_factory):
    user = user_factory(nickname="升级的")
    user.is_gm = True
    user.save()
    assert GMCard.objects.filter(user=user).exists()


def test_个人空间游客可看且不含邮箱(api_client, user_factory):
    user = user_factory(nickname="公开的", email="secret@example.com")
    response = api_client.get(f"/api/v1/profiles/users/{user.pk}/")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["nickname"] == "公开的"
    assert "email" not in body["user"]
    assert "secret@example.com" not in response.content.decode()


def test_档位未公布时不回传赞与倒赞计数(api_client, user_factory):
    user = user_factory(nickname="评价少的")
    card = user.player_card
    card.likes = 5
    card.dislikes = 1
    card.reviews_received = 6
    card.save()
    body = api_client.get(f"/api/v1/profiles/users/{user.pk}/").json()
    assert body["player_card"]["level"] == ""
    assert body["player_card"]["likes"] is None
    assert body["player_card"]["dislikes"] is None


def test_自己的玩家卡可改(api_client, user_factory):
    user = user_factory(nickname="改卡的")
    api_client.force_authenticate(user=user)
    response = api_client.patch(
        "/api/v1/profiles/me/player-card/",
        {"taboos": "不接受 PVP", "preferred_rule_systems": ["COC", "自定义规则"], "free_text": "新人一枚"},
        format="json",
    )
    assert response.status_code == 200
    card = PlayerCard.objects.get(user=user)
    assert card.taboos == "不接受 PVP"
    assert card.preferred_rule_systems == ["COC", "自定义规则"]


def test_玩家卡的统计字段是只读的(api_client, user_factory):
    user = user_factory(nickname="想刷数据的")
    api_client.force_authenticate(user=user)
    api_client.patch("/api/v1/profiles/me/player-card/", {"games_played": 999}, format="json")
    assert PlayerCard.objects.get(user=user).games_played == 0


def test_非GM拿不到GM卡(api_client, user_factory):
    user = user_factory(nickname="还不是GM")
    api_client.force_authenticate(user=user)
    response = api_client.get("/api/v1/profiles/me/gm-card/")
    assert response.status_code == 403  # W5 状态码统一：身份类拒绝 → 403
    #  拆码：这一处是「你尚未成为 GM，暂无 GM 卡」，与 games 放团的 `not_gm` 不是一件事。
    assert response.json()["error"]["code"] == "no_gm_card"


def test_重算卡片用注册的provider(user_factory, site_config, monkeypatch):
    from apps.profiles import stats
    from apps.profiles.services import recompute_player_card

    def fake_provider(user):
        return {"games_played": 7, "reviews_received": 12, "likes": 11, "dislikes": 1}

    # 只保留本用例的 provider：注册表是全局的，其他 app 在 ready() 里注册的
    # provider 会一起被调用，测「注册表本身」时必须先隔离，否则用例的成败
    # 取决于别的 app 当下的实现状态。
    monkeypatch.setattr(stats, "_player_providers", [fake_provider])

    card = recompute_player_card(user_factory(nickname="被重算的"))
    assert card.games_played == 7
    assert card.reviews_received == 12
    assert card.level == "overwhelmingly_positive"


# --------------------------------------------------------------------------
# W5：三个计数一起进公布阈值闸；本人卡与公开卡同一口径
# --------------------------------------------------------------------------


def _set_counts(user, *, likes: int, dislikes: int):
    from apps.profiles.services import level_for

    card = user.player_card
    card.likes = likes
    card.dislikes = dislikes
    card.reviews_received = likes + dislikes
    card.level = level_for(likes, dislikes, likes + dislikes) or ""
    card.save()
    return card


def test_未达阈值时被评次数也回null(api_client, user_factory, site_config):
    """`reviews_received` 是实时跳动的：单独露出去，第三方轮询就能测出「刚才有人评了他」。"""
    user = user_factory(nickname="被评次数少的")
    _set_counts(user, likes=5, dislikes=1)
    assert site_config.like_level_publish_threshold == 10

    public = api_client.get(f"/api/v1/profiles/users/{user.pk}/").json()["player_card"]
    api_client.force_authenticate(user)
    mine = api_client.get("/api/v1/profiles/me/player-card/").json()

    for body in (public, mine):
        assert body["likes"] is None
        assert body["dislikes"] is None
        assert body["reviews_received"] is None
        assert body["level"] == ""


def test_达到阈值后同时露出档位与三个数字(api_client, user_factory, site_config):
    user = user_factory(nickname="评价够多的")
    _set_counts(user, likes=9, dislikes=3)  # 12 ≥ 阈值 10
    assert site_config.like_level_publish_threshold == 10

    public = api_client.get(f"/api/v1/profiles/users/{user.pk}/").json()["player_card"]
    api_client.force_authenticate(user)
    mine = api_client.get("/api/v1/profiles/me/player-card/").json()

    for body in (public, mine):
        assert body["likes"] == 9
        assert body["dislikes"] == 3
        assert body["reviews_received"] == 12
        assert body["level"] != ""
        assert body["level_display"]


def test_关掉赞功能后连达阈值的数字也不露(api_client, user_factory, site_config):
    user = user_factory(nickname="关功能后的")
    _set_counts(user, likes=9, dislikes=3)
    site_config.like_feature_enabled = False
    site_config.save()

    body = api_client.get(f"/api/v1/profiles/users/{user.pk}/").json()["player_card"]

    assert (body["likes"], body["dislikes"], body["reviews_received"]) == (None, None, None)


def test_GM卡同样受阈值闸约束(api_client, user_factory, site_config):
    user = user_factory(nickname="GM卡阈值")
    user.is_gm = True
    user.save(update_fields=["is_gm"])
    card = user.gm_card
    card.likes, card.dislikes, card.reviews_received = 4, 1, 5
    card.save()

    public = api_client.get(f"/api/v1/profiles/users/{user.pk}/").json()["gm_card"]
    api_client.force_authenticate(user)
    mine = api_client.get("/api/v1/profiles/me/gm-card/").json()

    for body in (public, mine):
        assert (body["likes"], body["dislikes"], body["reviews_received"]) == (None, None, None)
