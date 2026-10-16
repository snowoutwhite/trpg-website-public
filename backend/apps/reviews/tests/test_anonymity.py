"""匿名红线：被评者看到的任何东西都不能反推出评价人。

覆盖四道锁里的字段锁、顺序锁与后台泄露面，时间锁在 `test_visibility.py`。
"""

from __future__ import annotations

import json

import pytest
from django.contrib import admin
from django.db.models.query import QuerySet

from apps.reviews import services
from apps.reviews.admin import ReviewAdmin
from apps.reviews.models import Review
from apps.reviews.tests.conftest import GIVEN_URL, RECEIVED_URL

pytestmark = pytest.mark.django_db


def walk(node):
    """遍历 JSON 里的每个 (key, value)。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def test_被评者接口全文不含评价人身份(
    user_factory, gm_factory, game_factory, pass_delay, submit, api_client
):
    # 先造几个占位用户，让评价人的 id 与团 id 错开，下面的「id 不得出现」断言才精确。
    for _ in range(3):
        user_factory()
    gm = gm_factory(nickname="带团的人", email="reviewer-gm@example.com")
    reviewee = user_factory(nickname="被评的人", email="reviewee@example.com")
    game = game_factory(gm, [reviewee], title="匿名测试团")
    assert submit(gm, game, reviewee, text="打得不错").status_code == 201
    pass_delay(reviewee, game.finished_at)

    api_client.force_authenticate(reviewee)
    payload = api_client.get(RECEIVED_URL).json()
    raw = json.dumps(payload, ensure_ascii=False)

    assert len(payload["results"]) == 1
    assert payload["results"][0]["text"] == "打得不错"
    # 1) 昵称与邮箱不得出现在全文里
    assert gm.nickname not in raw
    assert gm.email not in raw
    # 2) 不得有任何带 reviewer 字样的键，也不得有任何等于评价人 id 的值
    for key, value in walk(payload):
        assert "reviewer" not in key.lower()
        assert value != gm.pk, f"评价人 id 出现在 {key} 里"
    # 3) 连 id / 创建时间都不给：它们能反推提交顺序
    assert set(payload["results"][0]) == {
        "verdict",
        "verdict_display",
        "text",
        "reviewee_role",
        "game",
    }


def _received_order(user) -> list[str]:
    visible, _ = services.received_by(user)
    return [review.text for review in visible]


def test_被评者看到的顺序与创建顺序无关(
    user_factory, gm_factory, game_factory, pass_delay, settings
):
    gm = gm_factory()
    reviewee = user_factory()
    reviewers = [user_factory() for _ in range(3)]
    game = game_factory(gm, [reviewee, *reviewers], title="顺序测试团")
    creation_order = []
    for index, reviewer in enumerate(reviewers, start=1):
        services.upsert_review(
            reviewer, game=game, reviewee=reviewee, verdict="like", text=f"第{index}条"
        )
        creation_order.append(f"第{index}条")
    pass_delay(reviewee, game.finished_at)

    # 稳定：同一把种子下每次请求顺序一致（不能每次刷新都抖）
    assert _received_order(reviewee) == _received_order(reviewee)

    # 与创建顺序无关：换几把种子，至少有一把排出来不是创建顺序
    orders = []
    for seed in ("seed-a", "seed-b", "seed-c", "seed-d"):
        settings.SECRET_KEY = seed
        orders.append(_received_order(reviewee))
    assert all(sorted(order) == sorted(creation_order) for order in orders)
    assert any(order != creation_order for order in orders)


def test_被评者的查询不按id或创建时间排序(
    user_factory, gm_factory, game_factory, pass_delay, submit, monkeypatch
):
    gm = gm_factory()
    reviewee = user_factory()
    game = game_factory(gm, [reviewee])
    submit(gm, game, reviewee)
    pass_delay(reviewee, game.finished_at)

    seen: list[tuple] = []
    original = QuerySet.order_by

    def spy(self, *fields):
        seen.append(fields)
        return original(self, *fields)

    monkeypatch.setattr(QuerySet, "order_by", spy)
    services.received_by(reviewee)

    forbidden = {"id", "pk", "created_at", "updated_at"}
    assert not [
        field for fields in seen for field in fields if str(field).lstrip("-") in forbidden
    ], f"被评者视角出现了泄露创建顺序的排序：{seen}"


def test_本人可回顾自己发出的评价(
    user_factory, gm_factory, game_factory, submit, api_client
):
    gm = gm_factory(nickname="带团的人")
    reviewee = user_factory(nickname="被评的人")
    game = game_factory(gm, [reviewee])
    submit(gm, game, reviewee, text="自查用")

    api_client.force_authenticate(gm)
    payload = api_client.get(GIVEN_URL).json()

    assert len(payload["results"]) == 1
    entry = payload["results"][0]
    assert entry["reviewee"]["nickname"] == "被评的人"  # 本人当然知道自己评了谁
    assert entry["text"] == "自查用"
    for key, _value in walk(payload):
        assert "reviewer" not in key.lower()


def test_他人看不到别人发出或收到的评价(
    user_factory, gm_factory, game_factory, submit, api_client
):
    gm = gm_factory()
    reviewee = user_factory()
    outsider = user_factory()
    game = game_factory(gm, [reviewee])
    submit(gm, game, reviewee)

    api_client.force_authenticate(outsider)
    assert api_client.get(GIVEN_URL).json()["results"] == []
    assert api_client.get(RECEIVED_URL).json()["results"] == []


class _FakeRequest:
    def __init__(self, superuser: bool):
        self.user = type("U", (), {"is_superuser": superuser})()


def test_后台对非超级用户隐藏评价人列(db):
    site_admin = ReviewAdmin(Review, admin.site)
    staff = _FakeRequest(superuser=False)
    owner = _FakeRequest(superuser=True)

    assert "reviewer_nickname" not in site_admin.get_list_display(staff)
    assert "reviewer" not in site_admin.get_fields(staff)
    assert "reviewer__nickname" not in site_admin.get_search_fields(staff)
    assert site_admin.lookup_allowed("reviewer__id__exact", "1", staff) is False


    assert "reviewer_nickname" in site_admin.get_list_display(owner)
    assert "reviewer" in site_admin.get_fields(owner)


def test_不为收到评价发通知(user_factory, gm_factory, game_factory, submit):
    """通知时间戳 = 提交时间戳，会泄露评价人的提交时序，所以收到评价不通知。"""
    from apps.notifications.models import Notification

    gm = gm_factory()
    reviewee = user_factory()
    game = game_factory(gm, [reviewee])
    submit(gm, game, reviewee)

    assert not Notification.objects.filter(recipient=reviewee).exists()
