"""红队（W3 对抗测试）：时间锁与统计侧信道。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.games import services as game_services
from apps.games.models import GAME_FINISHED, GAME_RUNNING
from apps.reviews import services
from apps.reviews.tests.conftest import RECEIVED_URL, mutual_url

pytestmark = pytest.mark.django_db


def _mint_empty_finished_game(gm, *, title="空团"):
    """GM 凭空开一个零人团并试图立刻结团：走的是 games 的生产路径。

    W5 起 `finish_game` 直接拒绝零到场的团（`no_attendee`），所以这条攻击连
    「结出一个空团」这一步都走不完 —— 时间锁在 games 层多了一道前置闸。
    下面两条用例继续钉住最终效果：无论试多少次，延迟都不会被刷掉。
    """
    game = game_services.create_game(gm, title=title, start_at=timezone.now())
    game = game_services.start_game(game)
    with pytest.raises(game_services.NoAttendee):
        game_services.finish_game(game, attended_signup_ids=[])
    return game


# --------------------------------------------------------------------------
# 1. 刷团解锁：延迟计数必须只认「真的有别人在场」的团
# --------------------------------------------------------------------------


def test_连开空团不能提前解锁收到的评价(gm_factory, user_factory, game_factory, submit, api_client):
    """攻击：被评者自己是 GM，结团后立刻连开 3 个零人团，把延迟锁当场刷掉。

    3 人团里只有 1 个人能评自己，提前读到评价 = 直接锁定评价人。
    """
    host = gm_factory()
    attacker = gm_factory()
    other = user_factory()
    game = game_factory(host, [attacker, other])
    submit(other, game, attacker, verdict="dislike", text="倒赞正文")

    for index in range(3):
        _mint_empty_finished_game(attacker, title=f"刷延迟{index}")

    api_client.force_authenticate(attacker)
    payload = api_client.get(RECEIVED_URL).json()
    assert payload["results"] == [], "空团刷出来的延迟被认了，时间锁被绕开"
    assert payload["hidden_count"] == 1


def test_连开空团不能提前解锁互见面板(gm_factory, user_factory, game_factory, submit, api_client):
    host = gm_factory()
    attacker = gm_factory()
    other = user_factory()
    game = game_factory(host, [attacker, other], mutual_review=True)
    submit(other, game, attacker, verdict="dislike", text="互见倒赞正文")

    for index in range(3):
        _mint_empty_finished_game(attacker, title=f"刷互见{index}")

    api_client.force_authenticate(attacker)
    payload = api_client.get(mutual_url(game)).json()
    assert payload["available"] is False, "空团刷出来的延迟让互见面板提前开了"
    assert payload["groups"] == []


def test_真实有人的团仍然正常计入延迟(gm_factory, user_factory, game_factory, submit, api_client):
    """修复不能把正常路径一起挡掉：3 个有别人在场的团照样解锁。"""
    host = gm_factory()
    target = user_factory()
    other = user_factory()
    game = game_factory(host, [target, other])
    submit(other, game, target, text="正常路径")

    for index in range(3):
        game_factory(host, [target], finished_at=game.finished_at + timedelta(hours=index + 1))

    api_client.force_authenticate(target)
    payload = api_client.get(RECEIVED_URL).json()
    assert [item["text"] for item in payload["results"]] == ["正常路径"]
    assert payload["hidden_count"] == 0


def test_被评者作为GM主持的真实团也计入延迟(gm_factory, user_factory, game_factory, submit, api_client):
    """只要团里有到场 PL，作为 GM 结的团同样算数（architecture 17.2 原口径）。"""
    host = gm_factory()
    target = gm_factory()
    other = user_factory()
    guest = user_factory()
    game = game_factory(host, [target, other])
    submit(other, game, target, text="GM 侧延迟")

    for index in range(3):
        game_factory(target, [guest], finished_at=game.finished_at + timedelta(hours=index + 1))

    api_client.force_authenticate(target)
    assert [item["text"] for item in api_client.get(RECEIVED_URL).json()["results"]] == ["GM 侧延迟"]


# --------------------------------------------------------------------------
# 2. 窗口边界（Asia/Shanghai）
# --------------------------------------------------------------------------


def test_评价窗口边界_恰好截止时刻可评_过一微秒即冻结(
    gm_factory, user_factory, game_factory, submit, site_config
):
    gm = gm_factory()
    target = user_factory()
    window = timedelta(days=site_config.review_window_days)

    open_game = game_factory(gm, [target], finished_at=timezone.now() - window + timedelta(seconds=5))
    assert submit(gm, open_game, target).status_code == 201

    closed_game = game_factory(
        gm, [target], finished_at=timezone.now() - window - timedelta(seconds=5)
    )
    closed = submit(gm, closed_game, target)
    assert closed.status_code == 400  # W5：时间窗关闭 → 400
    assert closed.json()["error"]["code"] == "review_window_closed"

    # 精确到微秒的边界：恰好等于截止时刻仍算窗口内，晚一微秒即关闭。
    ends_at = services.window_ends_at(open_game)
    assert services.in_review_window(open_game, now=ends_at) is True
    assert services.in_review_window(open_game, now=ends_at + timedelta(microseconds=1)) is False


def test_窗口长度按绝对时间算_不受本地时区日界影响(gm_factory, user_factory, game_factory, site_config):
    """中国无夏令时，但仍确认窗口是 finished_at + N 天的绝对时长，不是按本地日界取整。"""
    from django.utils import timezone as tz

    gm = gm_factory()
    target = user_factory()
    finished = tz.localtime(tz.now()).replace(hour=23, minute=59, second=0, microsecond=0)
    game = game_factory(gm, [target], finished_at=finished)
    ends_at = services.window_ends_at(game)
    assert ends_at - finished == timedelta(days=site_config.review_window_days)
    assert tz.localtime(ends_at).hour == 23 and tz.localtime(ends_at).minute == 59


# --------------------------------------------------------------------------
# 3. 互见开关的回溯翻转
# --------------------------------------------------------------------------


def test_结团后GM无法再翻开互见开关(gm_factory, user_factory, game_factory, api_client):
    """games 的 `update_game` 对已结团的团整体拒改，互见开关跟着被锁死。"""
    gm = gm_factory()
    target = user_factory()
    game = game_factory(gm, [target], mutual_review=False)
    api_client.force_authenticate(gm)
    response = api_client.patch(f"/api/v1/games/{game.pk}/", {"mutual_review": True}, format="json")
    assert response.status_code >= 400
    game.refresh_from_db()
    assert game.mutual_review is False


def test_跑完还没结团时不应再翻开互见开关(gm_factory, user_factory, game_factory):
    """W5 已修（原 xfail）：互见开关在出现第一条报名后就冻结。

    不再只看「已结团/已取消」，因为成员是在**报名那一刻**按当时的开关值同意的。
    """
    gm = gm_factory()
    target = user_factory()
    game = game_factory(gm, [target], mutual_review=False, status=GAME_RUNNING)
    with pytest.raises(game_services.MutualReviewFrozen):
        game_services.update_game(game, mutual_review=True)
    game.refresh_from_db()
    assert game.mutual_review is False


def test_没人报名时互见开关还能改(gm_factory, game_factory):
    """冻结的触发点是「第一条报名」，不是「建团那一刻」。"""
    gm = gm_factory()
    game = game_factory(gm, [], mutual_review=False, status=GAME_RUNNING)
    game_services.update_game(game, mutual_review=True)
    game.refresh_from_db()
    assert game.mutual_review is True


# --------------------------------------------------------------------------
# 4. 统计侧信道：个人空间的赞/倒赞是实时的
# --------------------------------------------------------------------------


def test_延迟期内本人卡片不应泄露赞倒赞(gm_factory, user_factory, game_factory, submit, api_client):
    """W5 已修（原 xfail）：两道闸一起上。

    1. `reviews.services.review_counts` 只统计「已对被评者可见」的评价 —— 延迟期内
       卡片上的 likes/dislikes/reviews_received 根本不动；
    2. `profiles` 的 `_MaskedCountsMixin` 在被评次数未达公布阈值时把三个计数压成 null，
       本人卡与公开卡同一口径。
    """
    gm = gm_factory()
    target = user_factory()
    other = user_factory()
    game = game_factory(gm, [target, other])

    api_client.force_authenticate(target)
    before = api_client.get("/api/v1/profiles/me/player-card/").json()
    assert before["dislikes"] is None and before["reviews_received"] is None

    submit(other, game, target, verdict="dislike", text="倒赞正文")

    api_client.force_authenticate(target)
    after = api_client.get("/api/v1/profiles/me/player-card/").json()
    received = api_client.get(RECEIVED_URL).json()
    assert received["results"] == [] and received["hidden_count"] == 1  # 评价本身还看不见
    assert after["dislikes"] == before["dislikes"], "卡片把倒赞实时交出去了"
    assert after["reviews_received"] == before["reviews_received"]
    # 底层缓存字段本身也没动（统计只计已过延迟的评价）
    target.player_card.refresh_from_db()
    assert (target.player_card.dislikes, target.player_card.reviews_received) == (0, 0)


def test_公开个人空间不应实时暴露被评次数(gm_factory, user_factory, game_factory, submit, api_client):
    """W5 已修（原 xfail）：`reviews_received` 也进了公布阈值闸，未达阈值一律 null。"""
    gm = gm_factory()
    target = user_factory()
    other = user_factory()
    game = game_factory(gm, [target, other])
    url = f"/api/v1/profiles/users/{target.pk}/"

    before = api_client.get(url).json()["player_card"]["reviews_received"]
    submit(other, game, target, verdict="like", text="赞正文")
    after = api_client.get(url).json()["player_card"]["reviews_received"]
    assert before is None
    assert after == before, "第三方可以靠轮询公开卡片测出评价提交时刻"


def test_hidden_count只给一个数字_不给团不给时间(
    gm_factory, user_factory, game_factory, submit, api_client
):
    """17.3 第 4 条承认计数实时，但它不许再附带团、时间戳或分组明细。"""
    gm = gm_factory()
    target = user_factory()
    other = user_factory()
    game = game_factory(gm, [target, other])
    submit(other, game, target, text="暂不可见")

    api_client.force_authenticate(target)
    payload = api_client.get(RECEIVED_URL).json()
    assert set(payload) == {"results", "hidden_count", "visible_after_games"}
    assert payload["hidden_count"] == 1
    assert payload["results"] == []


def test_取消的团不计入延迟(gm_factory, user_factory, game_factory, submit, api_client):
    """取消团不计任何次数，也不该被拿来刷延迟。"""
    host = gm_factory()
    target = gm_factory()
    other = user_factory()
    game = game_factory(host, [target, other])
    submit(other, game, target, text="取消团刷不动")

    for index in range(3):
        cancelled = game_services.create_game(target, title=f"取消{index}", start_at=timezone.now())
        game_services.cancel_game(cancelled, reason="不跑了")
        assert cancelled.status != GAME_FINISHED

    api_client.force_authenticate(target)
    assert api_client.get(RECEIVED_URL).json()["results"] == []


def test_互见开启时同团成员确实能替被评者提前读到评价_固有(
    gm_factory, user_factory, game_factory, submit, pass_delay, api_client
):
    """**固有可推知**（architecture 17.3 第 3 条），留证不修。

    互见面板按「查看者」判定延迟。查看者 B 的延迟过了、被评者 A 的没过时，
    B 看得到 A 收到的评价，转告 A 就等于 A 的时间锁被绕开。
    这是「开团勾选互见 = 团内接受这件事」的直接后果，不是实现缺陷；
    如果将来要收紧，就在 `mutual_for` 里对每一组再判一次组主自己的延迟。
    """
    host = gm_factory()
    target = user_factory()
    relay = user_factory()
    game = game_factory(host, [target, relay], mutual_review=True)
    submit(host, game, target, verdict="dislike", text="A 还看不到的倒赞")

    # A 自己：延迟没过，既看不到收到的评价，也开不了互见面板。
    api_client.force_authenticate(target)
    assert api_client.get(RECEIVED_URL).json()["results"] == []
    assert api_client.get(mutual_url(game)).json()["available"] is False

    # B：延迟过了，互见面板里看得到 A 收到的那一条。
    pass_delay(relay, game.finished_at)
    api_client.force_authenticate(relay)
    groups = api_client.get(mutual_url(game)).json()["groups"]
    group = next(g for g in groups if g["user"]["id"] == target.pk)
    assert [item["text"] for item in group["reviews"]] == ["A 还看不到的倒赞"]
    # 但 B 看到的同样是匿名的：没有评价人、没有 id、没有时间戳。
    assert set(group["reviews"][0]) == {"verdict", "verdict_display", "text", "reviewee_role", "game"}


def test_互见面板的错误顺序不泄露额外信息(gm_factory, user_factory, game_factory, api_client):
    """非到场者先撞到 `mutual_review_disabled` 再撞 `not_attendee`：

    互见开关本来就在团详情里公开（`GameDetailSerializer.mutual_review`，游客可读），
    所以这个先后顺序不多给任何信息。钉住行为，防止将来把别的秘密塞进这条路径。
    """
    host = gm_factory()
    outsider = user_factory()
    closed = game_factory(host, [], mutual_review=False)
    opened = game_factory(host, [], mutual_review=True)

    api_client.force_authenticate(outsider)
    assert api_client.get(mutual_url(closed)).json()["error"]["code"] == "mutual_review_disabled"
    assert api_client.get(mutual_url(opened)).json()["error"]["code"] == "not_attendee"
