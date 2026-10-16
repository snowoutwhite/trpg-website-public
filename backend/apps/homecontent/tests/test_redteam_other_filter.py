"""业务规则与安全约束。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


@pytest.fixture
def gm(user_factory):
    user = user_factory(nickname="其他筛选GM")
    user.is_gm = True
    user.save(update_fields=["is_gm"])
    return user


@pytest.fixture
def make_game(gm):
    from apps.games import services

    def make(title: str, rule_system: str = "", tags: list[str] | None = None):
        start = timezone.now() + timedelta(days=7)
        game = services.create_game(
            gm,
            title=title,
            rule_system=rule_system,
            start_at=start,
            card_deadline=start - timedelta(days=1),
            min_players=1,
            max_players=5,
        )
        if tags:
            from apps.games.models import Tag

            for name in tags:
                tag, _ = Tag.objects.get_or_create(name=name)
                game.tags.add(tag)
        return game

    return make


def _titles(response) -> set[str]:
    return {row["title"] for row in response.json()["results"]}


# --------------------------------------------------------------------------
# 5a. 空规则名
# --------------------------------------------------------------------------


def test_没填规则的团也算其他(api_client, make_game):
    """`exclude_preset_rule_systems` 的 docstring 承诺「规则名为空的行会被保留」。

    这条在卡池侧有用例，团侧没有。`exclude(field__iexact=...)` 在
    NULL/空串上的行为是 ORM 里最容易翻车的一处，必须逐个数据库口径验一遍。
    """
    make_game("没填规则的团")
    make_game("COC 的团", rule_system="COC")
    make_game("自定义规则的团", rule_system="PBTA")

    body = api_client.get("/api/v1/games/?rule_system=__other__")
    assert body.status_code == 200
    assert _titles(body) == {"没填规则的团", "自定义规则的团"}


def test_只有空白字符的规则名也算其他(api_client, make_game):
    make_game("只打了空格的团", rule_system="   ")
    make_game("COC 的团", rule_system="COC")
    assert _titles(api_client.get("/api/v1/games/?rule_system=__other__")) == {"只打了空格的团"}


# --------------------------------------------------------------------------
# 5b. 预设表里的脏数据不得吞掉全部结果
# --------------------------------------------------------------------------


def test_预设里混进空白名字不会吞掉所有团(api_client, make_game, db):
    """空串/纯空白如果被当成一个预设名去 `exclude(rule_system__iexact="")`，
    所有没填规则的团会被一起排掉 —— 公开列表凭空少一批内容。
    """
    from apps.homecontent.models import RuleSystemPreset

    make_game("没填规则的团")
    make_game("自定义规则的团", rule_system="PBTA")
    # 绕过 serializer（validate_name 会拒空），模拟数据迁移/shell 写进来的脏行
    RuleSystemPreset.objects.create(name="   ", sort=98)
    RuleSystemPreset.objects.create(name="\t", sort=99)

    body = api_client.get("/api/v1/games/?rule_system=__other__")
    assert body.status_code == 200
    assert _titles(body) == {"没填规则的团", "自定义规则的团"}


def test_预设条数放大后公开筛选不得5xx(api_client, make_game, db):
    """站主能写预设表 → 每多一条预设，公开查询就多一段 `NOT (... LIKE ...)`。

    站主是可信的，但「可信用户的一次误操作/脚本导入能把公开接口打成永久 500」
    仍然是缺陷。这里放到 200 条量级看会不会撞上 SQL 表达式深度/变量上限。
    """
    from apps.homecontent.models import RuleSystemPreset

    make_game("自定义规则的团", rule_system="PBTA")
    RuleSystemPreset.objects.bulk_create(
        [RuleSystemPreset(name=f"预设{i:03d}", sort=i) for i in range(200)]
    )
    # bulk_create 不发 post_save，手动同步镜像（等价于站主一条条存完的终态）
    from apps.homecontent.services import sync_rule_system_presets

    sync_rule_system_presets()

    for url in (
        "/api/v1/games/?rule_system=__other__",
        "/api/v1/charactercards/pool/?rule_system=__other__",
    ):
        response = api_client.get(url)
        assert response.status_code == 200, f"{url} → {response.status_code}"
    assert _titles(api_client.get("/api/v1/games/?rule_system=__other__")) == {"自定义规则的团"}


# --------------------------------------------------------------------------
# 5c. m2m 上的 exclude 与分页
# --------------------------------------------------------------------------


def test_标签其他不会把一个团数两遍(api_client, make_game):
    """`?tag=<预设名>` 走的是 m2m `filter`，同一个团挂两个标签就会出现两行。

    `?tag=__other__` 走 `exclude`，理论上不会重复 —— 但 `count` 与 `results`
    对不上是分页里最难查的一类 bug，明确钉一颗钉子。
    """
    make_game("挂了三个自建标签的团", tags=["自建A", "自建B", "自建C"])
    make_game("挂了预设标签的团", tags=["战役"])

    body = api_client.get("/api/v1/games/?tag=__other__").json()
    titles = [row["title"] for row in body["results"]]
    assert titles.count("挂了三个自建标签的团") == 1, f"同一个团出现了多次：{titles}"
    assert body["count"] == len(body["results"]), (
        f"count={body['count']} 与实际行数 {len(body['results'])} 对不上"
    )


def test_两个其他一起用(api_client, make_game):
    make_game("双其他", rule_system="PBTA", tags=["自建标签"])
    make_game("规则是预设", rule_system="COC", tags=["自建标签"])
    make_game("标签是预设", rule_system="PBTA", tags=["战役"])

    body = api_client.get("/api/v1/games/?rule_system=__other__&tag=__other__")
    assert body.status_code == 200
    assert _titles(body) == {"双其他"}


def test_标签哨兵也区分大小写(api_client, make_game):
    """`__OTHER__` 必须当成一个普通标签名（于是查不到东西），不得走哨兵分支。"""
    make_game("挂自建标签的团", tags=["自建标签"])
    for value in ("__OTHER__", "__Other__", "__other", "other"):
        body = api_client.get(f"/api/v1/games/?tag={value}")
        assert body.status_code == 200
        assert _titles(body) == set(), f"tag={value} 被当成了哨兵"


def test_标签名里的通配符不会变成模糊匹配(api_client, make_game):
    from apps.games.models import Tag

    make_game("百分号团", tags=["%"])
    make_game("下划线团", tags=["_"])
    make_game("正常团", tags=["自建标签"])
    Tag.objects.filter(name__in=["%", "_"]).update(is_preset=True)

    body = api_client.get("/api/v1/games/?tag=__other__")
    assert body.status_code == 200
    assert _titles(body) == {"正常团"}


@pytest.mark.parametrize(
    "value",
    ["%", "_", "%%", "'", '"', "\\", "x" * 500, "COC' OR '1'='1", "__other__%", "％"],
)
def test_标签参数花样不得5xx(api_client, make_game, value):
    from urllib.parse import quote

    make_game("正常团", tags=["自建标签"])
    response = api_client.get(f"/api/v1/games/?tag={quote(value, safe='')}")
    assert response.status_code < 500, f"tag={value!r} → {response.status_code}"


# --------------------------------------------------------------------------
# 5d. 预设名恰好等于哨兵
# --------------------------------------------------------------------------


def test_预设名不该和哨兵撞车(api_client, staff_user, make_game):
    """站主把一条预设命名成 `__other__` 会怎样？

    镜像里于是有了 `__other__`，前端筛选条会画出这个筹码；点它 → 走哨兵分支，
    返回的是「不命中任何预设的团」，而**不是**这条预设的团。
    站主做出了一个自己永远选不中的分类。
    合格的答案有两种：建的时候就拒（`__other__` 是保留字），
    或者按普通规则名处理。这里断言前者 —— 保留字应当被保留。
    """
    from apps.siteconfig.services import OTHER_SENTINEL

    make_game("自称其他的团", rule_system=OTHER_SENTINEL)
    make_game("自定义规则的团", rule_system="PBTA")

    api_client.force_authenticate(staff_user)
    response = api_client.post(
        "/api/v1/home/admin/rule-presets/", {"name": OTHER_SENTINEL}, format="json"
    )
    assert response.status_code == 400, (
        "站主建出了一条名为 __other__ 的预设：前端会画出一个点了返回别人结果的筹码"
    )
