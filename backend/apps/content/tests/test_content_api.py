"""术语表 / 新人指南 / FAQ：游客可读，未发布的不外露。"""

from __future__ import annotations

import pytest

from apps.content.models import FAQ, GlossaryTerm, Guide

pytestmark = pytest.mark.django_db


def test_游客可读术语表(api_client):
    GlossaryTerm.objects.create(term="KP", definition="COC 的主持人", aliases=["守密人"], order=1)
    GlossaryTerm.objects.create(term="草稿词", definition="未发布", is_published=False)
    data = api_client.get("/api/v1/content/glossary/").json()
    assert [item["term"] for item in data] == ["KP"]
    assert data[0]["aliases"] == ["守密人"]


def test_游客可读指南列表与详情(api_client):
    Guide.objects.create(title="新人怎么报名", slug="how-to-join", body_markdown="# 步骤")
    listing = api_client.get("/api/v1/content/guides/").json()
    assert listing[0]["slug"] == "how-to-join"
    detail = api_client.get("/api/v1/content/guides/how-to-join/").json()
    assert detail["body_markdown"] == "# 步骤"


def test_未发布的指南404(api_client):
    Guide.objects.create(title="草稿", slug="draft", body_markdown="x", is_published=False)
    assert api_client.get("/api/v1/content/guides/draft/").status_code == 404


def test_游客可读FAQ(api_client):
    FAQ.objects.create(question="要付费吗", answer="不要")
    data = api_client.get("/api/v1/content/faqs/").json()
    assert data[0]["question"] == "要付费吗"
