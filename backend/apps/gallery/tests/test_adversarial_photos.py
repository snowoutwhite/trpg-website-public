"""红队（W3）：相册的上传闸门 / 可见性 / 举报 / 状态机 / CSRF。

攻击视角，不是功能视角：
- 上传闸：别的团的 GM、同团 PL、站主（非本团 GM）、未结团 / 已取消团、窗口边界、
  配额边界与「检查—插入」之间的并发窗口。
- 可见性：看不见的照片与不存在的照片必须**长得一模一样**（否则 id 枚举就是存在性探测）。
- 举报：举报人身份对 uploader 的**任何**泄露通道，包括站主写给举报人的备注被回显给 GM。
- 状态：模式切换不回溯、删除带未处理举报的照片不炸、恢复后能否再举报。
- 全路由的游客状态码表与 CSRF 表。
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.gallery import services
from apps.gallery.models import (
    PHOTO_PENDING_REVIEW,
    PHOTO_PUBLIC,
    PHOTO_REJECTED,
    PHOTO_TAKEN_DOWN,
    REASON_IN_PHOTO,
    RESULT_RESTORED,
    RESULT_TAKEN_DOWN,
    Photo,
    PhotoReport,
)
from apps.siteconfig.models import (
    GALLERY_MODE_POST_REPORT,
    GALLERY_MODE_PRE_REVIEW,
    GALLERY_MODE_PUBLIC,
)

from .conftest import make_image_bytes, photo_upload

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def list_url(game):
    return reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk})


def detail_url(pk):
    return reverse("v1:gallery:photo-detail", kwargs={"pk": pk})


def file_url(pk, size="thumb"):
    return reverse("v1:gallery:photo-file", kwargs={"pk": pk}) + f"?size={size}"


def report_url(pk):
    return reverse("v1:gallery:photo-report", kwargs={"pk": pk})


def handle_url(pk):
    return reverse("v1:gallery:moderation-handle-report", kwargs={"pk": pk})


def tiny() -> bytes:
    """小图：配额类用例要造几十张，用 1200×800 会把测试跑成龟速。"""
    return make_image_bytes(size=(60, 40))


def tiny_upload(name="a.jpg"):
    return photo_upload(name, tiny())


def set_mode(site_config, mode):
    site_config.gallery_moderation_mode = mode
    site_config.save(update_fields=["gallery_moderation_mode"])


# ==========================================================================
# 1. 上传闸门
# ==========================================================================


def test_nobody_but_this_games_gm_can_upload(
    api_client, finished_game, gm_factory, user_factory, owner_user
):
    """「是 GM」≠「是此团的 GM」；站主有审核权限位也不等于有上传权。"""
    game = finished_game(gm_factory())
    attackers = {
        "别的团的 GM": gm_factory(),
        "普通登录用户": user_factory(),
        "站主（持审核权限位）": owner_user,
    }
    for label, attacker in attackers.items():
        client = APIClient()
        client.force_login(attacker)
        response = client.post(list_url(game), {"file": tiny_upload()}, format="multipart")
        assert response.status_code == 403, f"{label} 上传得到 {response.status_code}"
        assert response.json()["error"]["code"] == "photo_not_game_gm"
    assert Photo.objects.count() == 0


@pytest.mark.parametrize(
    ("status_value", "clear_finished_at"),
    [("recruiting", False), ("running", False), ("cancelled", False), ("finished", True)],
)
def test_unfinished_cancelled_or_finished_at_less_game_refuses_upload(
    api_client, finished_game, gm_factory, status_value, clear_finished_at
):
    """未结团 / 已取消 / 状态是 finished 但没有 finished_at（脏数据）都必须挡住。"""
    gm = gm_factory()
    game = finished_game(gm)
    game.status = status_value
    if clear_finished_at:
        game.finished_at = None
    game.save(update_fields=["status", "finished_at"])

    api_client.force_login(gm)
    response = api_client.post(list_url(game), {"file": tiny_upload()}, format="multipart")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "photo_game_not_finished"
    assert Photo.objects.count() == 0


def test_upload_window_boundary_is_inclusive_to_the_last_second(
    finished_game, gm_factory, site_config
):
    """第 30 天末尾还能传，越过一秒就不能 —— 边界两侧各测一次（Asia/Shanghai）。"""
    from datetime import timedelta

    gm = gm_factory()
    game = finished_game(gm, finished_ago=timedelta(0))
    deadline = services.upload_window_deadline(game)
    assert deadline == game.finished_at + timedelta(days=site_config.gallery_upload_window_days)

    # 边界上（正好 deadline 这一刻）：放行。
    services.assert_can_upload(gm, game, now=deadline)
    # 边界后一秒：拒绝。
    with pytest.raises(services.UploadWindowClosed):
        services.assert_can_upload(gm, game, now=deadline + timedelta(seconds=1))
    # 站主把窗口改小，已过期的团立刻关门（阈值不许硬编码）。
    site_config.gallery_upload_window_days = 1
    site_config.save(update_fields=["gallery_upload_window_days"])
    from apps.siteconfig.services import get_config

    get_config.cache_clear() if hasattr(get_config, "cache_clear") else None
    with pytest.raises(services.UploadWindowClosed):
        services.assert_can_upload(gm, game, now=game.finished_at + timedelta(days=2))


def test_quota_blocks_the_next_photo_and_gm_cannot_self_reject_to_refill(
    api_client, finished_game, gm_factory, monkeypatch
):
    """配额边界 + 「用 rejected 刷配额」这条解读能不能被 GM 单方面利用。

    `rejected` 不占配额是有意为之，但置为 rejected 的唯一入口是站主的审核接口；
    GM 自己打那个接口必须 403，否则配额就是无限的。
    """
    monkeypatch.setattr(services, "PHOTO_MAX_PER_GAME", 3)
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)
    for _ in range(3):
        assert api_client.post(
            list_url(game), {"file": tiny_upload()}, format="multipart"
        ).status_code == 201

    over = api_client.post(list_url(game), {"file": tiny_upload()}, format="multipart")
    assert over.status_code == 400
    assert over.json()["error"]["code"] == "gallery_quota_exceeded"

    # GM 想自己把照片打成 rejected 来腾配额 → 审核接口必须拒绝他。
    victim = Photo.objects.filter(game=game).first()
    reject = api_client.post(
        reverse("v1:gallery:moderation-reject", kwargs={"pk": victim.pk}),
        {"reason": "自己驳回自己"},
        format="json",
    )
    assert reject.status_code == 403
    victim.refresh_from_db()
    assert victim.status != PHOTO_REJECTED
    assert Photo.objects.filter(game=game).count() == 3


def test_quota_cannot_be_overshot_by_a_second_upload_landing_mid_encode(
    finished_game, gm_factory, monkeypatch
):
    """并发突破配额：配额是「先数后插」，中间隔着三档 WebP 编码那几十毫秒。

    这里把那段窗口显式化 —— A 请求正在编码时 B 请求整个跑完并落库。
    没有二次校验的话 A 会在配额已满之后照样插进去，结果是 MAX+1 张。
    """
    monkeypatch.setattr(services, "PHOTO_MAX_PER_GAME", 2)
    gm = gm_factory()
    game = finished_game(gm)
    services.upload_photo(gm, game, tiny_upload())  # 已用 1 / 2

    real_encode = services._encode_tiers
    state = {"fired": False}

    def encode_with_a_concurrent_upload(uploaded_file):
        if not state["fired"]:
            state["fired"] = True
            # B 请求：在 A 还在编码的时候整条跑完，把配额用满。
            services.upload_photo(gm, game, tiny_upload())
        return real_encode(uploaded_file)

    monkeypatch.setattr(services, "_encode_tiers", encode_with_a_concurrent_upload)

    with pytest.raises(services.PhotoQuotaExceeded):
        services.upload_photo(gm, game, tiny_upload())
    # 注：这里 B 是跑在 A 的事务里的嵌套 savepoint，A 回滚会把 B 一起带走，
    # 所以只断言「配额没被突破」这一条（真实并发下 B 是独立事务，会留下）。
    # 修复前这一步是 3 张 > 上限 2，而且上面的 raises 根本不会触发。
    assert Photo.objects.filter(game=game).count() <= 2


def test_ten_mb_boundary(api_client, finished_game, gm_factory):
    """10 MB 上下各一发：恰好放行，多一字节拒绝（体积闸不能只看 Content-Length）。"""
    from apps.gallery.models import PHOTO_MAX_BYTES

    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)

    body = make_image_bytes(size=(900, 600))
    padded = body + b"\x00" * (PHOTO_MAX_BYTES - len(body))  # JPEG 尾部垃圾不影响解码
    assert len(padded) == PHOTO_MAX_BYTES
    assert api_client.post(
        list_url(game), {"file": photo_upload("ok.jpg", padded)}, format="multipart"
    ).status_code == 201

    over = api_client.post(
        list_url(game), {"file": photo_upload("big.jpg", padded + b"\x00")}, format="multipart"
    )
    assert over.status_code == 400
    assert over.json()["error"]["code"] == "image_too_large"


def test_hostile_caption_is_rejected_or_neutralised(api_client, finished_game, gm_factory):
    """图注：NUL / 换行 / 超长 / HTML 载荷。要么 400，要么原样当数据存，不许 500。"""
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)

    # NUL 字符：Postgres 的 text 列直接拒收，漏到 DB 层就是 500。
    nul = api_client.post(
        list_url(game),
        {"file": tiny_upload(), "caption": "正常\x00注入"},
        format="multipart",
    )
    assert nul.status_code == 400

    # 超长：序列化器 max_length=200 必须先挡，不能靠 services 里的截断兜底。
    too_long = api_client.post(
        list_url(game), {"file": tiny_upload(), "caption": "字" * 201}, format="multipart"
    )
    assert too_long.status_code == 400

    # 控制字符 + HTML：入库即可，但必须以 application/json 的**数据**形态回来，
    # 不能是 text/html（那样媒体域上就能直接把它当页面渲染）。
    payload = "第一行\r\n<img src=x onerror=alert(1)>\t结束"
    created = api_client.post(
        list_url(game), {"file": tiny_upload(), "caption": payload}, format="multipart"
    )
    assert created.status_code == 201
    assert created["Content-Type"].startswith("application/json")
    assert created.json()["caption"] == payload  # 原样存、原样回，解析出来还是字符串


# ==========================================================================
# 2. 可见性与 id 枚举
# ==========================================================================


@pytest.mark.parametrize("hidden_status", [PHOTO_PENDING_REVIEW, PHOTO_TAKEN_DOWN, PHOTO_REJECTED])
def test_hidden_photo_is_indistinguishable_from_a_nonexistent_id(
    api_client, photo_factory, user_factory, hidden_status
):
    """顺序 id + 403/404 不一致 = 存在性探测。三条路径的响应必须逐字节一致。"""
    photo = photo_factory()
    photo.status = hidden_status
    photo.save(update_fields=["status"])
    ghost_id = photo.pk + 10_000

    api_client.force_login(user_factory())
    for builder in (detail_url, file_url, report_url):
        hidden = api_client.get(builder(photo.pk)) if builder is not report_url else api_client.post(
            builder(photo.pk), {"reason": REASON_IN_PHOTO}, format="json"
        )
        ghost = api_client.get(builder(ghost_id)) if builder is not report_url else api_client.post(
            builder(ghost_id), {"reason": REASON_IN_PHOTO}, format="json"
        )
        assert hidden.status_code == ghost.status_code == 404, builder.__name__
        assert hidden.content == ghost.content, f"{builder.__name__} 的 404 响应体不一致"


def test_hidden_photo_never_appears_in_any_list(api_client, photo_factory, user_factory):
    """列表接口不能靠「总数」泄露隐藏照片的存在。"""
    public_photo = photo_factory()
    hidden = photo_factory(game=public_photo.game)
    hidden.status = PHOTO_TAKEN_DOWN
    hidden.save(update_fields=["status"])

    api_client.force_login(user_factory())
    body = api_client.get(list_url(public_photo.game)).json()
    ids = [row["id"] for row in body["results"]]
    assert ids == [public_photo.pk]
    assert body["count"] == 1, "count 把隐藏的那张也数进去了"


@pytest.mark.parametrize(
    "size",
    [
        "../../../etc/passwd",
        "__class__",
        "ORIGINAL",
        "  original  ",
        "original\x00",
        "thumb;preview",
        "x" * 500,
        "",
    ],
)
def test_hostile_size_parameter_never_500s_or_escapes_the_whitelist(
    api_client, photo_factory, user_factory, size
):
    """`?size=` 只认三个白名单值；认不出退回缩略图，绝不拿它当属性名或路径片段。"""
    photo = photo_factory()
    api_client.force_login(user_factory())
    response = api_client.get(reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk}), {"size": size})
    assert response.status_code == 200
    assert response["Content-Type"] == "image/webp"
    body = b"".join(response.streaming_content)
    assert body[:4] == b"RIFF"
    if size.strip().lower() != "original":
        # 非法值必须退到缩略图这一档，不能悄悄把原图端出去。
        with photo.thumbnail.storage.open(photo.thumbnail.name, "rb") as handle:
            assert body == handle.read()


def test_no_response_leaks_email_storage_path_or_reporter(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """一次扫全部返回体：邮箱 / protected 路径 / 存储文件名 / 举报人昵称。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    reporter = user_factory(nickname="举报人甲", email="reporter@example.com")
    services.report_photo(reporter, photo, reason=REASON_IN_PHOTO, reason_text="我在照片里")

    forbidden = [
        photo.uploader.email,
        reporter.email,
        "protected/",
        photo.original.name.rsplit("/", 1)[-1],
    ]
    # ① uploader（GM）视角
    api_client.force_login(photo.uploader)
    for url in (list_url(photo.game), detail_url(photo.pk), reverse("v1:gallery:my-reports")):
        raw = api_client.get(url).content.decode()
        for needle in forbidden + ["举报人甲", "reporter@example.com"]:
            assert needle not in raw, f"{url} 泄露了 {needle}"

    # ② 站主视角：允许看到举报人（那是处置所需），但邮箱与存储路径依然不许出现。
    api_client.force_login(owner_user)
    raw = api_client.get(reverse("v1:gallery:moderation-queue")).content.decode()
    for needle in forbidden:
        assert needle not in raw, f"moderation queue 泄露了 {needle}"
    # W5：待办两个列表各自分页，行在 results 里
    assert "举报人甲" in json.loads(raw)["open_reports"]["results"][0]["reporter"]["nickname"]


def test_uploader_cannot_learn_who_reported_through_the_moderator_note(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """站主写给**举报人**的备注不得被回显给被举报的 GM。

    `result_note` 的字段说明就是「给举报人的说明」，站主很自然会在里面写
    「XXX 说自己在照片里」。这段文字如果同时落进照片的 `taken_down_reason`，
    GM 打开自己那张被下架的照片就直接看见举报人是谁 —— 红线②的泄露通道。
    """
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    reporter = user_factory(nickname="被拍到的人")
    report = services.report_photo(reporter, photo, reason=REASON_IN_PHOTO)

    api_client.force_login(owner_user)
    note = "被拍到的人 本人来信要求下架，已核实"
    assert api_client.post(
        handle_url(report.pk), {"action": RESULT_TAKEN_DOWN, "note": note}, format="json"
    ).status_code == 200

    # 举报人应当收到这段说明。
    api_client.force_login(reporter)
    mine = api_client.get(reverse("v1:gallery:my-reports")).json()["results"][0]
    assert mine["result_note"] == note

    # 被举报的 GM 绝不能看到它。
    api_client.force_login(photo.uploader)
    raw = api_client.get(detail_url(photo.pk)).content.decode()
    assert "被拍到的人" not in raw, "站主写给举报人的备注被回显给了 uploader"


# ==========================================================================
# 3. 举报
# ==========================================================================


def test_duplicate_report_is_refused_without_revealing_anything_new(
    api_client, photo_factory, user_factory, site_config
):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    api_client.force_login(user_factory())
    assert api_client.post(report_url(photo.pk), {"reason": REASON_IN_PHOTO}, format="json").status_code == 201
    again = api_client.post(report_url(photo.pk), {"reason": REASON_IN_PHOTO}, format="json")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "photo_already_reported"
    assert PhotoReport.objects.count() == 1


def test_one_report_from_any_logged_in_user_takes_the_photo_down(
    api_client, photo_factory, user_factory, site_config
):
    """「举报后下架」模式的产品风险固化成用例：一个**无关**账号一次举报即下架。

    这是需求的字面口径（站主三选一），不是实现缺陷；用例在这里是为了让
    「换个解读」时一定会有东西变红，而不是悄悄改掉。
    """
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    stranger = user_factory()  # 跟此团毫无关系
    api_client.force_login(stranger)
    assert api_client.post(report_url(photo.pk), {"reason": "other"}, format="json").status_code == 201
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN
    # 下架理由里不带举报人任何信息。
    assert stranger.nickname not in photo.taken_down_reason


def test_restored_photo_can_be_reported_again_by_the_same_person(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """W5 已修：唯一约束改成「同时只能有一条 open 举报」。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    victim = user_factory()
    report = services.report_photo(victim, photo, reason=REASON_IN_PHOTO)

    api_client.force_login(owner_user)
    api_client.post(handle_url(report.pk), {"action": RESULT_RESTORED}, format="json")
    photo.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC

    api_client.force_login(victim)
    again = api_client.post(report_url(photo.pk), {"reason": REASON_IN_PHOTO}, format="json")
    assert again.status_code == 201, "恢复展示后被拍到者又没有下架入口了"
    assert PhotoReport.objects.filter(photo=photo, reporter=victim).count() == 2
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN  # 「举报后下架」模式下再次自动下架


def test_open_report_still_blocks_a_second_one_from_the_same_person(
    api_client, photo_factory, user_factory, site_config
):
    """放开的只是「处理完之后」；上一条还挂着的时候仍然拦。"""
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    victim = user_factory()
    services.report_photo(victim, photo, reason=REASON_IN_PHOTO)

    api_client.force_login(victim)
    again = api_client.post(report_url(photo.pk), {"reason": REASON_IN_PHOTO}, format="json")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "photo_already_reported"
    assert PhotoReport.objects.filter(photo=photo, reporter=victim).count() == 1


def test_reports_mine_shows_only_my_own(api_client, photo_factory, user_factory, site_config):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    mine_user, other = user_factory(), user_factory()
    services.report_photo(mine_user, photo, reason=REASON_IN_PHOTO, reason_text="我的诉求")
    services.report_photo(other, photo, reason="other", reason_text="别人的诉求")

    api_client.force_login(mine_user)
    body = api_client.get(reverse("v1:gallery:my-reports")).content.decode()
    assert "我的诉求" in body
    assert "别人的诉求" not in body
    assert json.loads(body)["count"] == 1


def test_moderation_routes_need_the_permission_bit_not_a_role_guess(
    api_client, photo_factory, user_factory, site_config
):
    """普通用户 / staff / 被举报照片的 GM，一律 403：能力只认权限位。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    staff = user_factory()
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])

    for label, attacker in {
        "普通用户": user_factory(),
        "is_staff 但没有权限位": staff,
        "被举报照片的 GM": photo.uploader,
    }.items():
        client = APIClient()
        client.force_login(attacker)
        assert client.get(reverse("v1:gallery:moderation-queue")).status_code == 403, label
        assert client.post(
            reverse("v1:gallery:moderation-approve", kwargs={"pk": photo.pk})
        ).status_code == 403, label
        assert client.post(
            handle_url(report.pk), {"action": RESULT_RESTORED}, format="json"
        ).status_code == 403, label
    report.refresh_from_db()
    assert report.status == "open"


def test_report_cannot_be_handled_twice(api_client, photo_factory, user_factory, owner_user, site_config):
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    api_client.force_login(owner_user)
    assert api_client.post(handle_url(report.pk), {"action": RESULT_RESTORED}, format="json").status_code == 200
    again = api_client.post(handle_url(report.pk), {"action": RESULT_TAKEN_DOWN}, format="json")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "report_already_handled"


# ==========================================================================
# 4. 状态机
# ==========================================================================


def test_mode_switch_does_not_retroactively_restate_existing_photos(
    photo_factory, finished_game, gm_factory, site_config
):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    already_public = photo_factory()
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    pending = photo_factory()
    set_mode(site_config, GALLERY_MODE_POST_REPORT)

    already_public.refresh_from_db()
    pending.refresh_from_db()
    assert already_public.status == PHOTO_PUBLIC
    assert pending.status == PHOTO_PENDING_REVIEW


def test_deleting_someone_elses_photo_is_a_404(api_client, photo_factory, user_factory, gm_factory):
    photo = photo_factory()
    for attacker in (user_factory(), gm_factory()):
        client = APIClient()
        client.force_login(attacker)
        assert client.delete(detail_url(photo.pk)).status_code == 404
    assert Photo.objects.filter(pk=photo.pk).exists()


def test_deleting_a_photo_with_an_open_report_does_not_strand_anything(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """GM 删掉正被举报的照片：举报随之消失，站主待办与举报人列表都不能 500。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    reporter = user_factory()
    report = services.report_photo(reporter, photo, reason=REASON_IN_PHOTO)

    api_client.force_login(photo.uploader)
    assert api_client.delete(detail_url(photo.pk)).status_code == 204

    api_client.force_login(owner_user)
    queue = api_client.get(reverse("v1:gallery:moderation-queue"))
    assert queue.status_code == 200
    assert queue.json()["open_reports"]["results"] == []  # W5：待办已分页
    assert api_client.post(handle_url(report.pk), {"action": RESULT_RESTORED}, format="json").status_code == 404

    api_client.force_login(reporter)
    mine = api_client.get(reverse("v1:gallery:my-reports"))
    assert mine.status_code == 200
    assert mine.json()["count"] == 0


# ==========================================================================
# 5. 游客状态码全表 + CSRF 全表
# ==========================================================================


def test_guest_status_table_for_every_route(api_client, photo_factory, user_factory, site_config):
    """游客打全部 10 条路由：登录闸必须在一切业务判断之前，且都是 401。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    routes = [
        ("get", list_url(photo.game)),
        ("post", list_url(photo.game)),
        ("get", detail_url(photo.pk)),
        ("delete", detail_url(photo.pk)),
        ("get", file_url(photo.pk, "original")),
        ("post", report_url(photo.pk)),
        ("get", reverse("v1:gallery:my-reports")),
        ("get", reverse("v1:gallery:moderation-queue")),
        ("post", reverse("v1:gallery:moderation-approve", kwargs={"pk": photo.pk})),
        ("post", reverse("v1:gallery:moderation-reject", kwargs={"pk": photo.pk})),
        ("post", handle_url(report.pk)),
    ]
    for method, url in routes:
        response = getattr(api_client, method)(url)
        assert response.status_code == 401, f"{method.upper()} {url} -> {response.status_code}"
        assert response.json()["error"]["code"] == "not_authenticated", url
    # 未登录一路打下来，什么都没被改。
    photo.refresh_from_db()
    report.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN and report.status == "open"


def test_csrf_is_enforced_on_every_write_route(photo_factory, user_factory, owner_user, site_config):
    """会话认证下的写接口全表过 CSRF —— 少一条就是站外表单能打的点。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    writes = [
        (photo.uploader, "post", list_url(photo.game)),
        (photo.uploader, "delete", detail_url(photo.pk)),
        (user_factory(), "post", report_url(photo.pk)),
        (owner_user, "post", reverse("v1:gallery:moderation-approve", kwargs={"pk": photo.pk})),
        (owner_user, "post", reverse("v1:gallery:moderation-reject", kwargs={"pk": photo.pk})),
        (owner_user, "post", handle_url(report.pk)),
    ]
    for actor, method, url in writes:
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(actor)  # 真实会话 cookie，不是 force_authenticate
        response = getattr(client, method)(url, {}, format="json")
        assert response.status_code == 403, f"{method.upper()} {url} 没有过 CSRF 闸"
    photo.refresh_from_db()
    report.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN and report.status == "open"
    assert Photo.objects.filter(pk=photo.pk).exists()


def test_report_response_reveals_nothing_the_public_config_does_not_already_say(
    api_client, photo_factory, user_factory, site_config
):
    """举报响应里的 `photo_status` 会暴露「站点是不是举报即下架」模式。

    这不构成泄露 —— `gallery_moderation_mode` 本来就在公开的站点配置接口里，
    游客都能读。用例把这个前提钉住：哪天有人把模式从公开配置里拿掉，
    这里就会变红，提醒重新评估举报响应。
    """
    public_config = api_client.get(reverse("v1:siteconfig:detail")).json()
    assert "gallery_moderation_mode" in public_config

    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    api_client.force_login(user_factory())
    body = api_client.post(report_url(photo.pk), {"reason": REASON_IN_PHOTO}, format="json").json()
    assert body["photo_status"] == PHOTO_TAKEN_DOWN


def test_图注含RTL覆盖字符一律400(api_client, finished_game, gm_factory):
    """业务规则与安全约束。"""
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_login(gm)
    response = api_client.post(
        list_url(game), {"file": tiny_upload(), "caption": "坏\u202e图"}, format="multipart"
    )
    assert response.status_code == 400, response.content
    assert not Photo.objects.filter(game=game).exists()
