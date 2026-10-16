"""「其他」筛选：`games/?rule_system=__other__`、`games/?tag=__other__`、卡池 `?rule_system=__other__`。

口径（`docs/dev/v2同步-实施方案.md`「后端新增」第 3 项）：
- 规则：排除站级预设，**大小写不敏感**；没填规则的也算「其他」。
- 标签：不带任何**预设**标签的团（GM 自建标签不影响）。
哨兵 `__other__` 本身大小写敏感，见对抗用例。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def gm(db, user_factory):
    user = user_factory(nickname="筛选GM")
    user.is_gm = True
    user.save(update_fields=["is_gm"])
    return user


@pytest.fixture
def make_game(db, gm):
    from apps.games import services

    def make(title: str, *, rule_system: str = "", tags=None, **kwargs):
        return services.create_game(
            gm,
            title=title,
            rule_system=rule_system,
            start_at=timezone.now() + timedelta(days=3),
            min_players=1,
            max_players=5,
            tags=tags,
            **kwargs,
        )

    return make


def _titles(response) -> set[str]:
    return {row["title"] for row in response.json()["results"]}


def test_规则其他排掉全部站级预设(api_client, make_game):
    make_game("预设团", rule_system="COC")
    make_game("小写预设团", rule_system="coc")
    make_game("自定义团", rule_system="PBTA")
    make_game("没填规则的团")

    response = api_client.get("/api/v1/games/?rule_system=__other__")
    assert response.status_code == 200
    assert _titles(response) == {"自定义团", "没填规则的团"}


def test_规则其他对四条预设全都生效(api_client, make_game):
    for name in ("FU", "COC", "DND", "三角机构"):
        make_game(f"{name}团", rule_system=name)
    make_game("别的规则", rule_system="Blades")

    assert _titles(api_client.get("/api/v1/games/?rule_system=__other__")) == {"别的规则"}


def test_新增预设后其他的集合跟着变(api_client, make_game):
    from apps.homecontent.models import RuleSystemPreset

    make_game("PBTA团", rule_system="PBTA")
    assert "PBTA团" in _titles(api_client.get("/api/v1/games/?rule_system=__other__"))

    RuleSystemPreset.objects.create(name="PBTA", sort=50)
    assert "PBTA团" not in _titles(api_client.get("/api/v1/games/?rule_system=__other__"))


def test_标签其他只留不带预设标签的团(api_client, make_game):
    make_game("战役团", tags=["战役"])
    make_game("西征团", tags=["西征"])
    make_game("混合团", tags=["战役", "夜场"])
    make_game("自建标签团", tags=["夜场"])
    make_game("没标签的团")

    assert _titles(api_client.get("/api/v1/games/?tag=__other__")) == {"自建标签团", "没标签的团"}


def test_普通标签筛选不受影响(api_client, make_game):
    make_game("战役团", tags=["战役"])
    make_game("夜场团", tags=["夜场"])
    assert _titles(api_client.get("/api/v1/games/?tag=战役")) == {"战役团"}


def test_卡池其他排掉站级预设(api_client, user_factory):
    from apps.charactercards import services

    owner = user_factory(nickname="卡主")
    services.create_card(owner, name="调查员", rule_system="COC", is_public=True)
    services.create_card(owner, name="小写调查员", rule_system="coc", is_public=True)
    services.create_card(owner, name="自定义卡", rule_system="PBTA", is_public=True)
    services.create_card(owner, name="没规则的卡", is_public=True)

    response = api_client.get("/api/v1/charactercards/pool/?rule_system=__other__")
    assert response.status_code == 200
    assert {row["name"] for row in response.json()["results"]} == {"自定义卡", "没规则的卡"}
