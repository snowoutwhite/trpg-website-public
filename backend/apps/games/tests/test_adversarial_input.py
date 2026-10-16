"""对抗测试：输入攻击、筛选/排序参数、场次唯一性、定时任务幂等与时区。

攻击假设：
1. `announcement` / `requirements` 是 TextField，DRF 默认不限长 —— 能不能一次灌进 20 MB？
   （用户可自由填写的长文本必须有长度上限。）
2. 标签名能不能塞控制字符 / 零宽空格 / RTL override，做出视觉上同名的两个标签？
3. 筛选参数塞 `__class__`、`ordering` 塞 `gm__email` 会不会 500 或泄露排序线索？
4. 同一个团重复建同序号场次会不会 500（IntegrityError 直接冒到 WSGI）？
5. `games_autoclose` 反复跑会不会重复结团 / 重复发通知？换时区会不会把天数算错？
"""

from __future__ import annotations

import unicodedata
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.games import services
from apps.games.models import (
    GAME_FINISHED,
    GAME_RUNNING,
    SIGNUP_NO_CARD,
    Game,
    Session,
    Signup,
    Tag,
)

from .conftest import soon

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# 1. 长文本上限
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["announcement", "requirements"])
def test_公告与需求长文本必须有上限(api_client, gm_factory, field):
    """TextField + DRF 默认不限长 = 一个账号就能往库里灌几十 MB。"""
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {
            "title": "超长文本团",
            "start_at": soon(days=3).isoformat(),
            field: "啊" * 200_000,
        },
        format="json",
    )
    assert response.status_code == 400, f"{field} 没有长度上限"
    assert not Game.objects.filter(title="超长文本团").exists()


@pytest.mark.parametrize("field", ["announcement", "requirements"])
def test_PATCH也不能灌超长文本(api_client, game_factory, field):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/", {field: "啊" * 200_000}, format="json"
    )
    assert response.status_code == 400
    game.refresh_from_db()
    assert len(getattr(game, field)) < 1000


def test_正常长度的公告可以写(api_client, gm_factory):
    """正向对照：上限是安全上限，不是产品字数限制。"""
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "正常团", "start_at": soon(days=3).isoformat(), "announcement": "啊" * 5000},
        format="json",
    )
    assert response.status_code == 201


def test_标题超长被拒(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "标" * 500, "start_at": soon(days=3).isoformat()},
        format="json",
    )
    assert response.status_code == 400


def test_空白标题被拒(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    for title in ("", "   ", "\t\n"):
        response = api_client.post(
            "/api/v1/games/", {"title": title, "start_at": soon(days=3).isoformat()}, format="json"
        )
        assert response.status_code == 400


# --------------------------------------------------------------------------
# 2. 标签
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "\u6218\u200b\u5f79",  # 零宽空格：和「战役」肉眼无差
        "\u6218\u5f79\u202e",  # RTL override
        "\u6218\u5f79\ufeff",  # BOM
        "\u6218\x00\u5f79",  # NUL
        "\u6218\u5f79\n\u8dd1\u56e2",  # 换行
        "\u6218\u5f79\t",  # 制表符
    ],
)
def test_标签名不接受不可见字符(api_client, gm_factory, raw):
    """标签名是全站共享的、按名字 get_or_create 的公共命名空间。

    放行零宽/双向控制字符就能造出「看起来是同一个标签」的两枚标签，
    与昵称同形冒充是同一类问题（architecture 第 6 节第 6 条）。
    """
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "控制字符标签团", "start_at": soon(days=3).isoformat(), "tags": [raw]},
        format="json",
    )
    if response.status_code == 201:
        stored = list(Tag.objects.values_list("name", flat=True))
        for name in stored:
            bad = [ch for ch in name if unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Co", "Cn"}]
            assert not bad, f"标签名里存进了不可见字符：{name!r}"
    else:
        assert response.status_code == 400


def test_标签名全角会被归一化不产生同形重复(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    for name in ("ＣＯＣ", "COC"):
        response = api_client.post(
            "/api/v1/games/",
            {"title": f"标签团{name}", "start_at": soon(days=3).isoformat(), "tags": [name]},
            format="json",
        )
        assert response.status_code == 201
    assert Tag.objects.filter(name__in=["COC", "ＣＯＣ"]).count() == 1, "同形标签产生了两条记录"


def test_标签数量爆炸被拒(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {
            "title": "标签爆炸团",
            "start_at": soon(days=3).isoformat(),
            "tags": [f"标签{i}" for i in range(500)],
        },
        format="json",
    )
    assert response.status_code == 400
    assert Tag.objects.count() == 2  # 只有数据迁移预置的两枚


def test_标签名超长被拒(api_client, gm_factory):
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "长标签团", "start_at": soon(days=3).isoformat(), "tags": ["标" * 200]},
        format="json",
    )
    assert response.status_code == 400


def test_标签里的HTML按原文入库不被执行(api_client, gm_factory):
    """服务端只负责原样存与原样回（JSON），不做半吊子转义。"""
    payload = "<img src=x onerror=alert(1)>"
    api_client.force_authenticate(gm_factory())
    response = api_client.post(
        "/api/v1/games/",
        {"title": "XSS 标签团", "start_at": soon(days=3).isoformat(), "tags": [payload]},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["tags"] == [payload]
    assert response["content-type"].startswith("application/json")


# --------------------------------------------------------------------------
# 3. 筛选与排序参数
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "?status=__class__",
        "?status=recruiting'; DROP TABLE games_game;--",
        "?gm=0 OR 1=1",
        "?gm=__class__",
        "?tag=%",
        "?tag=__contains",
        "?rule_system=%",
        "?rule_system=_",
        "?ordering=gm__email",
        "?ordering=-gm__password",
        "?page_size=999999",
        "?page=-1",
    ],
)
def test_列表筛选参数注入不会500也不改变结果集(api_client, game_factory, query):
    game_factory(rule_system="COC")
    game_factory(rule_system="DND")
    baseline = api_client.get("/api/v1/games/")
    assert baseline.status_code == 200
    baseline_ids = [row["id"] for row in baseline.json()["results"]]

    response = api_client.get(f"/api/v1/games/{query}")
    assert response.status_code in (200, 400, 404), f"{query} 触发了 {response.status_code}"
    if response.status_code == 200 and query.startswith("?ordering"):
        assert [row["id"] for row in response.json()["results"]] == baseline_ids, (
            f"{query} 真的改变了排序 —— 任意字段排序会泄露排序线索"
        )
    assert Game.objects.count() == 2


def test_列表不返回GM邮箱且ordering不能按邮箱排(api_client, game_factory, gm_factory):
    """排序线索泄露：`?ordering=gm__email` 若生效，就能按邮箱字典序推断别人的邮箱。"""
    gm_factory(nickname="甲", email="aaa@example.com")
    game_factory(gm=gm_factory(nickname="乙", email="zzz@example.com"))
    game_factory(gm=gm_factory(nickname="丙", email="bbb@example.com"))

    asc = api_client.get("/api/v1/games/?ordering=gm__email")
    desc = api_client.get("/api/v1/games/?ordering=-gm__email")
    assert asc.status_code == desc.status_code == 200
    assert [r["id"] for r in asc.json()["results"]] == [r["id"] for r in desc.json()["results"]]
    assert "example.com" not in str(asc.json())


@pytest.mark.parametrize("query", ["?q=" + "x" * 5000, "?q=%", "?q=__class__"])
def test_标签搜索参数不会500(api_client, query):
    response = api_client.get(f"/api/v1/games/tags/{query}")
    assert response.status_code == 200


def test_我的报名筛选参数注入不会500(api_client, game_factory, user_factory):
    game = game_factory()
    player = user_factory()
    services.signup(game, player)
    api_client.force_authenticate(player)
    for query in ("?game_status=__class__", "?game_status=' OR 1=1--"):
        response = api_client.get(f"/api/v1/games/my-signups/{query}")
        assert response.status_code == 200
        assert response.json()["results"] == []


# --------------------------------------------------------------------------
# 4. 场次
# --------------------------------------------------------------------------


def test_重复场次序号不得500(api_client, game_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    first = api_client.post(f"/api/v1/games/{game.pk}/sessions/", {"index": 0}, format="json")
    assert first.status_code == 201
    second = api_client.post(f"/api/v1/games/{game.pk}/sessions/", {"index": 0}, format="json")
    assert second.status_code != 500, "重复场次序号把 IntegrityError 冒成了 500"
    assert second.status_code == 400
    assert Session.objects.filter(game=game).count() == 1


def test_PATCH场次撞序号不得500(api_client, game_factory):
    game = game_factory()
    services.create_session(game, index=0)
    second = services.create_session(game, index=1)
    api_client.force_authenticate(game.gm)
    response = api_client.patch(
        f"/api/v1/games/{game.pk}/sessions/{second.pk}/", {"index": 0}, format="json"
    )
    assert response.status_code != 500, "PATCH 场次撞序号把 IntegrityError 冒成了 500"
    second.refresh_from_db()
    assert second.index == 1


def test_不同团可以有同序号场次(api_client, game_factory):
    a = game_factory()
    b = game_factory(gm=a.gm)
    services.create_session(a, index=0)
    services.create_session(b, index=0)
    assert Session.objects.count() == 2


def test_场次名称超长被拒(api_client, game_factory):
    game = game_factory()
    api_client.force_authenticate(game.gm)
    response = api_client.post(
        f"/api/v1/games/{game.pk}/sessions/", {"index": 1, "label": "回" * 500}, format="json"
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# 5. 定时任务
# --------------------------------------------------------------------------


def _due_game(game_factory, user_factory, card_factory, *, days_ago: int):
    """造一个「开团时间在 N 天前、有一名交过卡的 PL」的团。"""
    moment = timezone.now() + timedelta(days=1)
    game = game_factory(start_at=moment, card_deadline=moment, max_players=5)
    player = user_factory()
    record = services.signup(game, player)
    services.submit_card(record, card_factory(player))
    game.start_at = timezone.now() - timedelta(days=days_ago)
    game.card_deadline = game.start_at
    game.save(update_fields=["start_at", "card_deadline"])
    record.refresh_from_db()
    return game, player, record


def test_autoclose重复运行不重复结团不重复发通知(
    game_factory, user_factory, card_factory, site_config
):
    from apps.notifications.models import Notification

    game, player, record = _due_game(game_factory, user_factory, card_factory, days_ago=8)

    call_command("games_autoclose")
    game.refresh_from_db()
    record.refresh_from_db()
    assert game.status == GAME_FINISHED
    assert game.auto_closed is True
    assert record.attended is True
    finished_at = game.finished_at
    after_first = Notification.objects.count()
    assert after_first > 0

    for _ in range(3):
        call_command("games_autoclose")
    game.refresh_from_db()
    assert game.finished_at == finished_at, "重复运行把结团时间刷新了"
    assert Notification.objects.count() == after_first, "重复运行重复发了通知"
    assert services.player_games_played(player) == 1
    assert record.card.play_count == 1 or True  # 计数在 finish_game 已覆盖
    record.card.refresh_from_db()
    assert record.card.play_count == 1


def test_autoclose天数边界(game_factory, user_factory, card_factory, site_config):
    """站点配置 `auto_close_days`（默认 7）：差一点不结，到点才结。"""
    assert site_config.auto_close_days == 7
    early, _, _ = _due_game(game_factory, user_factory, card_factory, days_ago=6)
    late, _, _ = _due_game(game_factory, user_factory, card_factory, days_ago=7)

    services.auto_close_games()
    early.refresh_from_db()
    late.refresh_from_db()
    assert early.status != GAME_FINISHED
    assert late.status == GAME_FINISHED


def test_autoclose不受激活时区影响(game_factory, user_factory, card_factory, site_config):
    """所有判定都是 aware datetime 的加减，不该有任何「按本地日期切换」的行为。"""
    from django.utils import timezone as tz

    results = []
    for zone in ("Asia/Shanghai", "UTC", "America/New_York"):
        game, _, _ = _due_game(game_factory, user_factory, card_factory, days_ago=8)
        tz.activate(zone)
        try:
            services.auto_close_games()
        finally:
            tz.deactivate()
        game.refresh_from_db()
        results.append(game.status)
    assert results == [GAME_FINISHED] * 3


def test_autoclose提醒每团只发一次(game_factory, user_factory, card_factory, site_config):
    from apps.notifications import events
    from apps.notifications.models import Notification

    moment = timezone.now() + timedelta(hours=6)
    game = game_factory(start_at=moment, card_deadline=moment, max_players=5)
    services.signup(game, user_factory())

    call_command("games_autoclose")
    first = {
        events.CARD_DEADLINE_REMINDER: Notification.objects.filter(
            event=events.CARD_DEADLINE_REMINDER
        ).count(),
        events.GAME_START_REMINDER: Notification.objects.filter(
            event=events.GAME_START_REMINDER
        ).count(),
    }
    assert first[events.CARD_DEADLINE_REMINDER] == 1
    assert first[events.GAME_START_REMINDER] >= 1

    for _ in range(3):
        call_command("games_autoclose")
    for event, count in first.items():
        assert Notification.objects.filter(event=event).count() == count, f"{event} 重复发送"


def test_未交卡者在自动流程里会被标出来(game_factory, user_factory, site_config):
    """`run_autoclose_cycle` 先把到点的团刷成 running，之后的未交卡扫描必须仍然覆盖它们。"""
    moment = timezone.now() + timedelta(days=1)
    game = game_factory(start_at=moment, card_deadline=moment, max_players=5)
    player = user_factory()
    record = services.signup(game, player)
    game.start_at = timezone.now() - timedelta(hours=2)
    game.card_deadline = game.start_at
    game.save(update_fields=["start_at", "card_deadline"])

    services.run_autoclose_cycle()
    game.refresh_from_db()
    record.refresh_from_db()
    assert game.status in (GAME_RUNNING, GAME_FINISHED)
    assert record.status == SIGNUP_NO_CARD, "到点的团里未交卡的人没有被标记"


def test_未交卡被清出后位置重新开放(game_factory, user_factory):
    """满员 → 未交卡者被清出 → 位置空了，状态必须回到招募中。

    architecture 16.2：「有人退出/被移除或 GM 扩容后自动回到 recruiting」。
    """
    moment = timezone.now() + timedelta(days=1)
    game = game_factory(start_at=moment, card_deadline=moment, max_players=1)
    services.signup(game, user_factory())
    game.refresh_from_db()
    assert game.status == "closed_signup"

    game.card_deadline = timezone.now() - timedelta(minutes=5)
    game.save(update_fields=["card_deadline"])
    services.mark_no_card_signups(game)

    game.refresh_from_db()
    assert game.occupied_seats == 0
    assert game.status == "recruiting", "未交卡者被清出后位置没有重新开放"


def test_autoclose不碰已取消的团(game_factory, user_factory, card_factory, site_config):
    game, _, _ = _due_game(game_factory, user_factory, card_factory, days_ago=30)
    services.cancel_game(game, reason="早就散了")
    call_command("games_autoclose")
    game.refresh_from_db()
    assert game.status == "cancelled"
    assert game.finished_at is None


def test_autoclose空跑不报错(site_config):
    call_command("games_autoclose")
    assert Game.objects.count() == 0
    assert Signup.objects.count() == 0


def test_团名含RTL覆盖字符一律400(api_client, game_factory):
    """业务规则与安全约束。"""
    game = game_factory()
    before = game.title
    api_client.force_authenticate(game.gm)
    response = api_client.patch(f"/api/v1/games/{game.pk}/", {"title": "坏\u202e团"}, format="json")
    assert response.status_code == 400, response.content
    game.refresh_from_db()
    assert game.title == before
