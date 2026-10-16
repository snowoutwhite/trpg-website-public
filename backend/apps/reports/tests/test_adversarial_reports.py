"""对抗性测试 · 战报（reports）：存在性探测、越权、附件、输入边界、CSRF、游客状态码表。

红队纪律（安全测试规则）：
每条用例都是「能先复现才算发现」，跑一下没报错不算通过。

分节：
1. 可见性与存在性探测（404 / 403 一致性、精选 × 仅同团、改可见性后的附件）
2. 越权（改删别人的战报、跨战报附件 id、伪造 is_featured / author、非到场者）
3. 附件（大小边界、文件名头注入、路径穿越、不直出 protected 路径）
4. 输入边界（正文 / 标题 / 控制字符 / 非法枚举）
5. CSRF 与游客全路由状态码表
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.games.models import SIGNUP_WITHDRAWN, Signup
from apps.reports.models import (
    BODY_MAX_LENGTH,
    VISIBILITY_PUBLIC,
    VISIBILITY_SAME_GAME,
    Report,
    ReportAttachment,
)

from .conftest import PDF_BYTES, upload

pytestmark = pytest.mark.django_db

LIST_URL = reverse("v1:reports:report-list")
FEATURED_URL = reverse("v1:reports:report-featured")
PASSWORD = "testpass1234"


def detail_url(report) -> str:
    return reverse("v1:reports:report-detail", args=[report.pk])


def attachments_url(report) -> str:
    return reverse("v1:reports:attachment-list", args=[report.pk])


def attachment_detail_url(report, attachment_id: int) -> str:
    return reverse("v1:reports:attachment-detail", args=[report.pk, attachment_id])


def download_url(report, attachment_id: int) -> str:
    return reverse("v1:reports:attachment-download", args=[report.pk, attachment_id])


def abuse_url(report) -> str:
    return reverse("v1:reports:report-abuse", args=[report.pk])


@pytest.fixture
def world(game_factory, attendee_factory, report_factory, user_factory):
    """一个已结团的团：作者（到场 PL）、同团队友、站外登录用户。

    三份战报：精选公开 / 普通公开 / 仅同团。
    """
    game = game_factory()
    author = attendee_factory(game)
    teammate = attendee_factory(game)
    outsider = user_factory()

    featured = report_factory(game, author, title="精选", is_featured=True)
    public = report_factory(game, teammate, title="公开")
    same_game = report_factory(game, game.gm, title="仅同团", visibility=VISIBILITY_SAME_GAME)
    return {
        "game": game,
        "author": author,
        "teammate": teammate,
        "outsider": outsider,
        "gm": game.gm,
        "featured": featured,
        "public": public,
        "same_game": same_game,
    }


def _attach(report, author, api_client, name: str = "附件.pdf", data: bytes = PDF_BYTES):
    """借接口给战报挂一个附件，返回附件 id。"""
    api_client.force_authenticate(author)
    response = api_client.post(attachments_url(report), {"file": upload(name, data)}, format="multipart")
    assert response.status_code == 201, response.content
    api_client.force_authenticate(None)
    return response.json()["id"]


# ---------------------------------------------------------------------------
# 1. 可见性与存在性探测
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("param", ["game", "author"])
def test_列表过滤器收到超长数字不得打成500(api_client, world, param):
    """`?game=9999…`（4300 位以上）会让 int() 抛 ValueError，直接打穿成 500。"""
    response = api_client.get(LIST_URL, {param: "9" * 5000})

    assert response.status_code in (200, 400), response.status_code
    if response.status_code == 200:
        assert response.json()["results"] == []


def test_看不见的战报与不存在的战报返回一模一样的404(api_client, world):
    """两者响应体只要有差别，就能拿来探测「某 id 的私密战报是否存在」。"""
    hidden = api_client.get(detail_url(world["same_game"]))
    missing = api_client.get(reverse("v1:reports:report-detail", args=[10**6]))

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_按团筛选不泄露私密战报的存在(api_client, world, game_factory):
    """`?game=` 指向一个只有 same_game 战报的团时，游客拿到的结果必须与不存在的团一致。"""
    empty_game = game_factory()

    has_hidden = api_client.get(LIST_URL, {"game": world["game"].pk})
    no_such = api_client.get(LIST_URL, {"game": empty_game.pk})

    assert has_hidden.status_code == no_such.status_code == 200
    assert {row["id"] for row in has_hidden.json()["results"]} == {world["featured"].pk}
    assert no_such.json()["results"] == []


def test_精选但仅同团的战报游客拿不到详情附件与下载(api_client, world):
    """`is_featured=True` 不能盖过 `visibility=same_game`。"""
    hidden = world["same_game"]
    hidden.is_featured = True
    hidden.save(update_fields=["is_featured"])
    attachment_id = _attach(hidden, world["gm"], api_client)

    assert api_client.get(detail_url(hidden)).status_code == 404
    assert api_client.get(attachments_url(hidden)).status_code == 404
    assert api_client.get(download_url(hidden, attachment_id)).status_code == 404
    assert {row["id"] for row in api_client.get(FEATURED_URL).json()["results"]} == {
        world["featured"].pk
    }


def test_作者改成仅同团后站外用户立刻失去附件下载(api_client, world):
    """可见性是每次请求实时判断的，不能被上一次成功下载「缓存」下来。"""
    report = world["public"]
    attachment_id = _attach(report, world["teammate"], api_client)

    api_client.force_authenticate(world["outsider"])
    assert api_client.get(download_url(report, attachment_id)).status_code == 200

    api_client.force_authenticate(world["teammate"])
    patch = api_client.patch(detail_url(report), {"visibility": VISIBILITY_SAME_GAME}, format="json")
    assert patch.status_code == 200

    api_client.force_authenticate(world["outsider"])
    assert api_client.get(download_url(report, attachment_id)).status_code == 404
    assert api_client.get(attachments_url(report)).status_code == 404


def test_排序与搜索参数不能拿来翻别人的字段(api_client, world):
    """列表接口不支持 ordering / search；传了也只能被忽略，不能变成任意字段排序或 500。"""
    for params in (
        {"ordering": "author__email"},
        {"ordering": "-author__password"},
        {"search": "@example.com"},
        {"o": "author__email"},
    ):
        response = api_client.get(LIST_URL, params)
        assert response.status_code == 200, (params, response.status_code)
        assert {row["id"] for row in response.json()["results"]} == {world["featured"].pk}


def test_任何战报响应体都不出现邮箱(api_client, world):
    """列表 / 精选 / 详情 / 附件列表，四处都不许漏作者邮箱。"""
    attachment_id = _attach(world["featured"], world["author"], api_client)
    api_client.force_authenticate(world["author"])

    for url in (
        LIST_URL,
        FEATURED_URL,
        detail_url(world["featured"]),
        attachments_url(world["featured"]),
    ):
        body = api_client.get(url).content.decode()
        assert "@example.com" not in body, url
        assert world["author"].email not in body, url
    assert str(attachment_id) in api_client.get(attachments_url(world["featured"])).content.decode()


def test_附件序列化不泄露存储路径(api_client, world):
    """只许回鉴权视图路径；一旦回 media/protected 路径就等于绕开了鉴权。"""
    attachment_id = _attach(world["featured"], world["author"], api_client)

    body = api_client.get(detail_url(world["featured"])).content.decode()

    assert "protected" not in body
    assert "/media/" not in body
    assert download_url(world["featured"], attachment_id) in body


# ---------------------------------------------------------------------------
# 2. 越权
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_不能改删别人的战报(api_client, world, method):
    report = world["public"]
    api_client.force_authenticate(world["outsider"])

    payload = {"title": "被改了"} if method != "delete" else None
    response = (
        api_client.delete(detail_url(report))
        if method == "delete"
        else getattr(api_client, method)(detail_url(report), payload, format="json")
    )

    assert response.status_code == 403
    report.refresh_from_db()
    assert report.title == "公开"


def test_不能给别人的战报传附件或删附件(api_client, world):
    report = world["public"]
    attachment_id = _attach(report, world["teammate"], api_client)

    api_client.force_authenticate(world["outsider"])
    assert (
        api_client.post(attachments_url(report), {"file": upload()}, format="multipart").status_code
        == 403
    )
    assert api_client.delete(attachment_detail_url(report, attachment_id)).status_code == 403
    assert ReportAttachment.objects.filter(pk=attachment_id).exists()


def test_附件id属于别的战报时删不掉也下不到(api_client, world):
    """拿自己战报的 pk 配上别人附件的 id，不能把别人的附件删掉或下下来。"""
    mine = world["featured"]
    theirs = world["public"]
    victim_id = _attach(theirs, world["teammate"], api_client)

    api_client.force_authenticate(world["author"])
    assert api_client.delete(attachment_detail_url(mine, victim_id)).status_code == 404
    assert api_client.get(download_url(mine, victim_id)).status_code == 404
    assert ReportAttachment.objects.filter(pk=victim_id).exists()


def test_给看不见的战报传附件是404不是403(api_client, world):
    """403 会确认「这份战报存在」，必须跟不存在的 id 一样 404。"""
    api_client.force_authenticate(world["outsider"])

    response = api_client.post(
        attachments_url(world["same_game"]), {"file": upload()}, format="multipart"
    )

    assert response.status_code == 404


def test_提交时伪造is_featured与author一律被忽略(api_client, game_factory, attendee_factory, user_factory):
    game = game_factory()
    author = attendee_factory(game)
    victim = user_factory()
    api_client.force_authenticate(author)

    response = api_client.post(
        LIST_URL,
        {
            "game": game.pk,
            "title": "自封精选",
            "body_markdown": "正文",
            "is_featured": True,
            "author": victim.pk,
        },
        format="json",
    )

    assert response.status_code == 201
    report = Report.objects.get(pk=response.json()["id"])
    assert report.is_featured is False
    assert report.author_id == author.pk


def test_不能替别人在没进的团里写战报(api_client, game_factory, attendee_factory, user_factory):
    """不在团里的人 POST 只能吃 403 not_in_game，不能靠传 author 绕过。"""
    game = game_factory()
    attendee_factory(game)
    stranger = user_factory()
    api_client.force_authenticate(stranger)

    response = api_client.post(LIST_URL, {"game": game.pk, "title": "蹭团"}, format="json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_in_game"
    assert not Report.objects.filter(author=stranger).exists()


def test_退团的人即使被标到场也不能写战报不能看同团战报(
    api_client, game_factory, attendee_factory, report_factory
):
    """`attended` 是结团时的快照，报名状态才是「他到底算不算本团的人」。

    只看 `attended=True` 而不看报名状态，等于给「结团后被移出 / 退团」的人留了后门：
    既能补写战报拿积分，也能读本团的 same_game 战报。
    """
    game = game_factory()
    quitter = attendee_factory(game)
    Signup.objects.filter(game=game, player=quitter).update(
        status=SIGNUP_WITHDRAWN, attended=True
    )
    insider_only = report_factory(game, game.gm, visibility=VISIBILITY_SAME_GAME)

    api_client.force_authenticate(quitter)
    submit = api_client.post(LIST_URL, {"game": game.pk, "title": "退了还写"}, format="json")
    read = api_client.get(detail_url(insider_only))
    listing = api_client.get(LIST_URL)

    assert submit.status_code == 403, submit.content
    assert read.status_code == 404
    assert insider_only.pk not in {row["id"] for row in listing.json()["results"]}


def test_举报看不见的战报是404(api_client, world):
    api_client.force_authenticate(world["outsider"])

    response = api_client.post(abuse_url(world["same_game"]), {"reason": "探测"}, format="json")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3. 附件
# ---------------------------------------------------------------------------


def test_附件大小刚好到上限放行超一字节拒绝(api_client, world, monkeypatch):
    from apps.reports import services

    monkeypatch.setattr(services, "ATTACHMENT_MAX_BYTES", 2048)
    api_client.force_authenticate(world["author"])
    pad = b"\n%" + b"a" * (2048 - len(PDF_BYTES) - 2)

    ok = api_client.post(
        attachments_url(world["featured"]),
        {"file": upload("刚好.pdf", PDF_BYTES + pad)},
        format="multipart",
    )
    too_big = api_client.post(
        attachments_url(world["featured"]),
        {"file": upload("多一字节.pdf", PDF_BYTES + pad + b"a")},
        format="multipart",
    )

    assert ok.status_code == 201, ok.content
    assert too_big.status_code == 400
    assert too_big.json()["error"]["code"] == "card_file_too_large"


def test_二十兆上限没有被悄悄放宽():
    from apps.reports import services

    assert services.ATTACHMENT_MAX_BYTES == 20 * 1024 * 1024


def test_带引号换行的文件名传不进来(api_client, world):
    """multipart 的 filename 一遇引号/CRLF 就被截断，剩下的名字没有合法扩展名，直接被白名单拒。"""
    api_client.force_authenticate(world["author"])

    for evil in ('a";\r\nX-Injected: yes\r\n\r\n.pdf', 'a"b;X-Injected: yes.pdf'):
        response = api_client.post(
            attachments_url(world["featured"]),
            {"file": upload(evil, PDF_BYTES)},
            format="multipart",
        )
        assert response.status_code == 400, evil
    assert world["featured"].attachments.count() == 0


def test_下发名就算带控制字符也不能注入响应头(api_client, world):
    """最坏情况：假设某条路径真把脏名字写进了 `original_name`，
    下发这一环仍然必须自己扛住（`common.files` 的第 3 条边界）。"""
    attachment_id = _attach(world["featured"], world["author"], api_client)
    ReportAttachment.objects.filter(pk=attachment_id).update(
        original_name='a";\r\nX-Injected: yes\r\n\r\n.pdf'
    )

    response = api_client.get(download_url(world["featured"], attachment_id))

    assert response.status_code == 200
    assert "X-Injected" not in response
    disposition = response["Content-Disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert response["X-Content-Type-Options"] == "nosniff"
    assert disposition.startswith('attachment; filename="')
    # ASCII 回退名里既没有能提前闭合引号的 `"`，也没有能另起参数的 `;`。
    ascii_name = disposition.split('"')[1]
    assert re.fullmatch(r"[A-Za-z0-9._\- ]+", ascii_name), ascii_name
    assert disposition.count('"') == 2


def test_路径穿越文件名不会逃出受保护目录(api_client, world):
    attachment_id = _attach(
        world["featured"], world["author"], api_client, name="../../../../etc/passwd.pdf"
    )

    attachment = ReportAttachment.objects.get(pk=attachment_id)

    assert attachment.file.name.startswith("protected/reports/")
    assert ".." not in attachment.file.name
    assert "etc" not in attachment.file.name
    assert "passwd" not in attachment.file.name


def test_伪装扩展名的附件一律被魔数挡下(api_client, world):
    api_client.force_authenticate(world["author"])

    for name, data in (
        ("木马.pdf", b"MZ\x90\x00 not a pdf"),
        ("脚本.txt", b"\xff\xfe\x00\x01\x02"),
        ("表格.xlsx", b"PK\x03\x04 plain zip only"),
        ("执行档.exe", PDF_BYTES),
        ("无扩展名", PDF_BYTES),
    ):
        response = api_client.post(
            attachments_url(world["featured"]),
            {"file": upload(name, data)},
            format="multipart",
        )
        assert response.status_code == 400, (name, response.status_code)

    assert world["featured"].attachments.count() == 0


# ---------------------------------------------------------------------------
# 4. 输入边界
# ---------------------------------------------------------------------------


def test_正文长度边界(api_client, game_factory, attendee_factory):
    game = game_factory()
    author = attendee_factory(game)
    api_client.force_authenticate(author)

    ok = api_client.post(
        LIST_URL, {"game": game.pk, "title": "边界", "body_markdown": "字" * BODY_MAX_LENGTH},
        format="json",
    )
    assert ok.status_code == 201

    over = api_client.patch(
        detail_url(Report.objects.get(pk=ok.json()["id"])),
        {"body_markdown": "字" * (BODY_MAX_LENGTH + 1)},
        format="json",
    )
    assert over.status_code == 400


def test_标题超长与空白标题被拒(api_client, game_factory, attendee_factory):
    game = game_factory()
    author = attendee_factory(game)
    api_client.force_authenticate(author)

    for title in ("标" * 81, "   ", "\t\n"):
        response = api_client.post(LIST_URL, {"game": game.pk, "title": title}, format="json")
        assert response.status_code == 400, title
    assert not Report.objects.exists()


def test_控制字符与非法可见范围被拒(api_client, game_factory, attendee_factory):
    """NUL 进得了 SQLite，但 Postgres 会直接抛 DataError 打成 500。"""
    game = game_factory()
    author = attendee_factory(game)
    api_client.force_authenticate(author)

    nul_title = api_client.post(
        LIST_URL, {"game": game.pk, "title": "标题\x00注入"}, format="json"
    )
    nul_body = api_client.post(
        LIST_URL, {"game": game.pk, "title": "正常", "body_markdown": "正文\x00"}, format="json"
    )
    bad_visibility = api_client.post(
        LIST_URL, {"game": game.pk, "title": "正常", "visibility": "everyone"}, format="json"
    )

    assert nul_title.status_code == 400
    assert nul_body.status_code == 400
    assert bad_visibility.status_code == 400
    assert not Report.objects.exists()


def test_列表摘要不超长且原样截断(api_client, world):
    """excerpt 是原文前 200 字的硬截断：可能把 HTML 实体或代码块切成半截，
    前端渲染前必须自己 sanitize（服务端不渲染 Markdown 是既定口径）。"""
    from apps.reports.serializers import EXCERPT_LENGTH

    report = world["featured"]
    report.body_markdown = "<script>alert(1)</script>" + "字" * 500
    report.save(update_fields=["body_markdown"])

    row = next(r for r in api_client.get(LIST_URL).json()["results"] if r["id"] == report.pk)

    assert len(row["excerpt"]) <= EXCERPT_LENGTH
    assert row["excerpt"] == report.body_markdown[:EXCERPT_LENGTH]


# ---------------------------------------------------------------------------
# 5. CSRF 与游客状态码表
# ---------------------------------------------------------------------------


def test_写接口缺少csrf_token时被拒(world):
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=world["author"].email, password=PASSWORD)
    report = world["featured"]

    calls = [
        client.post(LIST_URL, {"game": world["game"].pk, "title": "无 token"}, format="json"),
        client.patch(detail_url(report), {"title": "无 token"}, format="json"),
        client.delete(detail_url(report)),
        client.post(attachments_url(report), {"file": upload()}, format="multipart"),
        client.post(abuse_url(world["public"]), {"reason": "无 token"}, format="json"),
    ]

    assert [response.status_code for response in calls] == [403] * 5
    assert not Report.objects.filter(title="无 token").exists()
    assert Report.objects.filter(pk=report.pk).exists()


def test_游客全路由状态码表(api_client, world):
    """游客对每条路由的状态码留一张表，将来任何一格变动都必须是有意为之。"""
    attachment_id = _attach(world["featured"], world["author"], api_client)
    visible, hidden = world["featured"], world["same_game"]

    table = {
        ("GET", "list"): api_client.get(LIST_URL).status_code,
        ("POST", "list"): api_client.post(LIST_URL, {"game": world["game"].pk, "title": "x"}, format="json").status_code,
        ("GET", "featured"): api_client.get(FEATURED_URL).status_code,
        ("GET", "detail-visible"): api_client.get(detail_url(visible)).status_code,
        ("GET", "detail-hidden"): api_client.get(detail_url(hidden)).status_code,
        ("PATCH", "detail"): api_client.patch(detail_url(visible), {"title": "x"}, format="json").status_code,
        ("DELETE", "detail"): api_client.delete(detail_url(visible)).status_code,
        ("GET", "attachments"): api_client.get(attachments_url(visible)).status_code,
        ("POST", "attachments"): api_client.post(attachments_url(visible), {"file": upload()}, format="multipart").status_code,
        ("DELETE", "attachment"): api_client.delete(attachment_detail_url(visible, attachment_id)).status_code,
        ("GET", "download"): api_client.get(download_url(visible, attachment_id)).status_code,
        ("POST", "abuse"): api_client.post(abuse_url(visible), {"reason": "x"}, format="json").status_code,
    }

    # W5 状态码统一：未登录访问需登录接口一律 401（与 charactercards / gallery 对齐）。
    assert table == {
        ("GET", "list"): 200,
        ("POST", "list"): 401,
        ("GET", "featured"): 200,
        ("GET", "detail-visible"): 200,
        ("GET", "detail-hidden"): 404,
        ("PATCH", "detail"): 401,
        ("DELETE", "detail"): 401,
        ("GET", "attachments"): 200,
        ("POST", "attachments"): 401,
        ("DELETE", "attachment"): 401,
        ("GET", "download"): 200,
        ("POST", "abuse"): 401,
    }
    assert Report.objects.filter(pk=visible.pk).exists()
    assert ReportAttachment.objects.filter(pk=attachment_id).exists()
    assert visible.visibility == VISIBILITY_PUBLIC


def test_战报标题含RTL覆盖字符一律400(api_client, world):
    """业务规则与安全约束。"""
    report = world["public"]
    api_client.force_authenticate(world["teammate"])
    response = api_client.patch(detail_url(report), {"title": "坏\u202e报"}, format="json")
    assert response.status_code == 400, response.content
    report.refresh_from_db()
    assert report.title == "公开"
