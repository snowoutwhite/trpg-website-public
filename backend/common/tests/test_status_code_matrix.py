"""跨 app 的状态码矩阵（W5 统一）。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# 造一个横跨多个 app 的世界
# --------------------------------------------------------------------------


@pytest.fixture
def world(user_factory, site_config):
    """一个结过团的团 + 一位 GM + 一位到场 PL + 一位局外人 + 各 app 的对象。"""
    from apps.charactercards import services as card_services
    from apps.games import services as game_services
    from apps.reports import services as report_services
    from apps.resources.models import Resource, ResourceKind

    gm = user_factory(nickname="矩阵GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    player = user_factory(nickname="矩阵PL")
    outsider = user_factory(nickname="矩阵局外人")

    game = game_services.create_game(
        gm,
        title="状态码矩阵团",
        rule_system="COC",
        start_at=timezone.now() + timedelta(hours=1),
        min_players=1,
        max_players=5,
        requires_card=False,
    )
    signup = game_services.signup(game, player)
    game_services.start_game(game)
    game_services.finish_game(game, attended_signup_ids=[signup.pk])
    game.refresh_from_db()

    private_card = card_services.create_card(outsider, name="别人的私密卡", is_public=False)
    report, _ = report_services.submit_report(
        player, game, title="矩阵战报", body_markdown="正文", visibility="same_game"
    )
    unapproved = Resource.objects.create(
        title="还没过审的资源", kind=ResourceKind.LINK, url="https://example.com/x",
        is_approved=False, uploader=outsider,
    )

    # 另开一个还没结团的团，用来测「目标状态不对 → 400」
    running = game_services.create_game(
        gm,
        title="还在跑的团",
        start_at=timezone.now() + timedelta(days=3),
        min_players=3,
        max_players=5,
    )

    return {
        "gm": gm,
        "player": player,
        "outsider": outsider,
        "game": game,
        "running": running,
        "signup": signup,
        "private_card": private_card,
        "report": report,
        "unapproved": unapproved,
    }


def _png_upload(name: str = "matrix.png"):
    """一张最小的合法 PNG：走 multipart 才不会先撞字段校验。"""
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (3, 3, 3)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def code_of(response) -> str:
    return response.json()["error"]["code"]


def assert_envelope(response) -> None:
    """错误响应一律是统一信封：`{"error": {"code", "message"}}`。"""
    body = response.json()
    assert set(body) == {"error"}, body
    assert isinstance(body["error"]["code"], str) and body["error"]["code"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# --------------------------------------------------------------------------
# 401：未登录访问需登录接口
# --------------------------------------------------------------------------


def guest_cases(world) -> list[tuple[str, str, dict]]:
    game, report = world["game"], world["report"]
    return [
        ("get", "/api/v1/accounts/me/", {}),
        ("get", "/api/v1/profiles/me/player-card/", {}),
        ("get", "/api/v1/profiles/me/gm-card/", {}),
        ("get", "/api/v1/notifications/", {}),
        ("get", "/api/v1/charactercards/mine/", {}),
        ("post", "/api/v1/charactercards/mine/", {"name": "x"}),
        ("get", "/api/v1/games/my-signups/", {}),
        ("post", "/api/v1/games/", {"title": "x"}),
        ("get", f"/api/v1/games/{game.pk}/signups/", {}),
        ("get", f"/api/v1/games/{game.pk}/roster/", {}),
        ("post", f"/api/v1/games/{game.pk}/signup/", {}),
        ("get", "/api/v1/reviews/pending/", {}),
        ("get", "/api/v1/reviews/mine/received/", {}),
        ("post", "/api/v1/reviews/", {"game": game.pk}),
        ("post", "/api/v1/reports/", {"game": game.pk, "title": "x"}),
        ("post", "/api/v1/reports/import-document/", {"game": game.pk}),
        ("patch", f"/api/v1/reports/{report.pk}/", {"title": "x"}),
        ("get", f"/api/v1/gallery/games/{game.pk}/photos/", {}),
        ("get", "/api/v1/gallery/reports/mine/", {}),
        ("get", "/api/v1/gallery/moderation/queue/", {}),
        ("post", "/api/v1/resources/", {"title": "x", "kind": "link"}),

        ("get", "/api/v1/home/admin/", {}),
        ("patch", "/api/v1/home/admin/config/", {"site_name": "x"}),
        ("post", "/api/v1/home/admin/rule-presets/", {"name": "x"}),
        ("post", "/api/v1/home/admin/quick-entries/", {"key": "x", "label": "x", "route": "/"}),
        ("post", "/api/v1/home/admin/announcements/", {"title": "x", "body": "y"}),
        ("post", "/api/v1/home/admin/featured-photos/", {"photo": 1, "is_featured": True}),
        ("get", "/api/v1/home/admin/featured-photos/candidates/", {}),
    ]


def test_游客访问需登录接口一律401(api_client, world):
    """DRF 在会话认证下会把 `NotAuthenticated` 降级成 403（没有 WWW-Authenticate 头），
    `common.exceptions.api_exception_handler` 统一把它拨回 401。"""
    wrong = {}
    for method, url, payload in guest_cases(world):
        response = getattr(api_client, method)(url, payload, format="json")
        if response.status_code != 401:
            wrong[(method, url)] = response.status_code
        else:
            assert_envelope(response)
            assert code_of(response) == "not_authenticated", url
    assert not wrong, f"以下接口对游客不是 401：{wrong}"


def test_封禁号与注销号不是401而是403(api_client, world, user_factory):
    """「要登录」和「登录了但账号不能用」是两件事，状态码必须分得开。"""
    for extra in ({"is_banned": True}, {"is_active": False, "is_deactivated": True}):
        blocked = user_factory(**extra)
        api_client.force_authenticate(blocked)
        for url in (
            "/api/v1/charactercards/mine/",
            f"/api/v1/games/{world['game'].pk}/roster/",
            "/api/v1/gallery/reports/mine/",
        ):
            response = api_client.get(url)
            assert response.status_code == 403, f"{extra} → {url} = {response.status_code}"


# --------------------------------------------------------------------------
# 403 的账号处置分格（缺陷 D4）：禁言 / 封禁 要有各自的 code，不能都是 permission_denied
# --------------------------------------------------------------------------


def test_禁言被拒一律是403加account_muted(api_client, world, user_factory):
    """禁言只禁「放团 / 报名 / 评价」。

    这三条路径分别经过权限类（`IsNotMuted`）与 service 层（`_assert_can_act`），
    两条路必须给出同一个 code，否则前端想为禁言做专门引导就取不到稳定的机器码。
    """
    muted = user_factory(nickname="被禁言的人", is_gm=True, is_muted=True)
    game, running, gm = world["game"], world["running"], world["gm"]
    cases = [
        ("post", "/api/v1/games/", {"title": "禁言还想放团", "start_at": "2030-01-01T10:00:00+08:00"}),
        ("post", f"/api/v1/games/{running.pk}/signup/", {}),
        ("post", "/api/v1/reviews/", {"game": game.pk, "reviewee": gm.pk,
                                      "verdict": "like", "text": "禁言还想评"}),
    ]
    api_client.force_authenticate(muted)
    wrong = {}
    for method, url, payload in cases:
        response = getattr(api_client, method)(url, payload, format="json")
        if response.status_code != 403 or code_of(response) != "account_muted":
            wrong[(method, url)] = (response.status_code, response.json())
        else:
            assert_envelope(response)
    assert not wrong, f"以下禁言拒绝不是 403/account_muted：{wrong}"

    # 反向保险：解除禁言后同一个请求不再被这条闸挡住（否则上面可能只是「反正都失败」）。
    muted.is_muted = False
    muted.save(update_fields=["is_muted"])
    again = api_client.post(f"/api/v1/games/{running.pk}/signup/", {}, format="json")
    assert again.status_code == 201, again.json()


def test_封禁被拒一律是403加account_banned(api_client, world, user_factory):
    """封禁与注销要分得开：封禁同时置 is_active=False，判定顺序反了就会报成「已注销」。"""
    banned = user_factory(nickname="被封禁的人", is_banned=True, is_active=False)
    deactivated = user_factory(nickname="已注销的人", is_active=False, is_deactivated=True)
    urls = [
        "/api/v1/charactercards/mine/",
        f"/api/v1/games/{world['game'].pk}/roster/",
        "/api/v1/gallery/reports/mine/",
        "/api/v1/notifications/",
    ]
    expectations = [(banned, "account_banned"), (deactivated, "account_deactivated")]
    wrong = {}
    for user, expected_code in expectations:
        api_client.force_authenticate(user)
        for url in urls:
            response = api_client.get(url)
            if response.status_code != 403 or code_of(response) != expected_code:
                wrong[(user.nickname, url)] = (response.status_code, response.json())
            else:
                assert_envelope(response)
    assert not wrong, f"以下账号处置的 code 不对：{wrong}"


# --------------------------------------------------------------------------
# 403：已登录，但身份 / 角色 / 归属不允许
# --------------------------------------------------------------------------


def test_已登录但身份不符一律403(api_client, world):
    """not_gm / no_gm_card / not_game_gm / not_owner / 非同团 / 权限位缺失，全在这一格。"""
    game, report, outsider = world["game"], world["report"], world["outsider"]
    cases = [
        # 不是 GM → 放不了团
        ("post", "/api/v1/games/", {"title": "非GM团", "start_at": "2030-01-01T10:00:00+08:00"}, "not_gm"),
        # 不是 GM → 没有 GM 卡
        ("get", "/api/v1/profiles/me/gm-card/", {}, "no_gm_card"),
        # 不是本团 GM → 改不了公告
        ("patch", f"/api/v1/games/{game.pk}/", {"title": "篡改"}, "not_game_gm"),
        ("post", f"/api/v1/games/{game.pk}/cancel/", {"reason": "x"}, "not_game_gm"),
        # 不是同团 → 看不到正式名单
        ("get", f"/api/v1/games/{game.pk}/roster/", {}, "permission_denied"),
        # 不是本团到场者 → 评不了
        ("post", "/api/v1/reviews/", {"game": game.pk, "reviewee": world["gm"].pk,
                                      "verdict": "like", "text": "硬评"}, "not_attendee"),
        # 不是本团到场者 → 写不了战报
        ("post", "/api/v1/reports/", {"game": game.pk, "title": "硬写", "body_markdown": "x"}, "not_in_game"),
        # 不是本团到场者 → 也不能从文档导入战报正文（资格与写战报同口径）
        ("post", "/api/v1/reports/import-document/", {"game": game.pk}, "not_in_game"),
        # 没有审核权限位 → 进不了相册待办
        ("get", "/api/v1/gallery/moderation/queue/", {}, "permission_denied"),
        # 没有上传权限位 → 传不了资源
        ("post", "/api/v1/resources/", {"title": "x", "kind": "link", "url": "https://e.com"},
         "permission_denied"),

        ("patch", "/api/v1/home/admin/config/", {"site_name": "篡改站名"}, "permission_denied"),
        ("post", "/api/v1/home/admin/announcements/", {"title": "假公告", "body": "y"},
         "permission_denied"),
    ]
    api_client.force_authenticate(outsider)
    wrong = {}
    for method, url, payload, expected_code in cases:
        response = getattr(api_client, method)(url, payload, format="json")
        if response.status_code != 403 or code_of(response) != expected_code:
            wrong[(method, url)] = (response.status_code, response.json())
        else:
            assert_envelope(response)
    assert not wrong, f"以下接口不是 403/{'{expected_code}'}：{wrong}"

    # 不是本团 GM → 传不了活动照片（得带上真文件，否则先撞字段校验）
    api_client.force_authenticate(outsider)
    photo = api_client.post(
        f"/api/v1/gallery/games/{game.pk}/photos/",
        {"file": _png_upload()},
        format="multipart",
    )
    assert photo.status_code == 403
    #  拆码：相册这一处从 `not_game_gm` 改成 `photo_not_game_gm`（状态码不变）
    assert code_of(photo) == "photo_not_game_gm"

    # 不是作者 → 改不了战报（战报本身对同团可见，所以不是 404）
    api_client.force_authenticate(world["gm"])
    denied = api_client.patch(f"/api/v1/reports/{report.pk}/", {"title": "替人改"}, format="json")
    assert denied.status_code == 403
    assert code_of(denied) == "permission_denied"


# --------------------------------------------------------------------------
# 400：参数错误 / 目标状态不对 / 容量与重复
# --------------------------------------------------------------------------


def test_参数与业务状态错误一律400(api_client, world):
    game, running, gm, player = world["game"], world["running"], world["gm"], world["player"]

    api_client.force_authenticate(gm)
    cases = [
        # 参数校验
        ("post", "/api/v1/games/", {"title": ""}, "validation_error"),
        ("post", f"/api/v1/games/{running.pk}/cancel/", {"reason": ""}, "validation_error"),
        # 目标状态不对
        ("patch", f"/api/v1/games/{game.pk}/", {"title": "已结团还想改"}, "invalid_game_status"),
        ("post", f"/api/v1/games/{game.pk}/start/", {}, "invalid_game_status"),
        # 容量 / 重复 / 序号冲突由各 app 自己的用例守，这里只取有代表性的一条
        ("post", f"/api/v1/games/{running.pk}/expand/", {"max_players": 2}, "invalid_player_range"),
    ]
    wrong = {}
    for method, url, payload, expected_code in cases:
        response = getattr(api_client, method)(url, payload, format="json")
        if response.status_code != 400 or code_of(response) != expected_code:
            wrong[(method, url)] = (response.status_code, response.json())
        else:
            assert_envelope(response)
    assert not wrong, f"以下接口不是 400：{wrong}"

    # 「团还没结团」在 games / reviews / reports / gallery 四个 app 里是同一格：400
    api_client.force_authenticate(player)
    not_open = api_client.post(
        "/api/v1/reviews/",
        {"game": running.pk, "reviewee": gm.pk, "verdict": "like", "text": "没结团就评"},
        format="json",
    )
    assert not_open.status_code == 400 and code_of(not_open) == "review_not_open"

    no_report = api_client.post(
        "/api/v1/reports/",
        {"game": running.pk, "title": "没结团就写", "body_markdown": "x"},
        format="json",
    )
    assert no_report.status_code == 400 and code_of(no_report) == "game_not_finished"


def test_精选非公开照片是400(api_client, world, user_factory, settings, tmp_path):
    """「这张照片的状态不对」属于「这次请求不行」，落 400（第 5.1 节的分界线）。"""
    from apps.gallery import services as gallery_services
    from apps.gallery.tests.conftest import photo_upload

    settings.MEDIA_ROOT = tmp_path  # 这条用例真的会落盘三档文件，别留在仓库里
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME

    staff = user_factory(nickname="矩阵站主", is_staff=True)
    photo = gallery_services.upload_photo(
        world["gm"], world["game"], photo_upload(), caption="矩阵合影"
    )
    gallery_services.take_down_photo(photo, reason="先下架")

    api_client.force_authenticate(staff)
    response = api_client.post(
        "/api/v1/home/admin/featured-photos/",
        {"photo": photo.pk, "is_featured": True},
        format="json",
    )
    assert response.status_code == 400
    assert code_of(response) == "photo_not_public"
    assert_envelope(response)


def test_时间窗关闭在各app里都是400(api_client, world, site_config):
    """games 的交卡截止、reviews 的评价窗口、gallery 的上传窗口是同一类事。"""
    from apps.games.models import Game

    game, player, gm = world["game"], world["player"], world["gm"]
    Game.objects.filter(pk=game.pk).update(
        finished_at=timezone.now() - timedelta(days=site_config.review_window_days + 1)
    )
    api_client.force_authenticate(player)
    closed = api_client.post(
        "/api/v1/reviews/",
        {"game": game.pk, "reviewee": gm.pk, "verdict": "like", "text": "过期了"},
        format="json",
    )
    assert closed.status_code == 400
    assert code_of(closed) == "review_window_closed"


# --------------------------------------------------------------------------
# 404：对方看不见的对象
# --------------------------------------------------------------------------


def test_看不见的对象一律404(api_client, world):
    """403 等于承认「它存在，只是你不能看」；主键是自增整数，枚举一遍就能数出来。"""
    card, report, unapproved = world["private_card"], world["report"], world["unapproved"]
    api_client.force_authenticate(world["gm"])  # 站主之外的登录身份
    outsider_cases = [
        ("get", f"/api/v1/charactercards/{card.pk}/"),  # 他人的私密卡
        ("get", f"/api/v1/charactercards/{card.pk}/download/"),
        ("get", f"/api/v1/charactercards/mine/{card.pk}/"),  # mine/<别人的 id>
        ("get", f"/api/v1/resources/{unapproved.pk}/"),  # 未审核的资源
    ]
    wrong = {}
    for method, url in outsider_cases:
        response = getattr(api_client, method)(url)
        if response.status_code != 404:
            wrong[(method, url)] = response.status_code
        else:
            assert_envelope(response)
            assert code_of(response) == "not_found", url
    assert not wrong, f"以下不可见对象不是 404：{wrong}"

    # 同团限定的战报对局外人是 404（而不是 403）
    api_client.force_authenticate(world["outsider"])
    hidden = api_client.get(f"/api/v1/reports/{report.pk}/")
    assert hidden.status_code == 404 and code_of(hidden) == "not_found"

    # 游客同理：401 会泄露「这个对象存在」
    api_client.force_authenticate(None)
    assert api_client.get(f"/api/v1/charactercards/{card.pk}/").status_code == 404
    assert api_client.get(f"/api/v1/reports/{report.pk}/").status_code == 404


def test_不存在的主键与看不见的对象状态码相同(api_client, world):
    """两者必须无法区分，否则 404 的意义就没了。"""
    api_client.force_authenticate(world["gm"])
    missing = api_client.get("/api/v1/charactercards/99999999/")
    hidden = api_client.get(f"/api/v1/charactercards/{world['private_card'].pk}/")
    assert missing.status_code == hidden.status_code == 404
    assert missing.json() == hidden.json()


# --------------------------------------------------------------------------
# 反向保险：公开只读接口不受影响
# --------------------------------------------------------------------------


def test_公开只读接口对游客仍然是200(api_client, world):
    """统一状态码不能把游客可见范围一起收紧了。"""
    for url in (
        "/api/v1/health/",
        "/api/v1/siteconfig/",
        "/api/v1/content/glossary/",
        "/api/v1/resources/",
        "/api/v1/resources/categories/",
        "/api/v1/charactercards/pool/",
        "/api/v1/games/",
        "/api/v1/games/tags/",
        f"/api/v1/games/{world['game'].pk}/",
        "/api/v1/reports/",
        "/api/v1/reports/featured/",
        f"/api/v1/profiles/users/{world['player'].pk}/",
    ):
        assert api_client.get(url).status_code == 200, url


# --------------------------------------------------------------------------
# 一码多义：同一个 code 不许有两个说法不同的来源
#
# 拆码前 `not_gm` 与 `card_file_missing` 各有两个来源，两边该说的话不一样，
# 前端 `lib/api-error.ts` 只能把这两个 code 整个从映射表里摘掉
# （收进来必然覆盖错一边）。现在四个码各归各的：
#   games.services.NotGM               → not_gm（只有 GM 才能放团。）
#   profiles.views.NoGMCard            → no_gm_card（你尚未成为 GM，暂无 GM 卡。）
#   games.services.SignupCardFileMissing → signup_card_file_missing（交卡那句）
#   charactercards.views.CardFileMissing → card_file_missing（这张卡还没有文件。）
# --------------------------------------------------------------------------


def test_四个拆开的码互不相同且文案各自保持原样():
    from apps.charactercards.views import CardFileMissing
    from apps.games.services import NotGM, SignupCardFileMissing
    from apps.profiles.views import NoGMCard

    pairs = {
        NotGM.default_code: NotGM.default_detail,
        NoGMCard.default_code: NoGMCard.default_detail,
        SignupCardFileMissing.default_code: SignupCardFileMissing.default_detail,
        CardFileMissing.default_code: CardFileMissing.default_detail,
    }
    assert set(pairs) == {
        "not_gm",
        "no_gm_card",
        "signup_card_file_missing",
        "card_file_missing",
    }, pairs
    # 文案一字不改
    assert pairs["not_gm"] == "只有 GM 才能放团。"
    assert pairs["no_gm_card"] == "你尚未成为 GM，暂无 GM 卡。"
    assert pairs["signup_card_file_missing"] == "这张卡尚未上传文件，请先上传文件后再交卡。"
    assert pairs["card_file_missing"] == "这张卡还没有文件。"


def test_相册拆出的三个码与games_reports互不相同且文案各自保持原样():
    """第二批拆码：gallery 三处改名，games / reports 原码不动。"""
    from apps.gallery import services as gallery
    from apps.games.services import NotGameGM
    from apps.reports import services as reports

    pairs = {
        NotGameGM.default_code: NotGameGM.default_detail,
        gallery.NotGameGM.default_code: gallery.NotGameGM.default_detail,
        reports.GameNotFinished.default_code: reports.GameNotFinished.default_detail,
        gallery.GameNotFinished.default_code: gallery.GameNotFinished.default_detail,
        reports.AlreadyReported.default_code: reports.AlreadyReported.default_detail,
        gallery.AlreadyReported.default_code: gallery.AlreadyReported.default_detail,
    }
    assert len(pairs) == 6, pairs
    assert pairs["not_game_gm"] == "只有本团的 GM 才能做这件事。"
    assert pairs["photo_not_game_gm"] == "只有本团的 GM 才能上传本团的照片。"
    assert pairs["game_not_finished"] == "团结束后才能撰写战报。"
    assert pairs["photo_game_not_finished"] == "团结束后才能上传照片。"
    assert pairs["already_reported"] == "你已经举报过这份战报。"
    assert pairs["photo_already_reported"] == "你已经举报过这张照片。"


def test_交卡与下载两处的空壳卡码不再撞车(api_client, world, user_factory):
    """一个 400 一个 404，code 也必须分得开 —— 前端才有可能各说各的话。"""
    from apps.charactercards import services as card_services
    from apps.games import services as game_services

    gm = world["gm"]
    player = user_factory(nickname="空壳卡PL")
    game = game_services.create_game(
        gm,
        title="要交卡的团",
        rule_system="COC",
        start_at=timezone.now() + timedelta(days=2),
        min_players=1,
        max_players=5,
        requires_card=True,
    )
    game_services.signup(game, player)
    empty = card_services.create_card(player, name="空壳卡", is_public=True)

    api_client.force_authenticate(player)
    submit = api_client.post(
        f"/api/v1/games/{game.pk}/submit-card/", {"card_id": empty.pk}, format="json"
    )
    assert submit.status_code == 400
    assert code_of(submit) == "signup_card_file_missing", submit.json()

    download = api_client.get(f"/api/v1/charactercards/{empty.pk}/download/")
    assert download.status_code == 404
    assert code_of(download) == "card_file_missing", download.json()
