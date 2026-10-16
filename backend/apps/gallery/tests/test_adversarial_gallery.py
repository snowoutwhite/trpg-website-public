"""相册的对抗性用例：越权、绕过、注入、直链泄露。

纪律（安全测试规则）：先写会失败的测试，能复现问题才算发现；
「跑了一下没报错」不算通过。本文件只放「试图把它弄坏」的路径。
"""

from __future__ import annotations

import json

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.gallery import services
from apps.gallery.models import PHOTO_PUBLIC, REASON_IN_PHOTO, Photo, PhotoReport
from apps.games.models import GAME_CANCELLED
from apps.siteconfig.models import GALLERY_MODE_POST_REPORT, GALLERY_MODE_PRE_REVIEW

from .conftest import make_image_bytes, photo_upload

pytestmark = pytest.mark.django_db


def file_url(photo, size="original") -> str:
    return reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk}) + f"?size={size}"


# --------------------------------------------------------------------------
# 越权
# --------------------------------------------------------------------------


def test_staff_without_permission_bit_cannot_moderate(api_client, photo_factory, user_factory):
    """`is_staff` 不等于有审核权。本 app 只认 `gallery.moderate_photo` 权限位。"""
    photo = photo_factory()
    staff = user_factory()
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])

    api_client.force_authenticate(staff)
    url = reverse("v1:gallery:moderation-approve", kwargs={"pk": photo.pk})
    assert api_client.post(url, {}, format="json").status_code == 403


def test_superuser_works_without_any_is_superuser_branch(api_client, photo_factory, user_factory, site_config):
    """站主（超级管理员）开箱即用 —— `has_perm()` 对超管恒为真，不需要代码里写分支。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.save()
    photo_factory()
    root = user_factory()
    root.is_superuser = True
    root.is_staff = True
    root.save(update_fields=["is_superuser", "is_staff"])

    api_client.force_authenticate(root)
    assert api_client.get(reverse("v1:gallery:moderation-queue")).status_code == 200


def test_no_is_superuser_branch_in_source():
    """业务规则与安全约束。"""
    import ast
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parent.parent
    for path in app_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        hits = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "is_superuser"
        ]
        assert not hits, f"{path} 第 {hits[0].lineno} 行读了 is_superuser"


def test_photo_of_another_game_not_listed(api_client, photo_factory, finished_game, user_factory):
    """A 团的照片不会出现在 B 团的相册里。"""
    photo_factory()
    other_game = finished_game()
    api_client.force_authenticate(user_factory())
    url = reverse("v1:gallery:game-photos", kwargs={"game_id": other_game.pk})
    assert api_client.get(url).json()["results"] == []


def test_cannot_upload_to_cancelled_game(api_client, finished_game, gm_factory):
    """取消的团不算「成功的团」，不该有活动相册。"""
    gm = gm_factory()
    game = finished_game(gm)
    game.status = GAME_CANCELLED
    game.save(update_fields=["status"])

    api_client.force_authenticate(gm)
    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload()},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "photo_game_not_finished"
    assert Photo.objects.count() == 0


def test_banned_user_cannot_report(api_client, photo_factory, user_factory):
    photo = photo_factory()
    banned = user_factory()
    banned.is_banned = True
    banned.save(update_fields=["is_banned"])
    api_client.force_authenticate(banned)
    url = reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk})
    assert api_client.post(url, {"reason": REASON_IN_PHOTO}, format="json").status_code == 403
    assert PhotoReport.objects.count() == 0


def test_uploader_cannot_delete_someone_elses_photo(api_client, photo_factory, gm_factory):
    """另一个 GM 删不掉别人团的照片，而且拿到 404。"""
    photo = photo_factory()
    api_client.force_authenticate(gm_factory())
    url = reverse("v1:gallery:photo-detail", kwargs={"pk": photo.pk})
    assert api_client.delete(url).status_code == 404
    assert Photo.objects.filter(pk=photo.pk).exists()


# --------------------------------------------------------------------------
# 直链与文件下发
# --------------------------------------------------------------------------


def test_gallery_files_are_not_reachable_through_debug_media():
    """开发期 `static()` 会直出整个 MEDIA_ROOT —— 相册的 `protected/` 路径必须先被堵死。

    这个用例**是可证伪的**：它同时断言两件事 ——
    1. `/media/protected/gallery/x.webp` 解析到 `deny_protected_media`；
    2. `/media/avatars/x.webp`（非受保护）解析到 Django 的 `static.serve`。
    第 2 条保证 `static()` 确实挂上了；少了它，「第 1 条通过」也可能只是因为
    DEBUG 分支整个没生效、这条路由压根不存在（404 看起来一样，但什么都没证明）。
    """
    import importlib

    from django.test import override_settings
    from django.urls import clear_url_caches, resolve
    from django.views.static import serve

    import config.urls as config_urls
    from common.views import deny_protected_media

    try:
        with override_settings(DEBUG=True):
            clear_url_caches()
            module = importlib.reload(config_urls)
            assert (
                resolve("/media/protected/gallery/deadbeef-original.webp", urlconf=module).func
                is deny_protected_media
            )
            assert resolve("/media/avatars/deadbeef.webp", urlconf=module).func is serve
    finally:
        clear_url_caches()
        importlib.reload(config_urls)


def test_x_accel_redirect_stays_inside_protected_prefix(
    api_client, photo_factory, user_factory, settings
):
    """生产模式下 Nginx internal 重定向目标必须落在受保护前缀内，且不带 `..`。"""
    settings.USE_X_ACCEL_REDIRECT = True
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.get(file_url(photo, "preview"))
    assert response.status_code == 200
    target = response["X-Accel-Redirect"]
    assert target.startswith(settings.X_ACCEL_REDIRECT_PREFIX)
    assert ".." not in target
    assert response.content == b""  # 字节由 Nginx 发，Django 不读盘


def test_file_response_never_uses_user_supplied_name(api_client, photo_factory, user_factory):
    """下发名由服务端生成，用户的原始文件名（可能带引号/换行/HTML）到不了响应头。"""
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    disposition = api_client.get(file_url(photo, "thumb"))["Content-Disposition"]
    assert f"photo-{photo.pk}-thumb.webp" in disposition
    assert "\n" not in disposition and "\r" not in disposition


def test_size_param_cannot_reach_arbitrary_attribute(api_client, photo_factory, user_factory):
    """`?size=` 只认三个白名单值；传模型上的别的属性名不会被当成文件字段。"""
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    for evil in ("uploader", "game", "__class__", "caption", ""):
        url = reverse("v1:gallery:photo-file", kwargs={"pk": photo.pk}) + f"?size={evil}"
        response = api_client.get(url)
        assert response.status_code == 200
        with photo.thumbnail.open("rb") as handle:
            assert b"".join(response.streaming_content) == handle.read()


# --------------------------------------------------------------------------
# 输入注入
# --------------------------------------------------------------------------


def test_xss_payload_in_caption_is_data_not_markup(api_client, finished_game, gm_factory, user_factory):
    """图注里的 XSS 载荷原样入库、以 JSON 字符串回显，响应类型不是 HTML。"""
    gm = gm_factory()
    game = finished_game(gm)
    payload = "<script>alert(document.cookie)</script>"
    api_client.force_authenticate(gm)
    created = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload(), "caption": payload},
        format="multipart",
    )
    assert created.status_code == 201

    api_client.force_authenticate(user_factory())
    response = api_client.get(reverse("v1:gallery:photo-detail", kwargs={"pk": created.json()["id"]}))
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["caption"] == payload


def test_caption_length_is_capped(api_client, finished_game, gm_factory):
    """业务规则与安全约束。"""
    gm = gm_factory()
    game = finished_game(gm)
    api_client.force_authenticate(gm)
    response = api_client.post(
        reverse("v1:gallery:game-photos", kwargs={"game_id": game.pk}),
        {"file": photo_upload(), "caption": "啊" * 5000},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_report_text_length_is_capped(api_client, photo_factory, user_factory):
    photo = photo_factory()
    api_client.force_authenticate(user_factory())
    response = api_client.post(
        reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk}),
        {"reason": REASON_IN_PHOTO, "reason_text": "啊" * 50000},
        format="json",
    )
    assert response.status_code == 400


def test_csrf_is_enforced_on_writes(photo_factory, user_factory):
    """写接口必须过 CSRF —— 会话认证下少了它就是站外提交。"""
    photo = photo_factory()
    client = APIClient(enforce_csrf_checks=True)
    user = user_factory()
    client.force_login(user)  # 走真实会话，不是 force_authenticate
    response = client.post(
        reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk}),
        {"reason": REASON_IN_PHOTO},
        format="json",
    )
    assert response.status_code == 403
    assert PhotoReport.objects.count() == 0


# --------------------------------------------------------------------------
# 举报后下架的绕过尝试
# --------------------------------------------------------------------------


def test_taken_down_photo_bytes_are_not_reachable(
    api_client, photo_factory, user_factory, site_config
):
    """下架之后三档文件全部拿不到 —— 只藏列表、不挡字节等于没下架。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_POST_REPORT
    site_config.save()
    photo = photo_factory()
    services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    photo.refresh_from_db()

    stranger = user_factory()
    api_client.force_authenticate(stranger)
    for size in ("thumb", "preview", "original"):
        assert api_client.get(file_url(photo, size)).status_code == 404


def test_report_after_take_down_does_not_reset_state(
    api_client, photo_factory, user_factory, owner_user, site_config
):
    """站主确认下架后，又来一个人举报，不能把状态搅回 public。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_POST_REPORT
    site_config.save()
    photo = photo_factory()
    first = services.report_photo(user_factory(), photo, reason=REASON_IN_PHOTO)
    services.handle_report(first, by=owner_user, action="taken_down")
    photo.refresh_from_db()

    # 第二个人已经看不到这张照片了，自然也举报不了
    second = user_factory()
    api_client.force_authenticate(second)
    url = reverse("v1:gallery:photo-report", kwargs={"pk": photo.pk})
    assert api_client.post(url, {"reason": REASON_IN_PHOTO}, format="json").status_code == 404
    photo.refresh_from_db()
    assert photo.status != PHOTO_PUBLIC


def test_quota_counts_taken_down_photos(finished_game, gm_factory, site_config):
    """已下架的照片仍占配额：否则「传 50 张 → 全被举报下架 → 再传 50 张」可以无限循环。"""
    from apps.gallery.models import PHOTO_MAX_PER_GAME

    gm = gm_factory()
    game = finished_game(gm)
    tiny = make_image_bytes(size=(4, 4))
    for _ in range(PHOTO_MAX_PER_GAME):
        photo = services.upload_photo(gm, game, photo_upload(data=tiny))
        services.take_down_photo(photo, reason="举报")

    with pytest.raises(services.PhotoQuotaExceeded):
        services.assert_can_upload(gm, game)


def test_moderation_queue_does_not_leak_emails(api_client, photo_factory, user_factory, owner_user, site_config):
    """站主待办里出现的用户一律是公开表示，不含邮箱。"""
    site_config.gallery_moderation_mode = GALLERY_MODE_PRE_REVIEW
    site_config.save()
    photo = photo_factory()
    reporter = user_factory(email="secret@example.com")
    services.report_photo(reporter, photo, reason=REASON_IN_PHOTO)

    api_client.force_authenticate(owner_user)
    body = json.dumps(api_client.get(reverse("v1:gallery:moderation-queue")).json(), ensure_ascii=False)
    assert "secret@example.com" not in body
    assert "protected" not in body
