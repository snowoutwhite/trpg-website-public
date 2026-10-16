"""对抗性测试 · 个人空间与卡片：隐私泄露、越权改别人的卡、五档边界与除零。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.profiles.levels import (
    MIXED,
    MOSTLY_NEGATIVE,
    MOSTLY_POSITIVE,
    OVERWHELMINGLY_NEGATIVE,
    OVERWHELMINGLY_POSITIVE,
)
from apps.profiles.services import ensure_gm_card, ensure_player_card, level_for

pytestmark = pytest.mark.django_db

MY_PLAYER = "/api/v1/profiles/me/player-card/"
MY_GM = "/api/v1/profiles/me/gm-card/"


def profile_url(user_id: int) -> str:
    return f"/api/v1/profiles/users/{user_id}/"


# ------------------------------------------------------------------ 隐私


def test_public_profile_never_leaks_email_or_moderation_state(api_client, user_factory):
    victim = user_factory(nickname="被看的", email="peek@example.com")
    victim.is_muted = True
    victim.mute_reason = "禁言理由不该外露"
    victim.save(update_fields=["is_muted", "mute_reason"])

    body = api_client.get(profile_url(victim.pk)).content.decode()
    for secret in [
        "peek@example.com",
        "禁言理由不该外露",
        "is_muted",
        "is_banned",
        "is_staff",
        "is_superuser",
        "anonymized_email_hash",
        "last_login",
        "date_joined",
        "password",
    ]:
        assert secret not in body, f"个人空间泄露了 {secret}"


def test_public_profile_user_fields_are_exactly_the_whitelist(api_client, user_factory):
    victim = user_factory(nickname="被看的B", email="peek-b@example.com")
    data = api_client.get(profile_url(victim.pk)).json()
    assert set(data["user"]) == {"id", "nickname", "avatar", "is_gm"}


def test_banned_user_profile_is_hidden(api_client, user_factory):
    from apps.accounts.services import ban_user

    victim = user_factory(nickname="被封的C", email="banned-c@example.com")
    ban_user(victim, reason="违规")
    assert api_client.get(profile_url(victim.pk)).status_code == 404


def test_unpublished_level_hides_like_counts(api_client, user_factory, site_config):
    """档位未公布时，赞/倒赞绝对值也不能外露 —— 否则能手算比例绕过阈值。"""
    site_config.like_level_publish_threshold = 10
    site_config.save()

    victim = user_factory(nickname="评价少的D", email="few-d@example.com")
    card = ensure_player_card(victim)
    card.likes = 2
    card.dislikes = 1
    card.reviews_received = 3
    card.level = ""
    card.save()

    data = api_client.get(profile_url(victim.pk)).json()["player_card"]
    assert data["likes"] is None
    assert data["dislikes"] is None
    assert data["level"] == ""


def test_my_card_view_does_not_expose_other_cards(api_client, user_factory):
    victim = user_factory(nickname="别人E", email="other-e@example.com")
    victim_card = ensure_player_card(victim)
    victim_card.taboos = "别人的雷点EEE"
    victim_card.save()

    attacker = user_factory(nickname="攻击E", email="attacker-e@example.com")
    api_client.force_authenticate(attacker)
    body = api_client.get(MY_PLAYER).content.decode()
    assert "别人的雷点EEE" not in body


# ------------------------------------------------------------------ 越权写


def test_cannot_patch_someone_elses_card(api_client, user_factory):
    victim = user_factory(nickname="别人F", email="other-f@example.com")
    ensure_player_card(victim)
    attacker = user_factory(nickname="攻击F", email="attacker-f@example.com")

    api_client.force_authenticate(attacker)
    response = api_client.patch(
        MY_PLAYER,
        {"taboos": "被篡改", "user": victim.pk, "id": victim.pk},
        format="json",
    )
    assert response.status_code == 200

    victim_card = ensure_player_card(victim)
    assert victim_card.taboos == ""
    assert ensure_player_card(attacker).taboos == "被篡改"


def test_cannot_forge_card_statistics(api_client, user_factory):
    """赞数、参团次数、档位都是服务端算的，客户端写不进去。"""
    user = user_factory(nickname="刷声望G", email="fame-g@example.com")
    ensure_player_card(user)
    api_client.force_authenticate(user)

    response = api_client.patch(
        MY_PLAYER,
        {
            "likes": 9999,
            "dislikes": 0,
            "reviews_received": 9999,
            "games_played": 9999,
            "level": OVERWHELMINGLY_POSITIVE,
        },
        format="json",
    )
    assert response.status_code == 200

    card = ensure_player_card(user)
    assert card.likes == 0
    assert card.dislikes == 0
    assert card.reviews_received == 0
    assert card.games_played == 0
    assert card.level == ""


def test_non_gm_cannot_touch_gm_card(api_client, user_factory):
    user = user_factory(nickname="非GM_H", email="notgm-h@example.com")
    api_client.force_authenticate(user)
    assert api_client.get(MY_GM).status_code == 403  # W5 状态码统一：身份类拒绝 → 403
    response = api_client.patch(MY_GM, {"style_text": "我是GM"}, format="json")
    assert response.status_code == 403
    #  拆码：profiles 这一处从 `not_gm` 改成 `no_gm_card`，
    # 与 games「只有 GM 才能放团」的 `not_gm` 分开（一码多义，前端按 code 映射会串话）。
    assert response.json()["error"]["code"] == "no_gm_card"

    from apps.profiles.models import GMCard

    assert not GMCard.objects.filter(user=user).exists()


def test_guest_cannot_touch_my_cards(api_client):
    for method, path in [
        ("get", MY_PLAYER),
        ("patch", MY_PLAYER),
        ("get", MY_GM),
        ("patch", MY_GM),
    ]:
        response = getattr(api_client, method)(path, {}, format="json")
        assert response.status_code in (401, 403), f"{method} {path} → {response.status_code}"


def test_rule_systems_input_is_bounded(api_client, user_factory):
    user = user_factory(nickname="乱填规则I", email="rules-i@example.com")
    ensure_player_card(user)
    api_client.force_authenticate(user)

    assert (
        api_client.patch(
            MY_PLAYER, {"preferred_rule_systems": [f"规则{i}" for i in range(50)]}, format="json"
        ).status_code
        == 400
    )
    assert (
        api_client.patch(
            MY_PLAYER, {"preferred_rule_systems": "不是数组"}, format="json"
        ).status_code
        == 400
    )
    assert (
        api_client.patch(
            MY_PLAYER, {"preferred_rule_systems": [{"a": 1}]}, format="json"
        ).status_code
        == 400
    )


def test_free_text_fields_are_length_capped(api_client, user_factory):
    """自由文本不设上限的话，单个账号就能往库里塞十几 MB。"""
    user = user_factory(nickname="灌水J", email="flood-j@example.com")
    ensure_player_card(user)
    api_client.force_authenticate(user)

    response = api_client.patch(MY_PLAYER, {"free_text": "水" * 200_000}, format="json")
    assert response.status_code == 400, "自由文本没有长度上限"


# ------------------------------------------------------------------ 五档计算


def test_level_is_none_below_threshold(site_config):
    site_config.like_level_publish_threshold = 10
    site_config.save()
    assert level_for(9, 0, 9) is None


def test_level_is_computed_exactly_at_threshold(site_config):
    """恰好等于阈值就要公布（`total < threshold` 才不公布）。"""
    site_config.like_level_publish_threshold = 10
    site_config.save()
    assert level_for(10, 0, 10) == OVERWHELMINGLY_POSITIVE


def test_level_handles_zero_denominator(site_config):
    """分母 = 赞 + 倒赞 + 无评价：为 0 时不能除零，也不能瞎给一个档；全是无评价则是中性。"""
    site_config.like_level_publish_threshold = 3
    site_config.save()
    assert level_for(0, 0, 10) == MIXED
    assert level_for(0, 0, 0) is None


@pytest.mark.parametrize(
    "like,dislike,none,expected",
    [
        (80, 20, 0, OVERWHELMINGLY_POSITIVE),  # 赞恰好 0.800
        (799, 201, 0, MOSTLY_POSITIVE),  # 赞 0.799，差一点
        (60, 40, 0, MOSTLY_POSITIVE),  # 赞恰好 0.600（倒赞同时 0.400，先看好评）
        (599, 401, 0, MOSTLY_NEGATIVE),  # 倒赞 0.401
        (600, 399, 1, MOSTLY_POSITIVE),
        (599, 399, 2, MIXED),  # 赞 0.599、倒赞 0.399
        (40, 60, 0, OVERWHELMINGLY_NEGATIVE),  # 倒赞恰好 0.600
        (401, 599, 0, MOSTLY_NEGATIVE),  # 倒赞 0.599
        (0, 100, 0, OVERWHELMINGLY_NEGATIVE),
        (100, 0, 0, OVERWHELMINGLY_POSITIVE),
        (0, 0, 100, MIXED),
    ],
)
def test_level_boundaries_are_inclusive_on_the_lower_edge(site_config, like, dislike, none, expected):
    site_config.like_level_publish_threshold = 1
    site_config.save()
    assert level_for(like, dislike, like + dislike + none) == expected


def test_level_respects_like_feature_switch(site_config):
    site_config.like_level_publish_threshold = 1
    site_config.like_feature_enabled = False
    site_config.save()
    assert level_for(100, 0, 100) is None


def test_level_boundaries_follow_site_config(site_config):
    """五档边界是站主可调的：改了配置，判定必须跟着改，不能硬编码。"""
    site_config.like_level_publish_threshold = 1
    site_config.level_overwhelmingly_positive_min = Decimal("0.950")
    site_config.level_mostly_positive_min = Decimal("0.900")
    site_config.level_overwhelmingly_negative_dislike_min = Decimal("0.500")
    site_config.level_mostly_negative_dislike_min = Decimal("0.100")
    site_config.save()

    assert level_for(90, 10, 100) == MOSTLY_POSITIVE
    assert level_for(95, 5, 100) == OVERWHELMINGLY_POSITIVE
    assert level_for(60, 40, 100) == MOSTLY_NEGATIVE
    assert level_for(85, 5, 100) == MIXED


def test_site_config_rejects_non_monotonic_boundaries(site_config):
    from django.core.exceptions import ValidationError

    site_config.level_overwhelmingly_positive_min = Decimal("0.100")
    site_config.level_mostly_positive_min = Decimal("0.600")
    with pytest.raises(ValidationError):
        site_config.full_clean()


def test_site_config_rejects_non_monotonic_dislike_boundaries(site_config):
    from django.core.exceptions import ValidationError

    site_config.level_overwhelmingly_negative_dislike_min = Decimal("0.300")
    site_config.level_mostly_negative_dislike_min = Decimal("0.400")
    with pytest.raises(ValidationError):
        site_config.full_clean()


def test_recompute_never_writes_a_level_that_is_not_published(
    site_config, user_factory, monkeypatch
):
    """评价数没到阈值就重算，也不许把档位写进库（写了就等于提前公布）。"""
    from apps.profiles import stats
    from apps.profiles.services import recompute_player_card

    site_config.like_level_publish_threshold = 10
    site_config.save()
    user = user_factory(nickname="重算K", email="recompute-k@example.com")

    def provider(target):
        return {"likes": 3, "dislikes": 0, "reviews_received": 3, "games_played": 3}

    # 只留本用例的 provider，避免依赖其他 app 在 ready() 里注册的那些
    monkeypatch.setattr(stats, "_player_providers", [provider])

    card = recompute_player_card(user)
    assert card.level == ""
    assert card.likes == 3


def test_gm_card_public_view_hides_counts_until_published(api_client, user_factory, site_config):
    site_config.like_level_publish_threshold = 10
    site_config.save()
    gm = user_factory(nickname="GM_L", email="gm-l@example.com")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    card = ensure_gm_card(gm)
    card.likes = 4
    card.dislikes = 4
    card.reviews_received = 8
    card.level = ""
    card.save()

    data = api_client.get(profile_url(gm.pk)).json()["gm_card"]
    assert data["likes"] is None
    assert data["dislikes"] is None
