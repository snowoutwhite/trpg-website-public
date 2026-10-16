"""角色卡文件的白名单校验：扩展名 + 魔数（txt 走 UTF-8 可解码校验）。"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass

from common.exceptions import ApiError

# 单文件上限：20 MB
CARD_FILE_MAX_BYTES = 20 * 1024 * 1024

# 扩展名 → 对外声明的 MIME。.jpeg 视作 .jpg 的别名。
EXTENSION_MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
ALLOWED_EXTENSIONS = tuple(EXTENSION_MIME)

# 扩展名 → 允许的文件头（魔数）。txt 没有魔数，单独做 UTF-8 校验。
MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    # OOXML 实际是 zip 容器
    "xlsx": (b"PK\x03\x04",),
    "docx": (b"PK\x03\x04",),
    # 旧版 xls 是 OLE2 复合文档
    "xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
}

# OOXML 容器里必须出现的成员，用来挡「把 .zip 改名成 .docx」
OOXML_MARKER = "[Content_Types].xml"
OOXML_REQUIRED_PREFIX = {"xlsx": "xl/", "docx": "word/"}


class InvalidCardFile(ApiError):
    default_code = "invalid_card_file"
    default_detail = "文件格式不受支持，仅支持 pdf、xlsx、xls、docx、txt、png、jpg。"


class CardFileTooLarge(ApiError):
    default_code = "card_file_too_large"
    default_detail = "单个文件体积超出限制。"


@dataclass(frozen=True)
class ValidatedCardFile:
    """校验结果：调用方据此落库，不要再信任上传端给的 content_type。"""

    original_name: str
    extension: str
    mime: str
    size: int


def validate_card_file(uploaded_file, *, max_bytes: int | None = None) -> ValidatedCardFile:
    """校验一个上传的角色卡文件，通过则返回归一化后的元数据，否则抛 ApiError。"""
    limit = CARD_FILE_MAX_BYTES if max_bytes is None else max_bytes

    original_name = posixpath.basename(str(getattr(uploaded_file, "name", "") or "")).strip()
    if not original_name:
        raise InvalidCardFile("这个文件没有文件名。")

    extension = posixpath.splitext(original_name)[1].lower().lstrip(".")
    if extension not in EXTENSION_MIME:
        raise InvalidCardFile()

    size = _size_of(uploaded_file)
    if size > limit:
        raise CardFileTooLarge(f"单个文件不能超过 {limit // 1024 // 1024} MB。")
    if size == 0:
        raise InvalidCardFile("这个文件内容为空。")

    if extension == "txt":
        _check_utf8_text(uploaded_file, limit=limit)
    else:
        _check_magic(uploaded_file, extension)
        if extension in OOXML_REQUIRED_PREFIX:
            _check_ooxml(uploaded_file, extension)

    uploaded_file.seek(0)
    return ValidatedCardFile(
        original_name=original_name[:255],
        extension=extension,
        mime=EXTENSION_MIME[extension],
        size=size,
    )


def _size_of(uploaded_file) -> int:
    size = getattr(uploaded_file, "size", None)
    if size is not None:
        return int(size)
    uploaded_file.seek(0, 2)
    size = uploaded_file.tell()
    uploaded_file.seek(0)
    return int(size)


def _check_magic(uploaded_file, extension: str) -> None:
    prefixes = MAGIC_PREFIXES[extension]
    longest = max(len(prefix) for prefix in prefixes)
    uploaded_file.seek(0)
    head = uploaded_file.read(longest)
    uploaded_file.seek(0)
    if not any(head.startswith(prefix) for prefix in prefixes):
        raise InvalidCardFile("文件内容与后缀不符，请更换文件。")


def _check_ooxml(uploaded_file, extension: str) -> None:
    """xlsx/docx 必须是真的 OOXML 包，且内容目录与扩展名对得上。"""
    uploaded_file.seek(0)
    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise InvalidCardFile("文件内容与后缀不符，请更换文件。") from exc
    finally:
        uploaded_file.seek(0)

    if OOXML_MARKER not in names:
        raise InvalidCardFile("文件内容与后缀不符，请更换文件。")
    required = OOXML_REQUIRED_PREFIX[extension]
    if not any(name.startswith(required) for name in names):
        raise InvalidCardFile("文件内容与后缀不符，请更换文件。")


def _check_utf8_text(uploaded_file, *, limit: int) -> None:
    """txt 没有魔数，改判「整份内容能按 UTF-8 解码」，顺带挡掉改名的二进制文件。"""
    uploaded_file.seek(0)
    raw = uploaded_file.read(limit + 1)
    uploaded_file.seek(0)
    if len(raw) > limit:
        raise CardFileTooLarge(f"单个文件不能超过 {limit // 1024 // 1024} MB。")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCardFile("txt 文件须为 UTF-8 编码，请转换后重新上传。") from exc
