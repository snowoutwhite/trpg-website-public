"""活动相册业务逻辑。视图只做鉴权与序列化，规则全写在这里。

三条主线：
1. **上传**：只有该团 GM、团已结团、且在 `finished_at + gallery_upload_window_days` 之内；
   扩展名 + 魔数双校验、≤10 MB、每团 ≤50 张、解压炸弹由 `common.images` 拦；
   处理 EXIF orientation 后重新编码成三档 WebP（EXIF/GPS/XMP 随之消失）。
2. **审核模式**（站级三选一，`siteconfig.gallery_moderation_mode`）：
   默认公开 → 上传即 `public`；公开前审核 → `pending_review`；
   举报后下架 → 上传即 `public`，任何登录用户举报后**立即** `taken_down` 待站主处理。
   切换模式**不回溯**已有照片的状态。
3. **可见性**：相册整体需登录；`public` 对登录用户可见，其余状态只有 uploader 与站主可见。
"""

from __future__ import annotations

import posixpath
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from PIL import ImageOps

from apps.gallery.models import (
    ALLOWED_EXTENSIONS,
    PERM_MODERATE,
    PHOTO_MAX_BYTES,
    PHOTO_MAX_PER_GAME,
    PHOTO_PENDING_REVIEW,
    PHOTO_PUBLIC,
    PHOTO_REJECTED,
    PHOTO_TAKEN_DOWN,
    PREVIEW_MAX_SIDE,
    QUOTA_STATUSES,
    REPORT_HANDLED,
    REPORT_OPEN,
    RESULT_DISMISSED,
    RESULT_RESTORED,
    RESULT_TAKEN_DOWN,
    THUMBNAIL_MAX_SIDE,
    WEBP_MAX_SIDE,
    Photo,
    PhotoReport,
)
from apps.notifications import events
from apps.notifications.services import notify
from apps.siteconfig.models import (
    GALLERY_MODE_POST_REPORT,
    GALLERY_MODE_PRE_REVIEW,
)
from apps.siteconfig.services import get_config
from common.exceptions import ApiError, Forbidden
from common.images import InvalidImage, open_validated_image, to_webp
from common.permissions import is_account_blocked

# --------------------------------------------------------------------------
# 错误类型（code 前端可分支）
# --------------------------------------------------------------------------
# `photo_` 前缀的三个码：
# 原先与 games 的 `not_game_gm`、reports 的 `game_not_finished` / `already_reported`
# 同码不同话，前端按 code 映射必然覆盖错一边。一个 code 只准有一个来源



class NotGameGM(Forbidden):
    default_code = "photo_not_game_gm"
    default_detail = "只有本团的 GM 才能上传本团的照片。"


class GameNotFinished(ApiError):
    default_code = "photo_game_not_finished"
    default_detail = "团结束后才能上传照片。"


class UploadWindowClosed(ApiError):
    default_code = "gallery_window_closed"
    default_detail = "本团的照片上传时间已截止。"


class PhotoQuotaExceeded(ApiError):
    default_code = "gallery_quota_exceeded"
    default_detail = f"每个团最多上传 {PHOTO_MAX_PER_GAME} 张照片。"


class AlreadyReported(ApiError):
    default_code = "photo_already_reported"
    default_detail = "你已经举报过这张照片。"


class ReportAlreadyHandled(ApiError):
    default_code = "report_already_handled"
    default_detail = "这条举报已经处理过。"


class InvalidPhotoStatus(ApiError):
    default_code = "invalid_photo_status"
    default_detail = "这张照片目前不支持此项变更。"


# --------------------------------------------------------------------------
# 权限判定
# --------------------------------------------------------------------------


def can_moderate(user) -> bool:
    """站主 / 被授予审核权限位的人。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(user.has_perm(PERM_MODERATE))


def is_game_gm(user, game) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return game.gm_id == user.pk


def can_view_photo(user, photo: Photo) -> bool:
    """相册整体需登录。

    - `public`：任意登录且账号正常的用户可见。
    - `pending_review` / `taken_down` / `rejected`：只有 uploader 与站主可见。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if is_account_blocked(user):  # 封禁/停用：与 reports 走同一个判定（common.permissions）
        return False
    if photo.status == PHOTO_PUBLIC:
        return True
    return photo.uploader_id == user.pk or can_moderate(user)


def visible_photos(user, game=None) -> QuerySet[Photo]:
    """当前用户能看到的照片查询集；游客拿到空集（视图层会先挡成 401）。"""
    queryset = Photo.objects.select_related("uploader", "game")
    if game is not None:
        queryset = queryset.filter(game=game)
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()
    if can_moderate(user):
        return queryset
    return queryset.filter(Q(status=PHOTO_PUBLIC) | Q(uploader=user))


# --------------------------------------------------------------------------
# 上传
# --------------------------------------------------------------------------


def upload_window_deadline(game):
    """结团时间 + 站点配置的上传窗口天数；团没有 finished_at 时返回 None。"""
    if not game.finished_at:
        return None
    return game.finished_at + timedelta(days=get_config().gallery_upload_window_days)


def assert_can_upload(user, game, *, now=None) -> None:
    """上传前的三道闸：本团 GM → 团已结团 → 还在窗口内。"""
    from apps.games.models import GAME_FINISHED

    if not is_game_gm(user, game):
        raise NotGameGM()
    if game.status != GAME_FINISHED or not game.finished_at:
        raise GameNotFinished()
    now = now or timezone.now()
    deadline = upload_window_deadline(game)
    if deadline is None or now > deadline:
        raise UploadWindowClosed()
    used = Photo.objects.filter(game=game, status__in=QUOTA_STATUSES).count()
    if used >= PHOTO_MAX_PER_GAME:
        raise PhotoQuotaExceeded()


def initial_status() -> str:
    """按站级审核模式决定新照片的初始状态。

    「举报后下架」模式下上传即公开（下架发生在有人举报之后），与「默认公开」一致。
    """
    if get_config().gallery_moderation_mode == GALLERY_MODE_PRE_REVIEW:
        return PHOTO_PENDING_REVIEW
    return PHOTO_PUBLIC


def validate_extension(uploaded_file) -> None:
    """扩展名白名单。

    真正说了算的是魔数（`open_validated_image`），但写的是
    「jpg/png/webp」，扩展名这一层先挡一道，省得把 `.gif` 改名成 `.jpg` 的人
    走到解码环节才知道被拒。**扩展名对了魔数不对照样拒**，反之亦然。
    """
    name = getattr(uploaded_file, "name", "") or ""
    extension = posixpath.splitext(name)[1].lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise InvalidImage("相册仅支持 jpg、png、webp 格式的图片。")


def _encode_tiers(uploaded_file):
    """校验 → 摆正方向 → 重新编码出三档无元数据 WebP。"""
    image = open_validated_image(uploaded_file, max_bytes=PHOTO_MAX_BYTES)
    image = ImageOps.exif_transpose(image) or image

    # 5. 「原图」档以 WebP 的硬上限封顶：超宽全景图（16384×1000 只有 50 KB、
    #    1638 万像素，体积闸与像素闸都拦不住）会让 libwebp 抛 ValueError，
    #    那不是 ApiError 也不是 OSError，直接变成 500。
    longest = min(max(image.size), WEBP_MAX_SIDE)
    original_bytes = to_webp(image, max_side=longest, quality=90)
    preview_bytes = to_webp(image, max_side=min(PREVIEW_MAX_SIDE, longest), quality=85)
    thumb_bytes = to_webp(image, max_side=min(THUMBNAIL_MAX_SIDE, longest), quality=80)
    return image, original_bytes, preview_bytes, thumb_bytes


@transaction.atomic
def upload_photo(user, game, uploaded_file, *, caption: str = "", now=None) -> Photo:
    """GM 上传一张活动照片。"""
    assert_can_upload(user, game, now=now)
    validate_extension(uploaded_file)

    image, original_bytes, preview_bytes, thumb_bytes = _encode_tiers(uploaded_file)

    # 配额是「先数后插」：第一次计数发生在三档编码**之前**，两者之间隔着几十毫秒，
    # 同一个 GM 连点上传就能让两个请求都数到 49 然后都插进去（W3 红队，用例
    # `test_quota_cannot_be_overshot_by_a_second_upload_landing_mid_encode`）。
    # 进事务后锁住团这一行再数一次，把窗口收到一次数据库往返之内。
    # SQLite 没有行锁，`select_for_update()` 会被编译器静默忽略（写本来就是串行的）。
    type(game).objects.select_for_update().filter(pk=game.pk).first()
    used = Photo.objects.filter(game=game, status__in=QUOTA_STATUSES).count()
    if used >= PHOTO_MAX_PER_GAME:
        raise PhotoQuotaExceeded()

    photo = Photo(
        game=game,
        uploader=user,
        width=image.width,
        height=image.height,
        size=len(original_bytes),
        status=initial_status(),
        caption=(caption or "").strip()[:200],
    )
    # 先落一次库拿到 pk，再存文件（upload_to 不依赖 pk，但保存文件会写库）。
    photo.original.save("original.webp", ContentFile(original_bytes), save=False)
    photo.preview.save("preview.webp", ContentFile(preview_bytes), save=False)
    photo.thumbnail.save("thumb.webp", ContentFile(thumb_bytes), save=False)
    photo.save()
    return photo


def delete_photo(photo: Photo) -> None:
    """删照片：连同三档文件一起清掉。调用方（视图）负责判断「谁能删」。"""
    files = list(photo.stored_files())
    photo.delete()
    for field in files:
        try:
            field.storage.delete(field.name)
        except Exception:  # pragma: no cover - 存储层异常不该拖垮删除动作
            pass


# --------------------------------------------------------------------------
# 站主审核（公开前审核模式）
# --------------------------------------------------------------------------


def approve_photo(photo: Photo) -> Photo:
    """审核通过 → public。"""
    if photo.status not in (PHOTO_PENDING_REVIEW, PHOTO_TAKEN_DOWN):
        raise InvalidPhotoStatus()
    photo.status = PHOTO_PUBLIC
    photo.taken_down_reason = ""
    photo.save(update_fields=["status", "taken_down_reason", "updated_at"])
    return photo


def reject_photo(photo: Photo, *, reason: str = "") -> Photo:
    """审核驳回 → rejected（不再占每团 50 张配额）。"""
    if photo.status not in (PHOTO_PENDING_REVIEW, PHOTO_TAKEN_DOWN):
        raise InvalidPhotoStatus()
    photo.status = PHOTO_REJECTED
    photo.taken_down_reason = (reason or "").strip()
    photo.is_featured = False
    photo.save(update_fields=["status", "taken_down_reason", "is_featured", "updated_at"])
    return photo


def take_down_photo(photo: Photo, *, reason: str = "") -> Photo:
    """下架 → taken_down，**顺手撤掉首页精选**。"""
    photo.status = PHOTO_TAKEN_DOWN
    photo.taken_down_reason = (reason or "").strip()
    photo.is_featured = False
    photo.save(update_fields=["status", "taken_down_reason", "is_featured", "updated_at"])
    return photo


def pending_moderation_queue() -> QuerySet[Photo]:
    return Photo.objects.filter(status=PHOTO_PENDING_REVIEW).select_related("uploader", "game")


def open_reports_queue() -> QuerySet[PhotoReport]:
    return PhotoReport.objects.filter(status=REPORT_OPEN).select_related("photo", "reporter")


# --------------------------------------------------------------------------
# 举报 / 下架诉求
# --------------------------------------------------------------------------


@transaction.atomic
def report_photo(user, photo: Photo, *, reason: str, reason_text: str = "") -> PhotoReport:
    """任何**登录**用户都能提。

    「举报后下架」模式：立刻把照片置为 `taken_down`，站主事后决定恢复还是确认下架。
    另外两种模式：只落一条待处理举报，照片状态不动（站级三选项的字面口径）。
    """
    try:
        report = PhotoReport.objects.create(
            photo=photo,
            reporter=user,
            reason=reason,
            reason_text=(reason_text or "").strip(),
        )
    except IntegrityError as exc:  # (photo, reporter) 在 open 状态下唯一
        # 只拦「上一条还没处理」的重复举报；站主处理完（含 restored）之后
        # 同一个人可以再提一次，下架入口不会永久关闭。
        raise AlreadyReported("你对这张照片的上一条举报还在处理中。") from exc

    if get_config().gallery_moderation_mode == GALLERY_MODE_POST_REPORT:
        if photo.status == PHOTO_PUBLIC:
            take_down_photo(photo, reason="收到举报，已自动下架待站主处理")
    return report


# 举报处置结果的默认说明文案（站主没写备注时用这个）。
_RESULT_MESSAGES = {
    RESULT_RESTORED: "站主复核后恢复了该照片的展示",
    RESULT_TAKEN_DOWN: "站主已确认下架该照片",
    RESULT_DISMISSED: "站主复核后认为无需处理",
}


@transaction.atomic
def handle_report(report: PhotoReport, *, by, action: str, note: str = "") -> PhotoReport:
    """站主处理举报：恢复展示 / 确认下架 / 不予处理。"""
    if report.status == REPORT_HANDLED:
        raise ReportAlreadyHandled()

    photo = report.photo
    if action == RESULT_RESTORED:
        # **只能从「已下架」恢复**（W5）。原实现无条件把照片置为 public，于是
        # 「处理一条挂在待审照片上的举报」能让照片绕过公开前审核直接上墙，
        # 「处理一条挂在已驳回照片上的举报」能把站主驳回过的照片翻回公开。
        # 举报挂在还在公开的照片上时，对应的动作是 `dismissed` 而不是 `restored`。
        if photo.status != PHOTO_TAKEN_DOWN:
            raise InvalidPhotoStatus("只有已下架的照片才能恢复展示。")
        photo.status = PHOTO_PUBLIC
        photo.taken_down_reason = ""
        photo.save(update_fields=["status", "taken_down_reason", "updated_at"])
    elif action == RESULT_TAKEN_DOWN:
        # `note` 是**写给举报人**的说明（字段名就是 result_note），站主很自然会在里面
        # 写「XX 本人要求下架」。它绝不能顺手写进 `taken_down_reason` —— 那一栏是

        # 红线②；W3 红队，用例 `test_uploader_cannot_learn_who_reported_through_the_moderator_note`）。
        take_down_photo(photo, reason="站主确认下架")
    elif action == RESULT_DISMISSED:
        pass
    else:
        raise InvalidPhotoStatus("无法识别该操作。")

    report.status = REPORT_HANDLED
    report.handled_by = by
    report.handled_at = timezone.now()
    report.result = action
    report.result_note = (note or "").strip()
    report.save(
        update_fields=["status", "handled_by", "handled_at", "result", "result_note", "updated_at"]
    )

    notify(
        report.reporter,
        events.PHOTO_REPORT_RESULT,
        actor=None,
        target=photo,
        payload={
            "result": action,
            "photo_id": photo.pk,
            "game_id": photo.game_id,
            "message": report.result_note or _RESULT_MESSAGES.get(action, ""),
        },
    )
    return report


def my_reports(user) -> QuerySet[PhotoReport]:
    """举报人只能看自己的举报状态。"""
    return PhotoReport.objects.filter(reporter=user).select_related("photo")
