"""积分账本：grant / revoke / balance 与去重。"""

from __future__ import annotations

import pytest

from apps.points import services
from apps.points.models import (
    REASON_MANUAL,
    REASON_REPORT_SUBMITTED,
    REASON_REVOKED_BY_ADMIN,
    PointsLedger,
    Title,
    UserTitle,
)
from common.exceptions import ApiError

pytestmark = pytest.mark.django_db


def test_grant_and_balance(user_factory):
    user = user_factory()

    services.grant(user, 10, REASON_REPORT_SUBMITTED)
    services.grant(user, 5, REASON_MANUAL, note="补发")

    assert services.balance(user) == 15
    assert PointsLedger.objects.filter(user=user).count() == 2


def test_balance_is_zero_without_entries(user_factory):
    assert services.balance(user_factory()) == 0


def test_zero_amount_rejected(user_factory):
    with pytest.raises(ApiError):
        services.grant(user_factory(), 0, REASON_MANUAL)


def test_dedupe_key_grants_once(user_factory):
    user = user_factory()

    first = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key="report:game:1:user:1")
    second = services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key="report:game:1:user:1")

    assert first.pk == second.pk
    assert services.balance(user) == 10


def test_revoke_writes_negative_row_without_deleting(user_factory):
    user = user_factory()
    staff = user_factory(nickname="站主")
    entry = services.grant(user, 10, REASON_REPORT_SUBMITTED)

    reversal = services.revoke(entry, by=staff)

    assert reversal.amount == -10
    assert reversal.reason == REASON_REVOKED_BY_ADMIN
    assert reversal.created_by == staff
    assert PointsLedger.objects.filter(pk=entry.pk).exists()  # 原行还在
    assert PointsLedger.objects.filter(user=user).count() == 2
    assert services.balance(user) == 0
    entry.refresh_from_db()
    assert entry.is_revoked is True


def test_revoke_twice_rejected(user_factory):
    user = user_factory()
    entry = services.grant(user, 10, REASON_REPORT_SUBMITTED)
    services.revoke(entry)

    with pytest.raises(ApiError):
        services.revoke(entry)

    assert services.balance(user) == 0


def test_revocation_row_cannot_be_revoked(user_factory):
    user = user_factory()
    reversal = services.revoke(services.grant(user, 10, REASON_REPORT_SUBMITTED))

    with pytest.raises(ApiError):
        services.revoke(reversal)


def test_revoked_points_do_not_come_back_with_same_dedupe_key(user_factory):
    """站主撤销后，同一个去重键不会因为重新提交而复发。"""
    user = user_factory()
    key = "report:game:7:user:3"
    services.revoke(services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key=key))

    services.grant(user, 10, REASON_REPORT_SUBMITTED, dedupe_key=key)

    assert services.balance(user) == 0


def test_ref_is_recorded(user_factory):
    user = user_factory()
    title = Title.objects.create(name="深潜者", cost=100)

    entry = services.grant(user, 1, REASON_MANUAL, ref=title)

    entry.refresh_from_db()
    assert entry.ref == title


def test_history_is_scoped_to_user(user_factory):
    user = user_factory()
    other = user_factory()
    services.grant(user, 10, REASON_MANUAL)
    services.grant(other, 20, REASON_MANUAL)

    assert [e.amount for e in services.history(user)] == [10]


def test_titles_are_table_only(user_factory):
    """称号首发只建表 + 后台：有模型，但不该有对外接口。"""
    from apps.points import urls

    user = user_factory()
    title = Title.objects.create(name="老兵", description="跑满十团", cost=50)
    UserTitle.objects.create(user=user, title=title)

    assert user.titles.count() == 1
    assert urls.urlpatterns == []
