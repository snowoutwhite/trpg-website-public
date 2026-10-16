"""战报列表的服务端筛选：`?rule_system=`（含 `__other__` 哨兵）与 `?mine=1`。

前端战报页原先拿一页数据回来再本地过滤，翻页计数和筛选结果都对不上；
这里钉住服务端口径，前端直接把筛选条作为请求参数发过来。
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.games.models import SIGNUP_REMOVED
from apps.reports.models import VISIBILITY_SAME_GAME

pytestmark = pytest.mark.django_db

LIST_URL = reverse("v1:reports:report-list")


def _titles(response) -> set[str]:
    return {row["title"] for row in response.json()["results"]}


@pytest.fixture
def rules_world(game_factory, report_factory, user_factory):
    """三个团各一份公开战报：预设 COC、小写 coc、非预设 Blades、空规则名。"""
    author = user_factory()
    for title, rule in (("COC战报", "COC"), ("小写coc战报", "coc"), ("Blades战报", "Blades"), ("空规则战报", "")):
        report_factory(game_factory(rule_system=rule), author, title=title)
    return author


def test_规则筛选大小写不敏感命中(api_client, rules_world):
    api_client.force_authenticate(rules_world)
    response = api_client.get(f"{LIST_URL}?rule_system=coc")
    assert response.status_code == 200
    assert _titles(response) == {"COC战报", "小写coc战报"}


def test_规则其他哨兵排掉站级预设(api_client, rules_world):
    """与团列表同口径：团的规则名不命中任何预设（大小写不敏感），空规则名也算「其他」。"""
    api_client.force_authenticate(rules_world)
    response = api_client.get(f"{LIST_URL}?rule_system=__other__")
    assert response.status_code == 200
    assert _titles(response) == {"Blades战报", "空规则战报"}


def test_哨兵大小写敏感大写当普通规则名(api_client, rules_world):
    api_client.force_authenticate(rules_world)
    assert _titles(api_client.get(f"{LIST_URL}?rule_system=__OTHER__")) == set()


def test_规则筛选不越过可见性(api_client, rules_world):
    """游客只见精选：筛选只在可见集合里再收窄，不会把非精选战报带出来。"""
    assert _titles(api_client.get(f"{LIST_URL}?rule_system=Blades")) == set()


@pytest.fixture
def mine_world(game_factory, attendee_factory, report_factory, user_factory, gm_factory):
    me = user_factory(nickname="我")
    stranger = user_factory()
    my_gm = gm_factory(nickname="我当GM")
    hosted = game_factory(gm=my_gm, title="我主持的团")
    attended = game_factory(title="我到场的团")
    attendee_factory(attended, me)
    removed = game_factory(title="我被移出的团")
    attendee_factory(removed, me, status=SIGNUP_REMOVED)  # 到场快照在，但已不在正式名单
    unrelated = game_factory(title="无关的团")

    report_factory(hosted, stranger, title="主持团的战报")
    report_factory(attended, stranger, title="到场团的战报", is_featured=True)
    report_factory(removed, stranger, title="被移出团的战报")
    report_factory(unrelated, stranger, title="无关团的战报", is_featured=True)
    return {"me": me, "my_gm": my_gm, "stranger": stranger}


def test_mine只留到场过的团(api_client, mine_world):
    api_client.force_authenticate(mine_world["me"])
    response = api_client.get(f"{LIST_URL}?mine=1")
    assert response.status_code == 200
    # 被移出的团不算「到场」—— 与 same_game 可见性共用 `member_game_ids` 的判据。
    assert _titles(response) == {"到场团的战报"}


def test_mine包含主持过的团(api_client, mine_world):
    api_client.force_authenticate(mine_world["my_gm"])
    assert _titles(api_client.get(f"{LIST_URL}?mine=1")) == {"主持团的战报"}


def test_mine游客返回空页(api_client, mine_world):
    """游客没有「我」：直接空页，而不是把 `mine` 忽略掉回全量精选。"""
    body = api_client.get(f"{LIST_URL}?mine=1").json()
    assert body == {"count": 0, "next": None, "previous": None, "results": []}


def test_mine封禁会话按游客算返回空页(api_client, mine_world):
    from apps.accounts.services import ban_user

    ban_user(mine_world["me"], reason="违规")
    api_client.force_authenticate(mine_world["me"])
    assert api_client.get(f"{LIST_URL}?mine=1").json()["count"] == 0


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_mine非1的值静默忽略(api_client, mine_world, value):
    api_client.force_authenticate(mine_world["me"])
    response = api_client.get(f"{LIST_URL}?mine={value}")
    assert response.status_code == 200
    assert "无关团的战报" in _titles(response)


def test_mine带出本团的仅同团战报(api_client, mine_world, game_factory, attendee_factory, report_factory):
    """mine 只是在可见集合里收窄；同团的 same_game 战报本来就可见，也应该在里面。"""
    game = game_factory(title="又一个到场的团")
    attendee_factory(game, mine_world["me"])
    report_factory(game, mine_world["stranger"], title="仅同团战报", visibility=VISIBILITY_SAME_GAME)
    api_client.force_authenticate(mine_world["me"])
    assert "仅同团战报" in _titles(api_client.get(f"{LIST_URL}?mine=1"))


def test_精选接口也认规则筛选(api_client, game_factory, report_factory, user_factory):
    """游客只有「精选」一档，规则筹码得在精选接口上也走服务端。"""
    author = user_factory()
    report_factory(game_factory(rule_system="COC"), author, title="精选COC", is_featured=True)
    report_factory(game_factory(rule_system="Blades"), author, title="精选Blades", is_featured=True)
    url = reverse("v1:reports:report-featured")
    assert _titles(api_client.get(f"{url}?rule_system=coc")) == {"精选COC"}
    assert _titles(api_client.get(f"{url}?rule_system=__other__")) == {"精选Blades"}
    assert _titles(api_client.get(f"{url}?rule_system=")) == {"精选COC", "精选Blades"}
