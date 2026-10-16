"""对抗性测试 · common/files.py：受保护文件下发的三条边界。

攻击面：
1. `download_name` 是调用方（往往来自用户输入的原始文件名/标题）传进来的，
   不能让它决定 `Content-Type` —— 配上 `nosniff`，浏览器会老老实实按声明的类型渲染，
   于是「存的是 txt、声明成 html」就成了媒体域上的存储型 XSS。
2. X-Accel-Redirect 的路径必须永远落在受保护前缀内；一旦存储名以 `/` 开头，
   `posixpath.join` 会直接丢掉前缀，变成对 Nginx 的任意 internal 重定向。
3. `Content-Disposition` 只有 `filename*=UTF-8''` 时，老客户端会退化成 URL 编码串，
   还要防住引号/换行把响应头拆开。
"""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from common.files import protected_file_response
from common.images import WEBP_MAX_SIDE, to_webp


class _FakeFileField:
    """只实现 protected_file_response 用到的那两样：`name` 与 `open()`。"""

    def __init__(self, name: str, content: bytes = b"payload"):
        self.name = name
        self._content = content

    def open(self, mode: str = "rb"):
        return io.BytesIO(self._content)


def _disposition(response) -> str:
    return response["Content-Disposition"]


# ------------------------------------------------------------ Content-Type


@pytest.mark.parametrize(
    "download_name,forbidden",
    [
        ("evil.html", "text/html"),
        ("evil.svg", "image/svg+xml"),
        ("evil.xhtml", "application/xhtml+xml"),
        ("evil.js", "javascript"),
    ],
)
def test_content_type_never_comes_from_caller_supplied_name(download_name, forbidden):
    """存的是 txt，下发名叫 .html —— Content-Type 绝不能跟着下发名走。"""
    field = _FakeFileField("protected/resources/abc123.txt")
    response = protected_file_response(field, download_name=download_name)
    assert forbidden not in response["Content-Type"], (
        f"下发名 {download_name} 把 Content-Type 顶成了 {response['Content-Type']}"
    )


def test_content_type_follows_the_stored_name():
    """反证：类型要跟着服务端生成的存储名走，不能一律退化成 octet-stream。"""
    field = _FakeFileField("protected/charactercards/abc123.pdf")
    response = protected_file_response(field, download_name="我的角色卡.pdf")
    assert response["Content-Type"] == "application/pdf"


def test_unknown_stored_extension_falls_back_to_octet_stream():
    field = _FakeFileField("protected/misc/abc123")
    response = protected_file_response(field, download_name="whatever.pdf")
    assert response["Content-Type"] == "application/octet-stream"


def test_explicit_content_type_wins():
    """调用方确有把握时可以显式指定，但必须是显式的，不能靠文件名猜。"""
    field = _FakeFileField("protected/misc/abc123")
    response = protected_file_response(
        field, download_name="x.bin", content_type="application/pdf"
    )
    assert response["Content-Type"] == "application/pdf"


# ------------------------------------------------- X-Accel-Redirect 路径


@override_settings(USE_X_ACCEL_REDIRECT=True, X_ACCEL_REDIRECT_PREFIX="/media/protected/")
@pytest.mark.parametrize(
    "stored_name",
    [
        "/etc/passwd",
        "//etc/passwd",
        "protected/../../../etc/passwd",
        "protected/cards/../../../../etc/shadow",
        "/protected/cards/ok.pdf",
    ],
)
def test_x_accel_redirect_never_escapes_the_protected_prefix(stored_name):
    """存储名不管长什么样，internal 重定向都必须落在受保护前缀里面。"""
    response = protected_file_response(_FakeFileField(stored_name))
    target = response["X-Accel-Redirect"]
    assert target.startswith("/media/protected/"), f"逃出了受保护前缀：{target}"
    assert "/.." not in target, f"重定向路径里还留着上跳段：{target}"


@override_settings(USE_X_ACCEL_REDIRECT=True, X_ACCEL_REDIRECT_PREFIX="/media/protected/")
def test_x_accel_redirect_normal_path_still_works():
    """反证：正常存储名要原样落在前缀后面，否则上一条用例是假绿灯。"""
    response = protected_file_response(_FakeFileField("protected/charactercards/abc.pdf"))
    assert response["X-Accel-Redirect"] == "/media/protected/charactercards/abc.pdf"
    assert response.content == b""  # 字节由 Nginx 发，Django 只做鉴权


# ------------------------------------------------- Content-Disposition


def test_disposition_carries_both_ascii_and_utf8_filenames():
    """中文名必须同时给 ASCII 回退与 RFC 5987 形式，老客户端才不会拿到一串 %E4%B8%AD。"""
    response = protected_file_response(
        _FakeFileField("protected/resources/abc.pdf"), download_name="我的角色卡.pdf"
    )
    disposition = _disposition(response)
    assert disposition.startswith("attachment;")
    assert "filename=" in disposition, f"缺少 ASCII 回退：{disposition}"
    assert "filename*=UTF-8''" in disposition, disposition


@pytest.mark.parametrize(
    "hostile",
    [
        'a";x="b.pdf',
        "a\\b.pdf",
        "a\r\nX-Injected: 1\r\n.pdf",
        "a\nX-Injected: 1.pdf",
        "../../etc/passwd",
        "\x00null.pdf",
    ],
)
def test_disposition_survives_hostile_download_names(hostile):
    """下发名常常直接来自用户输入，不能让它拆开响应头或逃出 filename 参数。"""
    response = protected_file_response(
        _FakeFileField("protected/resources/abc.pdf"), download_name=hostile
    )
    disposition = _disposition(response)
    assert "\r" not in disposition and "\n" not in disposition, disposition
    assert "\x00" not in disposition
    ascii_part = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in ascii_part and "\\" not in ascii_part, ascii_part
    assert "/" not in ascii_part and ".." not in ascii_part, ascii_part


def test_disposition_ascii_fallback_is_never_empty():
    response = protected_file_response(
        _FakeFileField("protected/resources/abc.pdf"), download_name="中文中文"
    )
    ascii_part = _disposition(response).split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part.strip("_ ") != "" or ascii_part, "ASCII 回退名不能是空串"
    assert ascii_part.isascii()


def test_inline_disposition_still_sets_nosniff():
    response = protected_file_response(
        _FakeFileField("protected/gallery/abc.webp"), as_attachment=False
    )
    assert _disposition(response).startswith("inline;")
    assert response["X-Content-Type-Options"] == "nosniff"


# --------------------------------------------------------------------------
# W5：to_webp 自校 WebP 容器的单边上限
# --------------------------------------------------------------------------


def _wide_png_bytes(width: int, height: int = 8) -> bytes:
    """造一张超宽的纯色 PNG：只有几十 KB，体积闸与像素闸都拦不住它。"""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (7, 7, 7)).save(buffer, format="PNG")
    return buffer.getvalue()


def _open_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_to_webp自己把超宽图封到WebP上限而不是抛500():
    """libwebp 单边上限 16383，超了 Pillow 抛的是 ValueError（不是 OSError、不是 ApiError）。

    以前只有 gallery 在调用侧封顶，任何以「不缩放」为意图调用 `to_webp` 的新代码
    都会踩同一个洞（W3 红队的原始缺口，W5 收进 common）。
    """
    image = _open_image(_wide_png_bytes(WEBP_MAX_SIDE + 1))

    data = to_webp(image, max_side=10**9)  # 调用方「不想缩放」

    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    assert max(_open_image(data).size) <= WEBP_MAX_SIDE


def test_to_webp不放大小图():
    """封顶只是上限，比目标尺寸小的图不许被放大。"""
    image = _open_image(_wide_png_bytes(64, 32))
    assert _open_image(to_webp(image, max_side=10**9)).size == (64, 32)


def test_头像走的是同一个转码函数_超宽图也不会500(api_client, user_factory):
    """头像以前靠 `AVATAR_MAX_SIDE=256` 恒缩到 256 才侥幸不中招，现在是函数自己兜底。"""
    user = user_factory(nickname="超宽头像")
    api_client.force_authenticate(user)
    response = api_client.post(
        "/api/v1/accounts/me/avatar/",
        {
            "avatar": SimpleUploadedFile(
                "wide.png", _wide_png_bytes(WEBP_MAX_SIDE + 1, 4), content_type="image/png"
            )
        },
        format="multipart",
    )
    assert response.status_code < 500, response.content
