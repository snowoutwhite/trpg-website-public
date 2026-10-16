"""战报的业务规则。视图只做鉴权与序列化，判断全在这里。"""

from __future__ import annotations

from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.charactercards.validators import CARD_FILE_MAX_BYTES, validate_card_file
from apps.games.models import GAME_FINISHED, SIGNUP_ACCEPTED, Game, Signup
from apps.points import services as points_services
from apps.points.models import REASON_REPORT_SUBMITTED
from apps.reports.models import (
    ABUSE_PENDING,
    MAX_ATTACHMENTS,
    VISIBILITY_PUBLIC,
    VISIBILITY_SAME_GAME,
    Report,
    ReportAttachment,
    ReportReport,
)
from common.exceptions import ApiError, Forbidden
from common.permissions import is_account_blocked

# 一份战报发多少积分。用户只定了「提交即发放、站主可撤销」，没定数值，
# 这里取 10 作为默认；将来要做成站级可配项就挪进 siteconfig

POINTS_PER_REPORT = 10

# 附件大小上限：战报附件同角色卡，直接复用角色卡的常量。
ATTACHMENT_MAX_BYTES = CARD_FILE_MAX_BYTES


class GameNotFinished(ApiError):
    # 400：团还没结团是「目标状态不对」，与 reviews 的 `review_not_open`、

    default_code = "game_not_finished"
    default_detail = "团结束后才能撰写战报。"


class NotInGame(Forbidden):
    default_code = "not_in_game"
    default_detail = "只有当场到场成员才能撰写战报。"


class TooManyAttachments(ApiError):
    default_code = "too_many_attachments"
    default_detail = f"一份战报最多 {MAX_ATTACHMENTS} 个附件。"


class AlreadyReported(ApiError):
    default_code = "already_reported"
    default_detail = "你已经举报过这份战报。"


# ---------------------------------------------------------------------------
# 资格判断
# ---------------------------------------------------------------------------


def is_game_gm(user, game: Game) -> bool:
    return bool(getattr(user, "pk", None)) and game.gm_id == user.pk


def attended_game(user, game: Game) -> bool:
    """本人是否在本团里到场。本团 GM 没有报名行，视为在场。

    判据是「**正式名单里的人** + 到场」：`attended` 只是结团那一刻的快照，
    单看它会把「退团 / 被移出 / 被拒」的报名行也算成同团（他们的 `attended`
    不会被回滚），等于给这些人留了「补写战报拿积分 + 读本团 same_game 战报」的后门。
    与 games 自己的口径一致（`games.services` 统计到场也是 `attended + accepted`）。
    对抗测试：`tests/test_adversarial_reports.py::test_退团的人即使被标到场也不能写战报不能看同团战报`。
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if is_game_gm(user, game):
        return True
    return Signup.objects.filter(
        game=game, player=user, attended=True, status=SIGNUP_ACCEPTED
    ).exists()


def assert_can_submit(user, game: Game) -> None:
    """不满足提交条件就抛 403（DRF 层会翻译成统一错误格式）。"""
    if game.status != GAME_FINISHED:
        raise GameNotFinished()
    if not attended_game(user, game):
        raise NotInGame()


def assert_can_import(user, game: Game) -> None:
    """「从文档导入正文」的资格：本团已有自己那份战报（作者改稿），或满足提交条件。

    与写战报同一口径：导入只是往编辑框里填字，能写 / 能改的人才用得着。
    """
    if Report.objects.filter(game=game, author=user).exists():
        return
    assert_can_submit(user, game)


def member_game_ids(user) -> models.QuerySet | list:
    """这个人「同团」的团 id：他主持的 + 他到场过的。"""
    if not getattr(user, "is_authenticated", False):
        return []
    hosted = Game.objects.filter(gm=user).values_list("id", flat=True)
    # 与 `attended_game()` 同一判据：正式名单里的人 + 到场，退团/被移出的不算同团。
    attended = Signup.objects.filter(
        player=user, attended=True, status=SIGNUP_ACCEPTED
    ).values_list("game_id", flat=True)
    return list(set(hosted) | set(attended))


def can_moderate(user) -> bool:
    """业务规则与安全约束。"""
    return bool(getattr(user, "is_authenticated", False)) and user.has_perm("reports.moderate_report")


# ---------------------------------------------------------------------------
# 可见性
# ---------------------------------------------------------------------------


def visible_queryset(user, *, featured_only: bool = False) -> models.QuerySet[Report]:
    """当前用户能看到的战报集合。游客只有「精选 + 公开」。

    封禁 / 停用的会话按游客算（`is_account_blocked`）：这两个接口是 `AllowAny`，
    走不到权限类，不在这里判一次的话，被封禁的人还能继续读同团的 `same_game` 战报
    —— 那正是「被封禁账号在读接口上被当成正常登录用户」的那一格。
    与 `apps.gallery.services.can_view_photo` 同一口径。
    """
    queryset = Report.objects.select_related("game", "author").prefetch_related("attachments")
    if not getattr(user, "is_authenticated", False) or is_account_blocked(user):
        return queryset.filter(is_featured=True, visibility=VISIBILITY_PUBLIC)

    condition = Q(visibility=VISIBILITY_PUBLIC) | Q(author=user)
    condition |= Q(visibility=VISIBILITY_SAME_GAME, game_id__in=member_game_ids(user))
    queryset = queryset.filter(condition)
    if featured_only:
        queryset = queryset.filter(is_featured=True, visibility=VISIBILITY_PUBLIC)
    return queryset.distinct()


def can_view(user, report: Report) -> bool:
    # 封禁先于一切（含作者本人），与 `visible_queryset()` 同一顺序：
    # 顺序反过来时封禁作者列表里看不到、详情却 200。
    if not getattr(user, "is_authenticated", False) or is_account_blocked(user):
        return report.visible_to_guests
    if user.pk == report.author_id:
        return True
    if report.visibility == VISIBILITY_PUBLIC:
        return True
    return attended_game(user, report.game)


def can_edit(user, report: Report) -> bool:
    """只有作者能改正文与附件；站主改内容不在需求里（站主只精选/删除/处理举报）。"""
    return getattr(user, "pk", None) == report.author_id


def can_delete(user, report: Report) -> bool:
    return can_edit(user, report) or can_moderate(user)


# ---------------------------------------------------------------------------
# 写操作
# ---------------------------------------------------------------------------


def points_dedupe_key(user_id: int, game_id: int) -> str:
    """积分去重键：每人每团只发一次，与「每人每团一份战报」同口径。"""
    return f"report:game:{game_id}:user:{user_id}"


@transaction.atomic
def submit_report(
    user,
    game: Game,
    *,
    title: str,
    body_markdown: str = "",
    visibility: str = VISIBILITY_PUBLIC,
) -> tuple[Report, bool]:
    """新建或更新本人在本团的战报，返回 `(report, created)`。

    第一次落库时发积分；之后的修改只更新内容，不再发分。
    """
    assert_can_submit(user, game)

    report, created = Report.objects.get_or_create(
        game=game,
        author=user,
        defaults={
            "title": title,
            "body_markdown": body_markdown,
            "visibility": visibility,
        },
    )
    if not created:
        report.title = title
        report.body_markdown = body_markdown
        report.visibility = visibility
        report.save(update_fields=["title", "body_markdown", "visibility", "updated_at"])
        return report, False

    points_services.grant(
        user,
        POINTS_PER_REPORT,
        REASON_REPORT_SUBMITTED,
        ref=report,
        dedupe_key=points_dedupe_key(user.pk, game.pk),
        note=f"战报《{report.title}》",
    )
    return report, True


def update_report(report: Report, **fields) -> Report:
    """改标题 / 正文 / 可见范围。精选标记不在这里改（只有站主在后台能动）。"""
    allowed = {"title", "body_markdown", "visibility"}
    changed = []
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(report, key, value)
            changed.append(key)
    if changed:
        report.save(update_fields=[*changed, "updated_at"])
    return report


def add_attachment(report: Report, uploaded_file, *, uploaded_by) -> ReportAttachment:
    """加一个附件。白名单 + 魔数与角色卡同一套（直接复用，不复制一份逻辑）。"""
    if report.attachments.count() >= MAX_ATTACHMENTS:
        raise TooManyAttachments()

    validated = validate_card_file(uploaded_file, max_bytes=ATTACHMENT_MAX_BYTES)
    attachment = ReportAttachment(
        report=report,
        original_name=validated.original_name,
        size=validated.size,
        mime=validated.mime,
        uploaded_by=uploaded_by,
    )
    uploaded_file.seek(0)
    # 存储名由 models.report_attachment_upload_to 生成（uuid，不可猜），只借原名取扩展名。
    attachment.file.save(f"upload.{validated.extension}", uploaded_file, save=False)
    attachment.save()
    return attachment


def delete_attachment(attachment: ReportAttachment) -> None:
    """删附件同时删盘上的文件，不留孤儿。"""
    stored = attachment.file
    attachment.delete()
    if stored:
        stored.delete(save=False)


def report_abuse(user, report: Report, *, reason: str) -> ReportReport:
    """举报一份战报。同一个人对同一份战报只能举报一次（唯一约束 + 这里的显式提示）。"""
    abuse, created = ReportReport.objects.get_or_create(
        report=report,
        reporter=user,
        defaults={"reason": reason, "status": ABUSE_PENDING},
    )
    if not created:
        raise AlreadyReported()
    return abuse


def handle_abuse(abuse: ReportReport, *, status: str, by=None, note: str = "") -> ReportReport:
    """站主处理举报（后台用）。"""
    abuse.status = status
    abuse.handled_by = by
    abuse.handled_at = timezone.now()
    abuse.handle_note = note
    abuse.save(update_fields=["status", "handled_by", "handled_at", "handle_note"])
    return abuse


def set_featured(report: Report, *, featured: bool) -> Report:
    """站主打/取消「精选」标记（后台用；前台没有这个入口）。"""
    report.is_featured = featured
    report.save(update_fields=["is_featured", "updated_at"])
    return report
