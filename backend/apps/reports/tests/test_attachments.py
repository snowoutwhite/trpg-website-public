"""附件：白名单校验、数量上限、受控下发。"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.reports.models import MAX_ATTACHMENTS, VISIBILITY_SAME_GAME, ReportAttachment

from .conftest import PDF_BYTES, upload

pytestmark = pytest.mark.django_db


@pytest.fixture
def owned_report(game_factory, attendee_factory, report_factory):
    game = game_factory()
    author = attendee_factory(game)
    return report_factory(game, author), author


def _list_url(report):
    return reverse("v1:reports:attachment-list", args=[report.pk])


def test_author_can_upload_attachment(api_client, owned_report):
    report, author = owned_report
    api_client.force_authenticate(author)

    response = api_client.post(_list_url(report), {"file": upload()}, format="multipart")

    assert response.status_code == 201
    assert response.json()["original_name"] == "战报附件.pdf"
    # 响应里绝不能出现存储路径
    assert "file" not in response.json()
    assert "/media/" not in response.content.decode()


def test_non_author_cannot_upload(api_client, owned_report, user_factory):
    report, _ = owned_report
    api_client.force_authenticate(user_factory())

    response = api_client.post(_list_url(report), {"file": upload()}, format="multipart")

    assert response.status_code == 403


def test_extension_whitelist_and_magic_check(api_client, owned_report):
    """与角色卡同一套校验：扩展名不在白名单 → 拒；魔数对不上 → 拒。"""
    report, author = owned_report
    api_client.force_authenticate(author)

    bad_ext = api_client.post(
        _list_url(report),
        {"file": SimpleUploadedFile("木马.exe", b"MZ\x90\x00")},
        format="multipart",
    )
    fake_pdf = api_client.post(
        _list_url(report),
        {"file": SimpleUploadedFile("伪装.pdf", b"MZ\x90\x00not a pdf")},
        format="multipart",
    )

    assert bad_ext.status_code == 400
    assert bad_ext.json()["error"]["code"] == "invalid_card_file"
    assert fake_pdf.status_code == 400
    assert not ReportAttachment.objects.exists()


def test_oversized_attachment_rejected(api_client, owned_report, monkeypatch):
    report, author = owned_report
    api_client.force_authenticate(author)
    monkeypatch.setattr("apps.reports.services.ATTACHMENT_MAX_BYTES", 10)

    response = api_client.post(
        _list_url(report), {"file": upload()}, format="multipart"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "card_file_too_large"


def test_attachment_count_capped(api_client, owned_report):
    report, author = owned_report
    api_client.force_authenticate(author)

    for _ in range(MAX_ATTACHMENTS):
        assert api_client.post(_list_url(report), {"file": upload()}, format="multipart").status_code == 201
    overflow = api_client.post(_list_url(report), {"file": upload()}, format="multipart")

    assert overflow.status_code == 400
    assert overflow.json()["error"]["code"] == "too_many_attachments"
    assert report.attachments.count() == MAX_ATTACHMENTS


def test_stored_name_is_uuid_not_original(api_client, owned_report):
    report, author = owned_report
    api_client.force_authenticate(author)
    api_client.post(
        _list_url(report), {"file": upload("我的真实姓名.pdf")}, format="multipart"
    )

    attachment = ReportAttachment.objects.get()
    assert "我的真实姓名" not in attachment.file.name
    assert attachment.file.name.startswith("protected/reports/")


def test_download_follows_report_visibility(
    api_client, owned_report, attendee_factory, user_factory
):
    report, author = owned_report
    report.visibility = VISIBILITY_SAME_GAME
    report.save(update_fields=["visibility"])
    api_client.force_authenticate(author)
    attachment_id = api_client.post(
        _list_url(report), {"file": upload()}, format="multipart"
    ).json()["id"]
    url = reverse("v1:reports:attachment-download", args=[report.pk, attachment_id])

    # 作者本人：可下
    assert api_client.get(url).status_code == 200
    # 同团：可下
    api_client.force_authenticate(attendee_factory(report.game))
    assert api_client.get(url).status_code == 200
    # 非同团的登录用户：404
    api_client.force_authenticate(user_factory())
    assert api_client.get(url).status_code == 404
    # 游客：404
    api_client.force_authenticate(None)
    assert api_client.get(url).status_code == 404


def test_download_is_attachment_with_nosniff(api_client, owned_report):
    report, author = owned_report
    api_client.force_authenticate(author)
    attachment_id = api_client.post(
        _list_url(report), {"file": upload()}, format="multipart"
    ).json()["id"]

    response = api_client.get(
        reverse("v1:reports:attachment-download", args=[report.pk, attachment_id])
    )

    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("attachment;")
    assert b"".join(response.streaming_content) == PDF_BYTES


def test_author_can_delete_attachment(api_client, owned_report, user_factory):
    report, author = owned_report
    api_client.force_authenticate(author)
    attachment_id = api_client.post(
        _list_url(report), {"file": upload()}, format="multipart"
    ).json()["id"]
    url = reverse("v1:reports:attachment-detail", args=[report.pk, attachment_id])

    api_client.force_authenticate(user_factory())
    assert api_client.delete(url).status_code == 403

    api_client.force_authenticate(author)
    assert api_client.delete(url).status_code == 204
    assert not ReportAttachment.objects.exists()
