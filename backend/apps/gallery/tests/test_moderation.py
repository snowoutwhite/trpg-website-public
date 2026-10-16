"""三种审核模式的状态流转、举报去重、举报处置与通知。"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.gallery import services
from apps.gallery.models import (
    PHOTO_PENDING_REVIEW,
    PHOTO_PUBLIC,
    PHOTO_REJECTED,
    PHOTO_TAKEN_DOWN,
    REASON_IN_PHOTO,
    REPORT_HANDLED,
    REPORT_OPEN,
    RESULT_DISMISSED,
    RESULT_RESTORED,
    RESULT_TAKEN_DOWN,
    PhotoReport,
)
from apps.notifications import events
from apps.notifications.models import Notification
from apps.siteconfig.models import (
    GALLERY_MODE_POST_REPORT,
    GALLERY_MODE_PRE_REVIEW,
    GALLERY_MODE_PUBLIC,
)

from .conftest import photo_upload

pytestmark = pytest.mark.django_db


def report_url(photo) -> str:
    return reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk})


def handle_url(report) -> str:
    return reverse("v1:gallery:moderation-handle-report", kwargs={"pk": report.pk})


def set_mode(site_config, mode):
    site_config.gallery_moderation_mode = mode
    site_config.save()


# --------------------------------------------------------------------------
# 模式一：默认公开
# --------------------------------------------------------------------------


def test_mode_public_uploads_go_live(api_client, photo_factory, site_config):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    assert photo.status == PHOTO_PUBLIC


def test_mode_public_report_does_not_auto_take_down(
    api_client, photo_factory, user_factory, site_config
):
    """默认公开模式下，举报只落一条待办，照片不自动下架（站级三选项的字面口径）。"""
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.post(report_url(photo), {"reason": REASON_IN_PHOTO}, format="json")
    assert response.status_code == 201

    photo.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC
    assert PhotoReport.objects.filter(photo=photo, status=REPORT_OPEN).count() == 1


# --------------------------------------------------------------------------
# 模式二：公开前审核
# --------------------------------------------------------------------------


def test_mode_pre_review_full_flow(api_client, finished_game, gm_factory, owner_user, site_config):
    """pending → 站主通过 → public；另一张 → 站主驳回 → rejected。"""
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    gm = gm_factory()
    game = finished_game(gm)
    good = services.upload_photo(gm, game, photo_upload())
    bad = services.upload_photo(gm, game, photo_upload())
    assert good.status == bad.status == PHOTO_PENDING_REVIEW

    api_client.force_authenticate(owner_user)
    queue = api_client.get(reverse("v1:gallery:moderation-queue")).json()
    # W5：待办两个列表各自分页，形状与全站分页一致
    assert queue["pending_photos"]["count"] == 2
    assert {row["id"] for row in queue["pending_photos"]["results"]} == {good.pk, bad.pk}

    approve = api_client.post(
        reverse("v1:gallery:moderation-approve", kwargs={"pk": good.pk}), {}, format="json"
    )
    assert approve.status_code == 200
    good.refresh_from_db()
    assert good.status == PHOTO_PUBLIC

    reject = api_client.post(
        reverse("v1:gallery:moderation-reject", kwargs={"pk": bad.pk}),
        {"reason": "有路人正脸"},
        format="json",
    )
    assert reject.status_code == 200
    bad.refresh_from_db()
    assert bad.status == PHOTO_REJECTED
    assert bad.taken_down_reason == "有路人正脸"


def test_rejected_photo_frees_quota(finished_game, gm_factory, site_config):
    """业务规则与安全约束。"""
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload())
    services.reject_photo(photo, reason="不合适")
    services.assert_can_upload(gm, game)  # 不抛就是没占配额


def test_non_moderator_cannot_moderate(api_client, photo_factory, user_factory, gm_factory):
    """普通用户与上传者本人都不能自审自批。"""
    photo = photo_factory()
    for actor in (user_factory(), photo.uploader):
        api_client.force_authenticate(actor)
        url = reverse("v1:gallery:moderation-approve", kwargs={"pk": photo.pk})
        assert api_client.post(url, {}, format="json").status_code == 403
        assert api_client.get(reverse("v1:gallery:moderation-queue")).status_code == 403


def test_moderation_queue_is_401_for_guest(api_client):
    assert api_client.get(reverse("v1:gallery:moderation-queue")).status_code == 401


# --------------------------------------------------------------------------
# 模式三：举报后下架
# --------------------------------------------------------------------------


def test_mode_post_report_takes_down_immediately(
    api_client, photo_factory, user_factory, site_config
):
    """任何登录用户举报后，照片**立即** taken_down，等站主处理。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    assert photo.status == PHOTO_PUBLIC

    reporter = user_factory()
    api_client.force_authenticate(reporter)
    response = api_client.post(
        report_url(photo),
        {"reason": REASON_IN_PHOTO, "reason_text": "我在这张照片里，请下架"},
        format="json",
    )
    assert response.status_code == 201

    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN
    # 下架之后，举报人自己也看不到这张照片了
    detail = reverse("v1:gallery:photo-detail", kwargs={"pk": photo.pk})
    assert api_client.get(detail).status_code == 404


def test_owner_can_restore_or_confirm_take_down(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    reporter = user_factory()
    report = services.report_photo(reporter, photo, reason=REASON_IN_PHOTO)
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN

    api_client.force_authenticate(owner_user)
    response = api_client.post(
        handle_url(report), {"action": RESULT_RESTORED, "note": "误报"}, format="json"
    )
    assert response.status_code == 200
    photo.refresh_from_db()
    report.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC
    assert report.status == REPORT_HANDLED
    assert report.result == RESULT_RESTORED
    assert report.handled_by_id == owner_user.pk


def test_owner_confirms_take_down(api_client, photo_factory, user_factory, owner_user, site_config):
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    api_client.post(handle_url(report), {"action": RESULT_TAKEN_DOWN}, format="json")
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN


def test_dismiss_leaves_photo_untouched(api_client, photo_factory, user_factory, owner_user, site_config):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    api_client.post(handle_url(report), {"action": RESULT_DISMISSED}, format="json")
    photo.refresh_from_db()
    report.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC
    assert report.result == RESULT_DISMISSED


def test_report_cannot_be_handled_twice(api_client, photo_factory, user_factory, owner_user):
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    api_client.force_authenticate(owner_user)
    assert api_client.post(handle_url(report), {"action": RESULT_DISMISSED}, format="json").status_code == 200
    second = api_client.post(handle_url(report), {"action": RESULT_RESTORED}, format="json")
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "report_already_handled"


# --------------------------------------------------------------------------
# 举报去重与通知
# --------------------------------------------------------------------------


def test_duplicate_report_is_rejected(api_client, photo_factory, user_factory, site_config):
    """(photo, reporter) 唯一：同一个人举报第二次 → photo_already_reported。"""
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    reporter = user_factory()
    api_client.force_authenticate(reporter)
    assert api_client.post(report_url(photo), {"reason": REASON_IN_PHOTO}, format="json").status_code == 201
    second = api_client.post(report_url(photo), {"reason": REASON_IN_PHOTO}, format="json")
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "photo_already_reported"
    assert PhotoReport.objects.filter(photo=photo).count() == 1


def test_different_users_can_each_report_once(api_client, photo_factory, user_factory, site_config):
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    for _ in range(3):
        api_client.force_authenticate(user_factory())
        assert api_client.post(report_url(photo), {"reason": REASON_IN_PHOTO}, format="json").status_code == 201
    assert PhotoReport.objects.filter(photo=photo).count() == 3


def test_reporter_is_notified_without_learning_who_handled_it(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """处理结果发给举报人，`actor` 必须为空（不把站主身份送到举报人面前）。"""
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    reporter = user_factory()
    report = services.report_photo(reporter, photo, reason=REASON_IN_PHOTO)

    services.handle_report(report, by=owner_user, action=RESULT_TAKEN_DOWN, note="已确认下架")

    notification = Notification.objects.get(recipient=reporter)
    assert notification.event == events.PHOTO_REPORT_RESULT
    assert notification.actor_id is None
    assert notification.payload["result"] == RESULT_TAKEN_DOWN
    # 上传者（被举报方）不会收到任何带举报人身份的通知
    assert not Notification.objects.filter(recipient=photo.uploader).exists()


def test_my_reports_only_shows_own(api_client, photo_factory, user_factory, site_config):
    """举报人只能看自己的举报状态。"""
    set_mode(site_config, GALLERY_MODE_PUBLIC)
    photo = photo_factory()
    mine = user_factory()
    other = user_factory()
    services.report_photo(mine, photo, reason=REASON_IN_PHOTO)
    services.report_photo(other, photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(mine)
    results = api_client.get(reverse("v1:gallery:my-reports")).json()["results"]
    assert len(results) == 1
    assert results[0]["photo_id"] == photo.pk
    # 不含处理人、不含其他举报人的任何线索
    assert "handled_by" not in results[0]
    assert "reporter" not in results[0]


def test_cannot_report_invisible_photo(api_client, finished_game, gm_factory, user_factory, site_config):
    """看不见的照片（待审）举报不了 —— 404，不泄露存在性。"""
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    gm = gm_factory()
    game = finished_game(gm)
    photo = services.upload_photo(gm, game, photo_upload())

    api_client.force_authenticate(user_factory())
    assert api_client.post(report_url(photo), {"reason": REASON_IN_PHOTO}, format="json").status_code == 404
    assert PhotoReport.objects.count() == 0


def test_invalid_reason_rejected(api_client, photo_factory, user_factory):
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.post(report_url(photo), {"reason": "随便写的"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------
# W5：restored 只能从「已下架」恢复；待办队列分页
# --------------------------------------------------------------------------


def test_restored只能把已下架的照片翻回公开(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """驳回过的照片不许被一条举报「恢复」成公开，待审的也不许借此绕过审核。"""
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    photo = photo_factory()
    services.reject_photo(photo, reason="有路人正脸")
    assert photo.status == PHOTO_REJECTED
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    response = api_client.post(handle_url(report), {"action": RESULT_RESTORED}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_photo_status"
    photo.refresh_from_db()
    report.refresh_from_db()
    assert photo.status == PHOTO_REJECTED
    assert report.status == REPORT_OPEN, "处置失败却把举报标成已处理"


def test_restored对待审照片同样不生效(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    photo = photo_factory()
    assert photo.status == PHOTO_PENDING_REVIEW  # 公开前审核模式下新图就是待审
    report = services.report_photo(owner_user, photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    assert api_client.post(handle_url(report), {"action": RESULT_RESTORED}, format="json").status_code == 400
    photo.refresh_from_db()
    assert photo.status == PHOTO_PENDING_REVIEW


def test_restored对已下架照片正常生效(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    set_mode(site_config, GALLERY_MODE_POST_REPORT)
    photo = photo_factory()
    report = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    photo.refresh_from_db()
    assert photo.status == PHOTO_TAKEN_DOWN

    api_client.force_authenticate(owner_user)
    assert api_client.post(handle_url(report), {"action": RESULT_RESTORED}, format="json").status_code == 200
    photo.refresh_from_db()
    assert photo.status == PHOTO_PUBLIC
    assert photo.taken_down_reason == ""


def test_待办队列两个列表各自分页(
    api_client, finished_game, gm_factory, user_factory, owner_user, site_config
):
    set_mode(site_config, GALLERY_MODE_PRE_REVIEW)
    gm = gm_factory()
    game = finished_game(gm)
    photos = [services.upload_photo(gm, game, photo_upload()) for _ in range(3)]
    assert all(photo.status == PHOTO_PENDING_REVIEW for photo in photos)
    for photo in photos[:2]:
        services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    queue = reverse("v1:gallery:moderation-queue")
    first = api_client.get(f"{queue}?page_size=2").json()

    assert first["pending_photos"]["count"] == 3
    assert len(first["pending_photos"]["results"]) == 2
    assert first["pending_photos"]["next"] is not None
    # 举报只有 2 条，同一个 page_size 下已经一页装下
    assert first["open_reports"]["count"] == 2
    assert first["open_reports"]["next"] is None

    # 两个列表的页码互不干扰
    second = api_client.get(f"{queue}?page_size=2&photos_page=2").json()
    assert len(second["pending_photos"]["results"]) == 1
    assert len(second["open_reports"]["results"]) == 2
