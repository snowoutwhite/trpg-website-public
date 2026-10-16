"""对抗性测试 · 积分账本（points）：刷分、并发双发、撤销、无路由、后台唯一写入口。"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.points import services
from apps.points.models import (
    REASON_MANUAL,
    REASON_REPORT_SUBMITTED,
    PointsLedger,
)

pytestmark = pytest.mark.django_db

LIST_URL = reverse("v1:reports:report-list")
PASSWORD = "testpass1234"


def _flatten(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _flatten(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern


# ---------------------------------------------------------------------------
# 1. 没有对外接口
# ---------------------------------------------------------------------------


def test_积分app一条对外路由都没有(api_client):
    """首发口径是「只建账本表 + 后台」。多出任何一条路由都意味着余额/流水可被前台触碰。"""
    from apps.points import urls as points_urls

    assert points_urls.urlpatterns == []
    # 只看对外 API 树；后台（站主专用，路径从环境变量读）不在此列。
    exposed = [
        route
        for route, _pattern in _flatten(get_resolver().url_patterns)
        if route.startswith("api/") and "points" in route
    ]
    assert exposed == [], exposed

    for path in ("/api/v1/points/", "/api/v1/points/balance/", "/api/v1/points/me/"):
        assert api_client.get(path).status_code == 404, path
        assert api_client.post(path, {}, format="json").status_code == 404, path


# ---------------------------------------------------------------------------
# 2. 刷分：删了重写、反复改、并发
# ---------------------------------------------------------------------------


@pytest.fixture
def submitter(db, user_factory):
    """一个已结团的团 + 一名到场 PL（reports 是 points 唯一的自动发分来源）。"""
    from datetime import timedelta

    from django.utils import timezone

    from apps.games.models import GAME_FINISHED, SIGNUP_ACCEPTED, Game, Signup

    gm = user_factory(nickname="主持人")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    start_at = timezone.now() - timedelta(days=3)
    game = Game.objects.create(
        gm=gm,
        title="深潜者之夏",
        rule_system="COC",
        start_at=start_at,
        card_deadline=start_at,
        status=GAME_FINISHED,
        finished_at=timezone.now() - timedelta(days=1),
    )
    player = user_factory()
    Signup.objects.create(game=game, player=player, order=1, status=SIGNUP_ACCEPTED, attended=True)
    return game, player


def _submit(api_client, game, author, title="战报"):
    api_client.force_authenticate(author)
    return api_client.post(LIST_URL, {"game": game.pk, "title": title}, format="json")


def test_反复删建战报三轮也只发一次分(api_client, submitter):
    """去重键是「某人 + 某团」而不是战报 id，删了重写不能二次发分。"""
    game, author = submitter

    for round_no in range(3):
        created = _submit(api_client, game, author, title=f"第 {round_no} 版")
        assert created.status_code == 201, created.content
        assert api_client.delete(
            reverse("v1:reports:report-detail", args=[created.json()["id"]])
        ).status_code == 204

    assert services.balance(author) == 10
    assert PointsLedger.objects.filter(user=author).count() == 1


def test_改战报不会再发一次分(api_client, submitter):
    game, author = submitter
    created = _submit(api_client, game, author)
    detail = reverse("v1:reports:report-detail", args=[created.json()["id"]])

    for i in range(5):
        assert api_client.patch(detail, {"title": f"改第 {i} 次"}, format="json").status_code == 200
        assert _submit(api_client, game, author, title=f"再提交 {i}").status_code == 200

    assert services.balance(author) == 10
    assert PointsLedger.objects.filter(user=author).count() == 1


def test_撤销过的分不会因为重写战报复活(api_client, submitter, user_factory):
    game, author = submitter
    created = _submit(api_client, game, author)
    services.revoke(PointsLedger.objects.get(user=author, dedupe_key__isnull=False), by=user_factory())
    assert services.balance(author) == 0

    api_client.delete(reverse("v1:reports:report-detail", args=[created.json()["id"]]))
    again = _submit(api_client, game, author, title="重写")

    assert again.status_code == 201
    assert services.balance(author) == 0


def test_并发提交同一份战报不会双发积分也不会500(api_client, submitter, monkeypatch):
    """模拟两个请求同时 POST：另一个请求在本请求「查重」与「落库」之间先建好了战报并发了分。"""
    game, author = submitter
    from apps.reports import services as report_services
    from apps.reports.models import Report

    original = report_services.assert_can_submit

    def racing(user, target_game):
        original(user, target_game)
        if not Report.objects.filter(game=target_game, author=user).exists():
            other = Report.objects.create(game=target_game, author=user, title="并发抢先")
            services.grant(
                user,
                report_services.POINTS_PER_REPORT,
                REASON_REPORT_SUBMITTED,
                ref=other,
                dedupe_key=report_services.points_dedupe_key(user.pk, target_game.pk),
            )

    monkeypatch.setattr(report_services, "assert_can_submit", racing)
    response = _submit(api_client, game, author)

    assert response.status_code == 200, response.content  # 撞上了已存在的那份，更新而不是新建
    assert Report.objects.filter(game=game, author=author).count() == 1
    assert PointsLedger.objects.filter(user=author).count() == 1
    assert services.balance(author) == 10


def test_并发抢同一个去重键不会双发也不会500(user_factory, monkeypatch):
    """`grant` 的查重与插入之间有窗口；靠唯一约束兜底时必须认下对方的行，而不是抛 500。"""
    user = user_factory()
    key = "report:game:7:user:7"

    original = services._attach_ref

    def racing(entry, ref):
        if not PointsLedger.objects.filter(dedupe_key=key).exists():
            PointsLedger.objects.create(
                user=user, amount=10, reason=REASON_REPORT_SUBMITTED, dedupe_key=key
            )
        return original(entry, ref)

    monkeypatch.setattr(services, "_attach_ref", racing)
    entry = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)

    assert PointsLedger.objects.filter(dedupe_key=key).count() == 1
    assert entry.pk == PointsLedger.objects.get(dedupe_key=key).pk
    assert services.balance(user) == 10


def test_去重键被别人占用时直接抛错而不是默默返回别人那一行(user_factory):
    """去重键是全局唯一的：撞了别人的键**必须抛错**（W5 收紧）。

    原来是「同键就返回那一行」，于是调用方把键拼错（团 id 与用户 id 写反、
    少拼一段…）时，B 的发分请求会静默地拿回 A 的流水：B 永远拿不到分，
    账面上也看不出异常。现在宁可 400 出错，也不让这种错配无声地过去。
    """
    first, second = user_factory(), user_factory()
    key = "report:game:1:user:1"
    services.grant(first, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)

    with pytest.raises(services.DedupeKeyOwnerMismatch):
        services.grant(second, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)

    assert services.balance(second) == 0
    assert services.balance(first) == 10
    assert PointsLedger.objects.filter(dedupe_key=key).count() == 1


def test_同一个人同键重复发分仍然幂等(user_factory):
    """收紧的只是「换了个人」，本人重复调用照样只发一次。"""
    user = user_factory()
    key = "report:game:9:user:9"
    first = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)
    again = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)

    assert again.pk == first.pk
    assert services.balance(user) == 10


# ---------------------------------------------------------------------------
# 3. 撤销
# ---------------------------------------------------------------------------


def test_撤销后余额可为负而且不能二次撤销(user_factory):
    user, staff = user_factory(), user_factory()
    entry = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key="k1")
    reversal = services.revoke(entry, by=staff)
    penalty = services.grant(user, -5, REASON_MANUAL, created_by=staff, note="扣分")

    assert services.balance(user) == -5
    with pytest.raises(services.AlreadyRevoked):
        services.revoke(entry, by=staff)
    with pytest.raises(services.NotRevocable):
        services.revoke(reversal, by=staff)

    services.revoke(penalty, by=staff)
    assert services.balance(user) == 0
    assert PointsLedger.objects.filter(user=user).count() == 4  # 只增不改：四行都在


def test_删战报后流水与余额都不动ref只是悬空(api_client, submitter):
    """业务规则与安全约束。"""
    game, author = submitter
    created = _submit(api_client, game, author)
    entry = PointsLedger.objects.get(user=author)
    assert entry.ref is not None

    api_client.delete(reverse("v1:reports:report-detail", args=[created.json()["id"]]))

    entry.refresh_from_db()
    assert entry.ref is None  # GenericFK 悬空，但流水行还在
    assert services.balance(author) == 10
    assert str(entry)  # 后台列表渲染不会被悬空的 ref 打崩


def test_零分不落库(user_factory):
    user = user_factory()
    with pytest.raises(services.InvalidPointsAmount):
        services.grant(user, 0, REASON_MANUAL)
    assert not PointsLedger.objects.filter(user=user).exists()


# ---------------------------------------------------------------------------
# 4. 后台（积分唯一的手工写入口，站主专用）
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client_for_points(client, user_factory):
    from django.conf import settings

    staff = user_factory(nickname="站主")
    staff.is_staff = True
    staff.is_superuser = True
    staff.save(update_fields=["is_staff", "is_superuser"])
    assert client.login(email=staff.email, password=PASSWORD)
    return client, staff, settings.ADMIN_URL


def test_后台手工发分不能打成500(admin_client_for_points, user_factory):
    """后台是积分唯一的手工入口；新增一条流水后必须能正常落库并跳回列表。"""
    client, _staff, admin_url = admin_client_for_points
    target = user_factory()

    response = client.post(
        f"/{admin_url}points/pointsledger/add/",
        {"user": target.pk, "amount": 7, "reason": REASON_MANUAL, "note": "补偿", "dedupe_key": ""},
        follow=False,
    )

    assert response.status_code == 302, response.status_code
    assert services.balance(target) == 7


def test_后台保存并继续编辑不会跳到不存在的对象(admin_client_for_points, user_factory):
    """`save_model` 里只调了 `services.grant()`，表单那个实例从头到尾没落库。

    于是 admin 手上的 `obj.pk` 仍是 None：「保存并继续编辑」会跳到 `.../None/change/`，
    操作日志（LogEntry）也记不到对象 id。
    """
    client, _staff, admin_url = admin_client_for_points
    target = user_factory()

    response = client.post(
        f"/{admin_url}points/pointsledger/add/",
        {
            "user": target.pk,
            "amount": 3,
            "reason": REASON_MANUAL,
            "note": "继续编辑",
            "dedupe_key": "",
            "_continue": "",
        },
    )

    assert response.status_code == 302
    assert "/None/" not in response["Location"], response["Location"]
    assert client.get(response["Location"]).status_code == 200


def test_后台发零分应当是字段错误而不是500(admin_client_for_points, user_factory):
    """`services.grant(0)` 抛的是业务异常，后台没人接就是 500。"""
    client, _staff, admin_url = admin_client_for_points
    target = user_factory()

    response = client.post(
        f"/{admin_url}points/pointsledger/add/",
        {"user": target.pk, "amount": 0, "reason": REASON_MANUAL, "note": "零分", "dedupe_key": ""},
    )

    assert response.status_code == 200  # 表单带着错误重新渲染，不是错误页
    assert "积分变动不能为 0" in response.content.decode()
    assert not PointsLedger.objects.filter(user=target).exists()
