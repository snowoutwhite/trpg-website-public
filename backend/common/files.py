"""受保护文件的下发。"""

from __future__ import annotations

import mimetypes
import posixpath
import re
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse

# ASCII 回退名里允许保留的字符：其余一律换成下划线。
# 排除 `"` `\` 是为了不逃出 filename="..."；排除路径分隔符与控制字符是为了
# 不让下发名看起来像路径、也不让它拆开响应头。
_ASCII_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._\- ]")
_DOT_RUN = re.compile(r"\.{2,}")

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def protected_file_response(
    file_field,
    *,
    download_name: str | None = None,
    content_type: str | None = None,
    as_attachment: bool = True,
) -> HttpResponse:
    """把一个 FileField/ImageField 的内容安全地下发给已鉴权的请求。

    调用方负责鉴权；本函数只负责「怎么发」。

    - `download_name`：给浏览器看的文件名，只影响 Content-Disposition，**不影响类型**。
    - `content_type`：调用方确有把握时显式指定；不传则按存储名推断，
      推断不出就退回 `application/octet-stream`。
    """
    stored_name = file_field.name or ""
    name = download_name or posixpath.basename(stored_name) or "download"
    if content_type is None:
        content_type = mimetypes.guess_type(posixpath.basename(stored_name))[0]
        content_type = content_type or DEFAULT_CONTENT_TYPE

    if settings.USE_X_ACCEL_REDIRECT:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = _internal_redirect_target(stored_name)
    else:
        response = FileResponse(file_field.open("rb"), content_type=content_type)

    disposition = "attachment" if as_attachment else "inline"
    response["Content-Disposition"] = (
        f"{disposition}; filename=\"{_ascii_filename(name)}\"; "
        f"filename*=UTF-8''{quote(_sanitize_filename(name), safe='')}"
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _internal_redirect_target(stored_name: str) -> str:
    """拼出 Nginx internal location 的路径，保证结果一定在受保护前缀之内。"""
    prefix = settings.X_ACCEL_REDIRECT_PREFIX.rstrip("/") + "/"
    relative = _relative_to_protected_root(stored_name)
    # lstrip("/") 不可省：posixpath.join(prefix, "/etc/passwd") == "/etc/passwd"，
    # 前缀会被整段丢掉，变成对 Nginx 的任意 internal 重定向。
    relative = relative.lstrip("/")
    # 压掉 `..`，避免靠上跳段逃出前缀（正常存储名是 uuid，不会有上跳段）。
    segments = [seg for seg in relative.split("/") if seg not in ("", ".", "..")]
    return quote(prefix + "/".join(segments))


def _relative_to_protected_root(stored_name: str) -> str:
    """存储名形如 `protected/charactercards/xx.pdf`，去掉前缀给 Nginx internal location 用。"""
    prefix = settings.PROTECTED_MEDIA_DIRNAME + "/"
    normalized = stored_name.lstrip("/")
    if normalized.startswith(prefix):
        return normalized[len(prefix) :]
    return normalized


def _sanitize_filename(name: str) -> str:
    """去掉控制字符与路径分隔符：下发名永远只是一个「名字」，不是路径。"""
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in "\r\n\t")
    cleaned = cleaned.replace("\\", "_").replace("/", "_")
    cleaned = _DOT_RUN.sub(".", cleaned).strip().strip(".")
    return cleaned or "download"


def _ascii_filename(name: str) -> str:
    """RFC 6266 的 ASCII 回退名：不支持 filename* 的客户端拿它。"""
    ascii_name = _ASCII_FILENAME_UNSAFE.sub("_", _sanitize_filename(name))
    ascii_name = _DOT_RUN.sub(".", ascii_name).strip().strip(".")
    return ascii_name or "download"
