"""积分账本的唯一写入口。

三个函数就是对外的全部 API（reports 模块与后台都只调这三个）：

    grant(user, amount, reason, *, ref=None, dedupe_key=None, created_by=None)
    revoke(entry, by=None)        # 写一条负数行，**不删原行**
    balance(user)                 # 所有流水之和

为什么要 `dedupe_key`：战报「提交即发积分」，但用户可以删掉战报再写一份。
如果只按「创建时发一次」判断，删了重写就能反复刷分；把去重键定成
「某人 + 某团」（战报本来就是每人每团一份）后，重写不会二次发分，
站主撤销过的分也不会因为重写而复活。
"""

from __future__ import annotations

from django.db import IntegrityError, models, transaction

from apps.points.models import (
    REASON_MANUAL,
    REASON_REVOKED_BY_ADMIN,
    PointsLedger,
)
from common.exceptions import ApiError


class InvalidPointsAmount(ApiError):
    default_code = "invalid_points_amount"
    default_detail = "积分变动不能为 0"


class AlreadyRevoked(ApiError):
    default_code = "points_already_revoked"
    default_detail = "这条积分流水已经撤销过了"


class NotRevocable(ApiError):
    default_code = "points_not_revocable"
    default_detail = "撤销行不能再被撤销"


class DedupeKeyOwnerMismatch(ApiError):
    default_code = "points_dedupe_key_conflict"
    default_detail = "去重键已经被另一个用户占用，积分未发放"


def grant(
    user,
    amount: int,
    reason: str = REASON_MANUAL,
    *,
    ref=None,
    dedupe_key: str | None = None,
    created_by=None,
    note: str = "",
) -> PointsLedger:
    """发放（或扣减）积分，返回落库的流水行。

    传了 `dedupe_key` 且库里已有同键的行时，**直接返回那一行，不再发分**（幂等）。
    """
    amount = int(amount)
    if amount == 0:
        raise InvalidPointsAmount()

    key = dedupe_key or None
    if key:
        existing = PointsLedger.objects.filter(dedupe_key=key).first()
        if existing is not None:
            _assert_same_owner(existing, user, key)
            return existing

    entry = PointsLedger(
        user=user,
        amount=amount,
        reason=reason,
        dedupe_key=key,
        created_by=created_by,
        note=note,
    )
    _attach_ref(entry, ref)
    try:
        # 单开 savepoint：撞唯一约束时只回滚这一步，外层事务还能继续。
        with transaction.atomic():
            entry.save()
    except IntegrityError:
        # 并发下另一个请求抢先写了同一个去重键，认它的结果。
        if key:
            existing = PointsLedger.objects.filter(dedupe_key=key).first()
            if existing is not None:
                _assert_same_owner(existing, user, key)
                return existing
        raise
    return entry


def _assert_same_owner(existing: PointsLedger, user, key: str) -> None:
    """去重键撞上了别人的流水 —— 宁可抛错，也不能静默「认它的结果」。

    `grant` 原来是「同键就直接返回那一行」，于是调用方拼错去重键（比如把团 id
    和用户 id 写反、或者少拼一段）时，B 的积分请求会**静默**地返回 A 的流水行：
    B 永远拿不到分，账面上也看不出任何异常，只有对账时才会发现。
    当前唯一的调用方是 reports（键 = `report:game:<团>:user:<人>`），
    这条断言就是钉住「键里必须带上人」这个约定。
    """
    owner_id = getattr(user, "pk", user)
    if existing.user_id != owner_id:
        raise DedupeKeyOwnerMismatch(
            f"去重键 {key} 已属于另一个用户的流水（#{existing.pk}），本次积分未发放"
        )


def revoke(entry: PointsLedger, by=None, *, note: str = "") -> PointsLedger:
    """站主撤销一条流水：追加一条金额相反的行，原行保持不动。"""
    if entry.reason == REASON_REVOKED_BY_ADMIN or entry.revokes_id is not None:
        raise NotRevocable()
    if entry.is_revoked:
        raise AlreadyRevoked()

    reversal = PointsLedger(
        user_id=entry.user_id,
        amount=-entry.amount,
        reason=REASON_REVOKED_BY_ADMIN,
        ref_content_type_id=entry.ref_content_type_id,
        ref_object_id=entry.ref_object_id,
        revokes=entry,
        created_by=by,
        note=note,
    )
    try:
        with transaction.atomic():
            reversal.save()
    except IntegrityError as exc:
        # 唯一约束兜住并发重复撤销。
        raise AlreadyRevoked() from exc
    return reversal


def balance(user) -> int:
    """某人的积分余额 = 其所有流水之和（含撤销产生的负数行）。"""
    total = PointsLedger.objects.filter(user=user).aggregate(total=models.Sum("amount"))["total"]
    return int(total or 0)


def history(user):
    """某人的流水（倒序）。后台与将来的个人页都从这里取，不要自己拼查询。"""
    return PointsLedger.objects.filter(user=user).select_related("created_by")


def _attach_ref(entry: PointsLedger, ref) -> None:
    """把关联对象挂到流水上；ref 为空则留空，不报错。"""
    if ref is None:
        return
    from django.contrib.contenttypes.models import ContentType

    entry.ref_content_type = ContentType.objects.get_for_model(ref.__class__)
    entry.ref_object_id = ref.pk
