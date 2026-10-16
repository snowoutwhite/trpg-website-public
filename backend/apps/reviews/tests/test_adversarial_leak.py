"""红队（W3 对抗测试）：直接泄露与排序侧信道。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.test import override_settings

from apps.reviews import services
from apps.reviews.models import Review
from apps.reviews.tests.conftest import (
    GIVEN_URL,
    PENDING_URL,
    QUOTA_URL,
    RECEIVED_URL,
    mutual_url,
)

pytestmark = pytest.mark.django_db

#: 被评者视角的条目只允许出现这些键，多一个都要先过匿名审查。
ALLOWED_REVIEW_KEYS = {"verdict", "verdict_display", "text", "reviewee_role", "game"}
#: 能反推提交顺序或直接指向评价人的键，出现在被评者视角即判失败。
FORBIDDEN_KEYS = {
    "id",
    "pk",
    "created_at",
    "updated_at",
    "reviewer",
    "reviewer_id",
    "email",
    "author",
    "user_id",
}


def _keys(node) -> set[str]:
    """递归收集 JSON 里出现过的全部键名。"""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


def _text(response) -> str:
    """响应体全文 + 全部响应头拼起来，供整串搜索。"""
    body = response.content.decode("utf-8", "replace")
    headers = " ".join(f"{k}:{v}" for k, v in response.items())
    return body + " " + headers


@pytest.fixture
def leak_scene(gm_factory, user_factory, game_factory, submit, pass_delay):
    """GM + 3 PL 的团，B 与 C 都评了 A；A 已跨过延迟门槛，互见开启。"""

    def build(*, mutual=True):
        gm = gm_factory(nickname="主持人QPZ", email="gm-qpz@example.com")
        target = user_factory(nickname="被评者WYX", email="target-wyx@example.com")
        reviewer_b = user_factory(nickname="评价人甲XZQ", email="reviewer-xzq@example.com")
        reviewer_c = user_factory(nickname="评价人乙KJH", email="reviewer-kjh@example.com")
        game = game_factory(gm, [target, reviewer_b, reviewer_c], mutual_review=mutual)
        submit(reviewer_b, game, target, verdict="like", text="甲写的正文")
        submit(reviewer_c, game, target, verdict="dislike", text="乙写的正文")
        pass_delay(target, game.finished_at)
        return SimpleNamespace(
            gm=gm, target=target, b=reviewer_b, c=reviewer_c, game=game
        )

    return build


# --------------------------------------------------------------------------
# 1. 直接泄露
# --------------------------------------------------------------------------


def test_被评者视角全部接口的响应体与响应头不含评价人身份(leak_scene, api_client):
    scene = leak_scene()
    api_client.force_authenticate(scene.target)

    received = api_client.get(RECEIVED_URL)
    mutual = api_client.get(mutual_url(scene.game))
    pending = api_client.get(PENDING_URL)
    quota = api_client.get(QUOTA_URL)
    given = api_client.get(GIVEN_URL)

    # 收到的评价：连团员昵称都不该出现，更不许出现邮箱。
    blob = _text(received)
    for needle in ("评价人甲XZQ", "评价人乙KJH", "reviewer-xzq@example.com", "reviewer-kjh@example.com"):
        assert needle not in blob, f"mine/received/ 泄露了 {needle}"
    # 条目级别逐条查白名单；`game` 子对象带团 id 与团的时间是允许的（团不是秘密），
    # 但条目自身绝不许有 id / created_at 这类能反推提交顺序的字段。
    for item in received.json()["results"]:
        assert set(item) == ALLOWED_REVIEW_KEYS, item
        assert not (set(item) & FORBIDDEN_KEYS)
    assert "reviewer" not in _keys(received.json())

    # 互见：成员昵称本来就公开（面板按人分组），但邮箱与评价条目的身份字段一律不许有。
    blob = _text(mutual)
    for needle in ("reviewer-xzq@example.com", "reviewer-kjh@example.com", "gm-qpz@example.com"):
        assert needle not in blob
    for group in mutual.json()["groups"]:
        for item in group["reviews"]:
            assert set(item) == ALLOWED_REVIEW_KEYS, item

    # pending / quota / given：不含任何他人邮箱。
    for response in (pending, quota, given):
        blob = _text(response)
        for needle in ("reviewer-xzq@example.com", "reviewer-kjh@example.com", "gm-qpz@example.com"):
            assert needle not in blob


def test_被评者看到的条目没有id与时间戳(leak_scene, api_client):
    """自增 id 与 created_at 同样能把提交顺序交出去。"""
    scene = leak_scene()
    api_client.force_authenticate(scene.target)
    payload = api_client.get(RECEIVED_URL).json()
    assert payload["results"]
    keys = _keys(payload["results"])
    # game 子对象自己带 id（团不是秘密），所以按条目级别检查。
    for item in payload["results"]:
        assert "id" not in item and "created_at" not in item and "updated_at" not in item
    assert "reviewer" not in keys


def test_upsert不回显他人对同一被评者的评价(leak_scene, submit, api_client):
    """冲突/改写路径上最容易把别人那一行捞出来回显。"""
    scene = leak_scene(mutual=False)
    # C 改写自己的评价：响应必须是 C 自己那一行，不能串到 B 的行。
    response = submit(scene.c, scene.game, scene.target, verdict="like", text="乙改过的正文")
    assert response.status_code == 200
    assert response.json()["text"] == "乙改过的正文"
    b_row = Review.objects.get(game=scene.game, reviewer=scene.b, reviewee=scene.target)
    assert response.json()["id"] != b_row.pk
    assert "甲写的正文" not in _text(response)


def test_错误响应不透露评价人线索(gm_factory, user_factory, game_factory, submit, api_client):
    """403/400 的 detail 文案只许说规则，不许说「谁评过你」。"""
    gm = gm_factory(nickname="主持人ERR")
    target = user_factory(nickname="被评者ERR")
    outsider = user_factory(nickname="局外人ERR")
    game = game_factory(gm, [target])

    # 非到场者提交
    bad = submit(outsider, game, target)
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "not_attendee"
    # 目标不在团里
    bad2 = submit(gm, game, outsider)
    assert bad2.status_code == 403
    assert bad2.json()["error"]["code"] == "invalid_review_target"

    for response in (bad, bad2):
        blob = _text(response)
        for needle in ("被评者ERR", "局外人ERR", "主持人ERR", "@example.com"):
            assert needle not in blob


def test_被评者无法用查询参数按评价人过滤或排序(leak_scene, api_client):
    """DRF filter backend 没挂，但要确认没人后来顺手挂上。"""
    scene = leak_scene()
    api_client.force_authenticate(scene.target)
    base = api_client.get(RECEIVED_URL).json()
    for query in (
        f"?ordering=id&o=1&search=甲&reviewer={scene.b.pk}",
        "?ordering=-created_at",
        "?page=1&page_size=1",
        f"?reviewer__id__exact={scene.b.pk}",
        f"?reviewee={scene.b.pk}",
    ):
        assert api_client.get(RECEIVED_URL + query).json() == base, query

    mutual_base = api_client.get(mutual_url(scene.game)).json()
    for query in ("?ordering=id", f"?reviewer={scene.b.pk}", "?page_size=1"):
        assert api_client.get(mutual_url(scene.game) + query).json() == mutual_base, query


# --------------------------------------------------------------------------
# 2. 排序侧信道
# --------------------------------------------------------------------------


def test_收到列表顺序与创建顺序无关且换密钥即重排(
    gm_factory, user_factory, game_factory, submit, pass_delay, api_client
):
    """5 人团按已知顺序创建 5 条评价，检查输出顺序既不等于创建顺序、又随密钥变。"""
    gm = gm_factory()
    target = user_factory()
    others = [user_factory() for _ in range(4)]
    game = game_factory(gm, [target, *others])

    order = [gm, *others]
    for index, reviewer in enumerate(order, start=1):
        submit(reviewer, game, target, text=f"第{index}条")
    created = [f"第{i}条" for i in range(1, 6)]

    pass_delay(target, game.finished_at)
    api_client.force_authenticate(target)

    seen = [
        [item["text"] for item in api_client.get(RECEIVED_URL).json()["results"]] for _ in range(3)
    ]
    assert seen[0] == seen[1] == seen[2], "同一密钥下顺序必须稳定，否则刷新即抖动"
    assert sorted(seen[0]) == sorted(created)
    assert seen[0] != created, "输出顺序等于创建顺序 = 提交时序被交出去"
    assert seen[0] != list(reversed(created))

    rows = list(Review.objects.filter(reviewee=target).select_related("game"))
    permutations = set()
    for key in ("k-alpha", "k-beta", "k-gamma"):
        with override_settings(SECRET_KEY=key):
            permutations.add(tuple(r.pk for r in services.anonymize_order(rows)))
    assert len(permutations) >= 2, "换 SECRET_KEY 顺序不变 = 顺序其实由 pk 决定"


def test_匿名排序键与pk大小没有统计相关():
    """300 条合成数据：输出里「后一条 pk 更大」的比例应接近一半。"""
    game = SimpleNamespace(finished_at=None)
    rows = [SimpleNamespace(pk=pk, game=game) for pk in range(1, 301)]
    ordered = [row.pk for row in services.anonymize_order(rows)]
    assert ordered != sorted(ordered)
    ascending = sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if b > a)
    ratio = ascending / (len(ordered) - 1)
    assert 0.35 < ratio < 0.65, f"升序相邻对占比 {ratio:.2f}，顺序与 pk 相关"


def test_互见面板每组顺序同样不按创建顺序(
    gm_factory, user_factory, game_factory, submit, pass_delay, api_client
):
    gm = gm_factory()
    target = user_factory()
    others = [user_factory() for _ in range(4)]
    game = game_factory(gm, [target, *others], mutual_review=True)
    for index, reviewer in enumerate([gm, *others], start=1):
        submit(reviewer, game, target, text=f"互见第{index}条")
    created = [f"互见第{i}条" for i in range(1, 6)]

    viewer = others[0]
    pass_delay(viewer, game.finished_at)
    api_client.force_authenticate(viewer)
    groups = api_client.get(mutual_url(game)).json()["groups"]
    group = next(g for g in groups if g["user"]["id"] == target.pk)
    assert [item["text"] for item in group["reviews"]] != created
