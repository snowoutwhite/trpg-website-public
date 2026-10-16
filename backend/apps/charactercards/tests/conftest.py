"""角色卡测试共用夹具与假文件工厂。"""

from __future__ import annotations

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
XLS_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
TXT_BYTES = "调查员：无名氏\n力量 60\n".encode()
EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 64


def ooxml_bytes(kind: str) -> bytes:
    """造一个最小但合法的 OOXML 包（xlsx / docx）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "xl/workbook.xml" if kind == "xlsx" else "word/document.xml", "<root/>"
        )
    return buffer.getvalue()


def plain_zip_bytes() -> bytes:
    """普通 zip：有 zip 魔数但没有 OOXML 结构，用来测「改名成 .xlsx」被拒。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not office")
    return buffer.getvalue()


def upload(name: str, data: bytes, content_type: str = "application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件留在仓库里。"""
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


@pytest.fixture
def card_factory(db, user_factory):
    from apps.charactercards.services import create_card

    def make(owner=None, **kwargs):
        owner = owner or user_factory()
        kwargs.setdefault("name", "无名调查员")
        kwargs.setdefault("rule_system", "COC")
        return create_card(owner, **kwargs)

    return make
