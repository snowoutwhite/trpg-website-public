"""账号域业务逻辑。视图只负责鉴权与序列化，规则全部落在这里。"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    ANONYMIZED_NICKNAME_PREFIX,
    GMApplication,
    NicknameHistory,
    User,
)
from apps.siteconfig.services import get_config
from common.exceptions import ApiError

# 昵称冷却期：30 天改一次
NICKNAME_CHANGE_INTERVAL = timedelta(days=30)


class NicknameTooSoon(ApiError):
    default_code = "nickname_change_too_soon"
    default_detail = "昵称每 30 天只能修改一次。"


class NicknameTaken(ApiError):
    default_code = "nickname_taken"
    default_detail = "该昵称已被占用。"


class AlreadyGM(ApiError):
    default_code = "already_gm"
    default_detail = "你已经是 GM，无需重复申请。"


class DuplicateGMApplication(ApiError):
    default_code = "duplicate_gm_application"
    default_detail = "你已有一份 GM 申请正在等待站主审核。"


def nickname_change_available_at(user: User):
    """返回下一次可改昵称的时间；从未改过则返回 None（表示随时可改）。"""
    if user.nickname_changed_at is None:
        return None
    return user.nickname_changed_at + NICKNAME_CHANGE_INTERVAL


class InvalidNickname(ApiError):
    default_code = "invalid_nickname"
    default_detail = "这个昵称不符合规范。"


@transaction.atomic
def change_nickname(user: User, new_nickname: str) -> User:
    """改昵称：归一化 + 唯一性 + 30 天冷却 + 留痕。

    归一化与注册表单共用 `validators.normalize_nickname`，两条路径规则必须一致。
    """
    from django.core.exceptions import ValidationError as DjangoValidationError

    from apps.accounts.validators import normalize_nickname

    try:
        new_nickname = normalize_nickname(new_nickname)
    except DjangoValidationError as exc:
        raise InvalidNickname("；".join(exc.messages)) from exc
    if new_nickname == user.nickname:
        return user

    available_at = nickname_change_available_at(user)
    if available_at and timezone.now() < available_at:
        raise NicknameTooSoon(
            f"昵称每 30 天只能修改一次，"
            f"下次可修改时间为 {timezone.localtime(available_at):%Y-%m-%d %H:%M}。"
        )
    if User.objects.filter(nickname__iexact=new_nickname).exclude(pk=user.pk).exists():
        raise NicknameTaken()

    old = user.nickname
    user.nickname = new_nickname
    user.nickname_changed_at = timezone.now()
    user.save(update_fields=["nickname", "nickname_changed_at"])
    NicknameHistory.objects.create(user=user, old_nickname=old, new_nickname=new_nickname)
    return user


def apply_for_gm(user: User, reason: str) -> GMApplication:
    """提交 GM 申请。只需理由，由站主在后台审批。"""
    if user.is_gm:
        raise AlreadyGM()
    if GMApplication.objects.filter(
        applicant=user, status=GMApplication.STATUS_PENDING
    ).exists():
        raise DuplicateGMApplication()
    reason = (reason or "").strip()
    if not reason:
        raise ApiError("请填写申请理由，供站主审核参考。", code="invalid_reason")
    return GMApplication.objects.create(applicant=user, reason=reason)


@transaction.atomic
def review_gm_application(
    application: GMApplication, *, approved: bool, reviewer: User | None, note: str = ""
) -> GMApplication:
    """站主审批 GM 申请（后台动作调用）。"""
    application.status = (
        GMApplication.STATUS_APPROVED if approved else GMApplication.STATUS_REJECTED
    )
    application.reviewer = reviewer
    application.reviewed_at = timezone.now()
    application.review_note = note
    application.save(update_fields=["status", "reviewer", "reviewed_at", "review_note", "updated_at"])

    if approved:
        grant_gm(application.applicant)

    from apps.notifications import events
    from apps.notifications.services import notify

    # actor 故意留空：审批人是站主，申请人没有知道「是哪个管理员批的」的必要。
    # 序列化器 GMApplicationSerializer 已经不回传 reviewer，通知这一路也必须对齐，
    # 否则 PublicUserSerializer 会把站主的 id / 昵称 / 头像送到申请人面前。
    notify(
        application.applicant,
        events.GM_APPLICATION_RESULT,
        target=application,
        payload={"approved": approved, "note": note},
    )
    return application


def grant_gm(user: User) -> User:
    """授予 GM 身份并确保 GM 卡存在。幂等。"""
    if not user.is_gm:
        user.is_gm = True
        user.save(update_fields=["is_gm"])
    from apps.profiles.services import ensure_gm_card

    ensure_gm_card(user)
    return user


def maybe_promote_gm(user: User, *, games_played: int | None = None) -> bool:
    """作为 PL 被成功结团达到阈值时自动晋升 GM。

    `games` app 在结团流程里调用本函数；阈值读站点配置（默认 3）。
    返回 True 表示本次发生了晋升。
    """
    if user.is_gm or not user.is_active or user.is_banned:
        return False

    if games_played is None:
        from apps.profiles.services import ensure_player_card

        games_played = ensure_player_card(user).games_played

    threshold = get_config().gm_auto_promote_threshold
    if games_played < threshold:
        return False

    grant_gm(user)

    from apps.notifications import events
    from apps.notifications.services import notify

    notify(user, events.GM_AUTO_PROMOTED, payload={"games_played": games_played})
    return True


@transaction.atomic
def deactivate_account(user: User) -> User:
    """注销 = 匿名化保留。

    做法：昵称改为「已注销用户#<id>」（唯一约束要求带后缀）、邮箱置空并留单向哈希、
    清头像、停用账号、断开登录凭据。评价、战报、统计等既有数据保留不删。
    """
    if user.is_deactivated:
        return user

    if user.email:
        user.anonymized_email_hash = hashlib.sha256(user.email.lower().encode()).hexdigest()
    old_nickname = user.nickname
    user.nickname = f"{ANONYMIZED_NICKNAME_PREFIX}#{user.pk}"
    user.email = None
    user.avatar = None
    user.is_active = False
    user.is_deactivated = True
    user.deactivated_at = timezone.now()
    user.set_unusable_password()
    user.save()

    NicknameHistory.objects.create(
        user=user, old_nickname=old_nickname, new_nickname=user.nickname
    )

    # 断开 allauth 的邮箱记录，避免注销后仍能走邮箱找回。
    from allauth.account.models import EmailAddress

    EmailAddress.objects.filter(user=user).delete()
    return user


def ban_user(user: User, *, reason: str = "") -> User:
    user.is_banned = True
    user.is_active = False
    user.ban_reason = reason
    user.save(update_fields=["is_banned", "is_active", "ban_reason"])
    return user


def unban_user(user: User) -> User:
    user.is_banned = False
    if not user.is_deactivated:
        user.is_active = True
    user.ban_reason = ""
    user.save(update_fields=["is_banned", "is_active", "ban_reason"])
    return user


def mute_user(user: User, *, reason: str = "") -> User:
    user.is_muted = True
    user.mute_reason = reason
    user.save(update_fields=["is_muted", "mute_reason"])
    return user


def unmute_user(user: User) -> User:
    user.is_muted = False
    user.mute_reason = ""
    user.save(update_fields=["is_muted", "mute_reason"])
    return user


def set_avatar(user: User, uploaded_file) -> User:
    """头像：jpg/png/webp、≤2 MB，服务端缩到 256 px 并统一转 WebP。

    格式按魔数校验，不信任扩展名；转码过程顺带剥掉 EXIF。
    """
    from django.conf import settings

    from common.images import open_validated_image, webp_content_file

    image = open_validated_image(uploaded_file, max_bytes=settings.AVATAR_MAX_BYTES)
    content = webp_content_file(
        image, max_side=settings.AVATAR_MAX_SIDE, name="avatar.webp"
    )
    old = user.avatar.name if user.avatar else ""
    user.avatar.save(content.name, content, save=True)
    if old and old != user.avatar.name:
        user.avatar.storage.delete(old)
    return user


def clear_avatar(user: User) -> User:
    if not user.avatar:
        return user
    name = user.avatar.name
    storage = user.avatar.storage
    user.avatar = None
    user.save(update_fields=["avatar"])
    if name:
        storage.delete(name)
    return user
