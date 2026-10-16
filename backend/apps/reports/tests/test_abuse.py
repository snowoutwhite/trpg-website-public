"""战报举报：登录才能举报，同一人同一份只能举报一次。"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.reports.models import ABUSE_PENDING, ReportReport

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_report(game_factory, attendee_factory, report_factory):
    game = game_factory()
    return report_factory(game, attendee_factory(game))


def test_guest_cannot_report(api_client, public_report):
    url = reverse("v1:reports:report-abuse", args=[public_report.pk])

    response = api_client.post(url, {"reason": "抄袭"}, format="json")

    assert response.status_code in (401, 403)
    assert not ReportReport.objects.exists()


def test_logged_in_user_can_report_once(api_client, public_report, user_factory):
    reporter = user_factory()
    api_client.force_authenticate(reporter)
    url = reverse("v1:reports:report-abuse", args=[public_report.pk])

    first = api_client.post(url, {"reason": "内容不适"}, format="json")
    second = api_client.post(url, {"reason": "再刷一次"}, format="json")

    assert first.status_code == 201
    assert first.json()["status"] == ABUSE_PENDING
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "already_reported"
    assert ReportReport.objects.filter(report=public_report, reporter=reporter).count() == 1


def test_reason_required(api_client, public_report, user_factory):
    api_client.force_authenticate(user_factory())
    url = reverse("v1:reports:report-abuse", args=[public_report.pk])

    response = api_client.post(url, {"reason": "   "}, format="json")

    assert response.status_code == 400


def test_cannot_report_invisible_report(api_client, public_report, user_factory):
    from apps.reports.models import VISIBILITY_SAME_GAME

    public_report.visibility = VISIBILITY_SAME_GAME
    public_report.save(update_fields=["visibility"])
    api_client.force_authenticate(user_factory())

    response = api_client.post(
        reverse("v1:reports:report-abuse", args=[public_report.pk]),
        {"reason": "看不见也想举报"},
        format="json",
    )

    assert response.status_code == 404


def test_admin_handles_abuse(public_report, user_factory):
    from apps.reports import services
    from apps.reports.models import ABUSE_RESOLVED

    reporter = user_factory()
    staff = user_factory(nickname="站主")
    abuse = services.report_abuse(reporter, public_report, reason="不适")

    services.handle_abuse(abuse, status=ABUSE_RESOLVED, by=staff, note="已下架")

    abuse.refresh_from_db()
    assert abuse.status == ABUSE_RESOLVED
    assert abuse.handled_by == staff
    assert abuse.handled_at is not None
