"""角色卡业务逻辑：建卡、加文件版本（保留最近 3 版）、可见性判断、参团记录。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.charactercards.models import (
    KEEP_FILE_VERSIONS,
    STATUS_ALIVE,
    CardPlayRecord,
    CharacterCard,
    CharacterCardFile,
)
from apps.charactercards.validators import validate_card_file
from apps.siteconfig.services import OTHER_SENTINEL, exclude_preset_rule_systems

# --------------------------------------------------------------------------
# 反向接线点（games 用）
# --------------------------------------------------------------------------

# 额外的「谁能看这张卡的源文件」判断，签名 (user, card) -> bool。
# games 阶段在 AppConfig.ready() 里注册「同团 GM 可看 PL 交上来的卡」。
_file_access_checkers: list[Callable[[object, CharacterCard], bool]] = []

# 参团记录的展示信息补全，签名 (game_ids) -> {game_id: {...}}，用来补团名、开团时间等。
_play_detail_providers: list[Callable[[Sequence[int]], dict]] = []


def register_file_access_checker(checker: Callable[[object, CharacterCard], bool]) -> None:
    if checker not in _file_access_checkers:
        _file_access_checkers.append(checker)


def register_play_detail_provider(provider: Callable[[Sequence[int]], dict]) -> None:
    if provider not in _play_detail_providers:
        _play_detail_providers.append(provider)


# --------------------------------------------------------------------------
# 可见性
# --------------------------------------------------------------------------


def can_view_card(user, card: CharacterCard) -> bool:
    """卡的元数据（名称 / 规则 / 次数 / 跑过的团）：公开卡人人可见，私密卡只有本人。"""
    if card.is_public:
        return True
    return _is_owner(user, card)


def can_view_file(user, card: CharacterCard) -> bool:
    """源文件下载权。

    当前口径：本人，或「登录用户 + 公开卡」。
    - 游客一律为假：需求整理写的是「公开卡可被任何用户浏览与下载」，
      本实现把「任何用户」理解为**已登录用户**，游客只能浏览卡池不能下载（存疑，已上报）。
    - games 阶段的「同团 GM 可看交上来的卡」通过 `register_file_access_checker` 追加，
      不要改这里的默认规则。
    """
    # 封禁号 / 注销号不算「已登录用户」：`mine/*` 用 IsAuthenticatedAndActive 挡住了他们，
    # 下发源文件的口子不能比写接口还松（资源区的下载接口也是这个口径）。
    # 注意：禁言（is_muted）只限制放团/报名/评价，不影响下载。
    if not _is_usable_account(user):
        return False
    if _is_owner(user, card):
        return True
    if card.is_public:
        return True
    return any(checker(user, card) for checker in _file_access_checkers)


def _is_usable_account(user) -> bool:
    """已登录、未注销（is_active）、未封禁。与 `common.permissions.IsAuthenticatedAndActive` 同口径。"""
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not getattr(user, "is_banned", False)
    )


def _is_owner(user, card: CharacterCard) -> bool:
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and card.owner_id == user.pk
    )


# --------------------------------------------------------------------------
# 卡与文件版本
# --------------------------------------------------------------------------


def create_card(
    owner,
    *,
    name: str,
    rule_system: str = "",
    is_public: bool = False,
    note: str = "",
) -> CharacterCard:
    return CharacterCard.objects.create(
        owner=owner,
        name=name,
        rule_system=rule_system,
        is_public=is_public,
        note=note,
    )


@transaction.atomic
def add_file_version(
    card: CharacterCard,
    uploaded_file,
    *,
    uploaded_by,
    uploaded_by_gm: bool = False,
) -> CharacterCardFile:
    """加一个文件版本。

    - 先做白名单 + 魔数（txt 走 UTF-8）校验，不通过直接抛 ApiError。
    - 版本号单调递增；参团记录跟着卡不跟着文件。
    - `uploaded_by_gm=True` 表示 GM 代 PL 上传，卡仍归 PL。
    """
    validated = validate_card_file(uploaded_file)

    for attempt in range(_VERSION_RETRIES):
        version = CharacterCardFile(
            card=card,
            original_name=validated.original_name,
            size=validated.size,
            mime=validated.mime,
            version=_next_version(card),
            uploaded_by=uploaded_by,
            uploaded_by_gm=uploaded_by_gm,
        )
        # 存储名由 models.card_file_upload_to 生成（uuid，不可猜），只借原名取扩展名。
        uploaded_file.seek(0)
        version.file.save(f"upload.{validated.extension}", uploaded_file, save=False)
        try:
            # 单开一个 savepoint：撞上唯一约束时只回滚这一步，外层事务还能继续重试。
            with transaction.atomic():
                version.save()
        except IntegrityError:
            # 并发的另一个上传抢先占了这个版本号。删掉刚落盘的孤儿文件后重算版本号再来。
            version.file.delete(save=False)
            if attempt == _VERSION_RETRIES - 1:
                raise
            continue
        break

    prune_old_versions(card)
    return version


#: 并发抢版本号时的重试次数（每次重算 next_version）。
_VERSION_RETRIES = 5


def _next_version(card: CharacterCard) -> int:
    return (
        CharacterCardFile.objects.filter(card=card)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    ) + 1


def prune_old_versions(card: CharacterCard, *, keep: int = KEEP_FILE_VERSIONS) -> int:
    """只保留最近 keep 版，更旧的连文件一起删。返回删掉的版本数。

    删的是本系统自己生成的版本文件（用户主动换新版时的旧版），不是用户当前持有的内容。
    """
    stale = list(CharacterCardFile.objects.filter(card=card).order_by("-version")[keep:])
    for old in stale:
        if old.file:
            old.file.delete(save=False)
        old.delete()
    return len(stale)


# --------------------------------------------------------------------------
# 参团记录（games 接线点）
# --------------------------------------------------------------------------


def record_play(card: CharacterCard, game, *, played_at=None) -> CardPlayRecord:
    """games 成功结团时调用：记一次「这张卡跑过此团」并刷新缓存的参团次数。

    `game` 传 games 的团实例或它的主键整数皆可；同一张卡 + 同一个团重复调用是幂等的。
    """
    game_id = int(getattr(game, "pk", game))
    record, created = CardPlayRecord.objects.get_or_create(
        card=card,
        game_id=game_id,
        defaults={"played_at": played_at or timezone.now()},
    )
    if created:
        card.play_count = CardPlayRecord.objects.filter(card=card).count()
        card.save(update_fields=["play_count", "updated_at"])
    return record


def games_played_for(card: CharacterCard) -> list[dict]:
    """这张卡参与过的团。

    games 尚未实现，没有任何 `record_play` 调用时返回空列表；
    games 落地后可用 `register_play_detail_provider` 把团名等补进每一项。
    """
    records = list(card.play_records.all())
    if not records:
        return []

    details: dict[int, dict] = {}
    game_ids = [record.game_id for record in records]
    for provider in _play_detail_providers:
        details.update(provider(game_ids) or {})

    return [
        {
            "game_id": record.game_id,
            "played_at": record.played_at,
            **(details.get(record.game_id) or {}),
        }
        for record in records
    ]


# --------------------------------------------------------------------------
# 卡池查询
# --------------------------------------------------------------------------


def public_pool_queryset(*, rule_system: str = "", status: str = "", owner_id: int | None = None):
    """角色卡池：只出公开卡，游客也能浏览（但不能下载源文件）。

    `owner_id` 只是在**公开卡**这个集合里再筛一层（个人空间要列「TA 的公开卡」），
    不会因为传了自己的 id 就把私密卡带出来 —— 我的卡列表走 `my_cards_queryset`。
    """
    queryset = (
        CharacterCard.objects.filter(is_public=True)
        .select_related("owner")
        .prefetch_related("play_records")
    )
    if rule_system == OTHER_SENTINEL:
        # 卡池的「其他」：规则名不命中任何一条站级预设（大小写不敏感），空规则名也算。
        queryset = exclude_preset_rule_systems(queryset)
    elif rule_system:
        queryset = queryset.filter(rule_system__iexact=rule_system)
    if status:
        queryset = queryset.filter(status=status)
    if owner_id is not None:
        queryset = queryset.filter(owner_id=owner_id)
    return queryset


def my_cards_queryset(user, *, status: str = ""):
    queryset = (
        CharacterCard.objects.filter(owner=user)
        .select_related("owner")
        .prefetch_related("play_records")
    )
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def usable_cards_for_signup(user) -> Iterable[CharacterCard]:
    """games 交卡时的可选卡：本人的、尚存的卡（撕卡不能再用于报名）。"""
    return my_cards_queryset(user).filter(status=STATUS_ALIVE)
