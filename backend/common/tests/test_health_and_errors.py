"""健康检查与统一错误格式。"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_健康检查游客可访问(api_client):
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_未登录访问受限接口返回统一错误格式(api_client):
    response = api_client.get(reverse("v1:accounts:me"))
    # W5 状态码统一：未登录 401（不再接受 DRF 降级出来的 403）
    assert response.status_code == 401
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "not_authenticated"
    assert isinstance(body["error"]["message"], str)


def test_不存在的资源返回统一错误格式(api_client):
    response = api_client.get("/api/v1/profiles/users/999999/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
