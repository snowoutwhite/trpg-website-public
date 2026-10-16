"""站长内容业务逻辑。视图只做鉴权与序列化，规则全写在这里。

四条主线：
1. **图片**：站长内容图与相册走同一套 `common.images`（魔数 + 解压炸弹闸 + EXIF 剥离），
   只是存公开目录、多认一种 AVIF 输入、输出恒为 WebP。
2. **规则预设同步**：`RuleSystemPreset` 表是真源，写完同步进
   `SiteConfig.rule_system_presets` 这面只读镜像（signals.py 挂的 post_save/post_delete）。
3. **公告推送**：一条公告只推一次（`notified_at` 幂等锚），收件人 = 全站活跃用户；
   预告（`published_at` 在未来）到点后由 `publish_due_announcements()` 补推。
4. **精选照片可见性**：站级开关 + 可见范围 + 登录态三者共同决定给不给。
"""

from __future__ import annotations

import posixpath

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from PIL import ImageOps, features

from apps.gallery.models import PHOTO_PUBLIC, Photo
from apps.homecontent.models import (
    ALLOWED_EXTENSIONS,
    CARD_MAX_SIDE,
    FULL_MAX_SIDE,
    QUICK_IMAGE_MAX_SIDE,
    SITE_IMAGE_MAX_BYTES,
    THUMB_MAX_SIDE,
    QuickEntry,
    RuleSystemPreset,
    SiteAnnouncement,
)
from apps.notifications import events
from apps.notifications.services import notify_many
from apps.siteconfig.models import FEATURED_PHOTOS_PUBLIC, SiteConfig
from apps.siteconfig.services import clear_config_cache, get_config
from common.exceptions import ApiError
from common.images import ALLOWED_IMAGE_FORMATS, InvalidImage, open_validated_image, webp_content_file

# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------


def allowed_image_formats() -> tuple[str, ...]:
    """魔数白名单。AVIF 只在本机 Pillow 真的编进了 libavif 时才认。

    Pillow 12.3.0 的官方 wheel 自带 AVIF 解码，但源码安装 / 精简镜像可能没有；
    无条件把 "AVIF" 写进白名单的后果是：校验放行 → `Image.open` 抛
    `UnidentifiedImageError` → 被 `open_validated_image` 翻译成 invalid_image，
    错误信息与实际原因对不上。用 `features.check("avif")` 现场问一次最诚实。
    """
    if features.check("avif"):
        return (*ALLOWED_IMAGE_FORMATS, "AVIF")
    return ALLOWED_IMAGE_FORMATS


def validate_extension(uploaded_file) -> None:
    """扩展名白名单（jpg / png / webp / avif）。

    真正说了算的是魔数；扩展名只是先挡一道，省得把 `.gif` 改名成 `.jpg` 的人
    走到解码环节才知道被拒。**扩展名对了魔数不对照样拒**，反之亦然。
    """
    name = getattr(uploaded_file, "name", "") or ""
    extension = posixpath.splitext(name)[1].lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise InvalidImage("站长内容图只接受 jpg / png / webp / avif")


def _open_site_image(uploaded_file):
    """校验 → 摆正方向。顺序与相册一致：先落实 EXIF orientation，再重编码剥元数据。"""
    validate_extension(uploaded_file)
    image = open_validated_image(
        uploaded_file,
        max_bytes=SITE_IMAGE_MAX_BYTES,
        allowed_formats=allowed_image_formats(),
    )
    return ImageOps.exif_transpose(image) or image


def _replace_image(instance, field_name: str, content) -> None:
    """换图时把旧文件删掉，别在磁盘上留孤儿（与 `accounts.services.set_avatar` 同一套）。"""
    field = getattr(instance, field_name)
    old = field.name if field else ""
    field.save(content.name, content, save=False)
    if old and old != getattr(instance, field_name).name:
        try:
            field.storage.delete(old)
        except Exception:  # pragma: no cover - 存储层异常不该拖垮上传
            pass


@transaction.atomic
def set_preset_image(preset: RuleSystemPreset, uploaded_file) -> RuleSystemPreset:
    """规则预设配图：一次生成 full / card / thumb 三档无元数据 WebP。"""
    image = _open_site_image(uploaded_file)
    # 不放大：原图比某一档还小时就按原图最长边封顶，免得糊成马赛克。
    longest = max(image.size)
    _replace_image(
        preset, "image_full", webp_content_file(image, max_side=min(FULL_MAX_SIDE, longest), name="full.webp")
    )
    _replace_image(
        preset, "image_card", webp_content_file(image, max_side=min(CARD_MAX_SIDE, longest), name="card.webp")
    )
    _replace_image(
        preset, "image_thumb", webp_content_file(image, max_side=min(THUMB_MAX_SIDE, longest), name="thumb.webp")
    )
    preset.save(update_fields=["image_full", "image_card", "image_thumb", "updated_at"])
    return preset


@transaction.atomic
def set_quick_entry_image(entry: QuickEntry, uploaded_file) -> QuickEntry:
    """快速选择配图：版面里最大就是卡片尺寸，只存一档。"""
    image = _open_site_image(uploaded_file)
    longest = max(image.size)
    _replace_image(
        entry,
        "image",
        webp_content_file(image, max_side=min(QUICK_IMAGE_MAX_SIDE, longest), name="quick.webp"),
    )
    entry.save(update_fields=["image", "updated_at"])
    return entry


def delete_stored_images(instance) -> None:
    """删记录时顺手清文件。"""
    fields = (
        instance.stored_images()
        if hasattr(instance, "stored_images")
        else ([instance.image] if getattr(instance, "image", None) else [])
    )
    for field in fields:
        try:
            field.storage.delete(field.name)
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------
# 规则预设 ↔ SiteConfig.rule_system_presets 镜像
# --------------------------------------------------------------------------


def sync_rule_system_presets() -> list[str]:
    """把预设表同步进 `SiteConfig.rule_system_presets` 那面只读镜像。

    只在真的不一样时才写库（signals 里每保存一条预设都会调用这里，
    无脑 save 会让单例的 `updated_at` 跟着抖，还会连带清一次缓存）。

    **镜像按大小写不敏感去重**：前端拿这份列表画筛选条，同时出现 `DND` 与 `dnd`
    就是两个等价筹码。表上已经有 `UniqueConstraint(Lower("name"))` 挡着，这里是
    给历史脏数据（约束上线前写进去的行）留的兜底，去重时保留排在前面的那条。
    空白名字不参与去重（`"   "` 与 `"\t"` 在 DB 约束里本来就是两条不同的行），
    它们在 `preset_rule_systems()` 里另有过滤。
    """
    names: list[str] = []
    seen: set[str] = set()
    for name in RuleSystemPreset.objects.order_by("sort", "id").values_list("name", flat=True):
        key = (name or "").strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        names.append(name)
    config = SiteConfig.objects.filter(pk=SiteConfig.SINGLETON_PK).first()
    if config is None:
        config = get_config()
    if list(config.rule_system_presets or []) == names:
        return names
    config.rule_system_presets = names
    config.save(update_fields=["rule_system_presets", "updated_at"])
    clear_config_cache()
    return names


# --------------------------------------------------------------------------
# 站长公告
# --------------------------------------------------------------------------


def active_announcements(*, now=None) -> QuerySet[SiteAnnouncement]:
    """公开列表：生效中 + 已到发布时间。未来时间的公告是预告，不外露。"""
    now = now or timezone.now()
    return SiteAnnouncement.objects.filter(is_active=True, published_at__lte=now).select_related(
        "author"
    )


def latest_announcement(*, now=None) -> SiteAnnouncement | None:
    return active_announcements(now=now).first()


def announcement_recipients():
    """全站活跃用户：能登录、没被封、没注销。"""
    from apps.accounts.models import User

    return User.objects.filter(is_active=True, is_banned=False, is_deactivated=False)


@transaction.atomic
def publish_announcement(announcement: SiteAnnouncement, *, now=None) -> int:
    """公告生效时给全站活跃用户各推一条 `site_announcement`。返回本次推送人数。

    **幂等**：`notified_at` 一旦落下就再不推第二遍。反复保存、来回切 `is_active`、
    后台批量动作、两个站主同时点保存 —— 都只会有一轮通知。
    并发那一路靠 `select_for_update()` 锁住这一行，不是靠「先查再写」。
    """
    now = now or timezone.now()
    locked = (
        SiteAnnouncement.objects.select_for_update().filter(pk=announcement.pk).first()
    )
    if locked is None:
        return 0
    if locked.notified_at is not None:
        return 0
    if not locked.is_active or locked.published_at > now:
        return 0

    count = notify_many(
        announcement_recipients(),
        events.SITE_ANNOUNCEMENT,
        actor=None,
        target=locked,
        payload={"announcement_id": locked.pk, "title": locked.title, "message": locked.body},
    )
    locked.notified_at = now
    locked.notified_count = count
    locked.save(update_fields=["notified_at", "notified_count", "updated_at"])
    announcement.notified_at = locked.notified_at
    announcement.notified_count = count
    return count


def publish_due_announcements(*, now=None) -> int:
    """把「已到发布时间但一轮都没推过」的公告补推掉，返回补推了几条。"""
    now = now or timezone.now()
    pending = SiteAnnouncement.objects.filter(
        is_active=True, published_at__lte=now, notified_at__isnull=True
    ).order_by("published_at", "id")
    published = 0
    for announcement in pending:
        publish_announcement(announcement, now=now)
        if announcement.notified_at is not None:
            published += 1
    return published


def announcement_notification_for(user, announcement: SiteAnnouncement):
    """当前用户收到的那条公告通知（用来回「是否已读」与给前端标已读的 id）。"""
    if announcement is None or not getattr(user, "is_authenticated", False):
        return None
    from django.contrib.contenttypes.models import ContentType

    from apps.notifications.models import Notification

    content_type = ContentType.objects.get_for_model(SiteAnnouncement)
    return (
        Notification.objects.filter(
            recipient=user,
            event=events.SITE_ANNOUNCEMENT,
            target_content_type=content_type,
            target_object_id=announcement.pk,
        )
        .only("id", "read_at")
        .first()
    )


# --------------------------------------------------------------------------
# 精选活动照片
# --------------------------------------------------------------------------


class PhotoNotPublic(ApiError):
    default_code = "photo_not_public"
    default_detail = "只有已公开的照片能设为首页精选。"


def featured_photos() -> QuerySet[Photo]:
    """精选池：必须同时是「精选」与「已公开」。两个条件缺一不可。"""
    return (
        Photo.objects.filter(is_featured=True, status=PHOTO_PUBLIC)
        .select_related("game")
        .order_by("-created_at", "-id")
    )


def can_see_featured_photos(user) -> bool:
    """站级开关 + 可见范围 + 登录态。

    相册整体是「需登录」的，所以默认 `members`；
    站主显式选 `public` 才对这一小撮照片开游客的口子。
    """
    config = get_config()
    if not config.featured_photos_enabled:
        return False
    if config.featured_photos_visibility == FEATURED_PHOTOS_PUBLIC:
        return True
    user_ok = (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not getattr(user, "is_banned", False)
    )
    return bool(user_ok)


def set_photo_featured(photo: Photo, featured: bool) -> Photo:
    """站主勾选/取消精选。**只有 `status=public` 的照片能被勾上**。"""
    featured = bool(featured)
    if featured and photo.status != PHOTO_PUBLIC:
        raise PhotoNotPublic()
    if photo.is_featured == featured:
        return photo
    photo.is_featured = featured
    photo.save(update_fields=["is_featured", "updated_at"])
    return photo
