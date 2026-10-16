"""资源区测试夹具：媒体目录隔离到 tmp_path，权限位按需授予。"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件堆进仓库。"""
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PROTECTED_MEDIA_ROOT = settings.MEDIA_ROOT / settings.PROTECTED_MEDIA_DIRNAME
    return settings.MEDIA_ROOT


@pytest.fixture
def grant_perm(db):
    """给用户加资源区权限位，并重新取一次用户以清掉 Django 的权限缓存。"""

    def grant(user, *codenames: str):
        perms = Permission.objects.filter(
            content_type__app_label="resources", codename__in=codenames
        )
        assert perms.count() == len(codenames), f"权限位不存在：{codenames}"
        user.user_permissions.add(*perms)
        return type(user).objects.get(pk=user.pk)

    return grant


@pytest.fixture
def pdf_upload():
    def make(name: str = "跑团速查.pdf", content: bytes = b"%PDF-1.7 fake"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    return make
