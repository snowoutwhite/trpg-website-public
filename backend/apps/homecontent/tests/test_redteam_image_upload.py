"""业务规则与安全约束。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.homecontent.tests.conftest import image_upload, png_bytes

pytestmark = pytest.mark.django_db


def code_of(response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def preset_url(db):
    from apps.homecontent.models import RuleSystemPreset

    preset = RuleSystemPreset.objects.first()
    return preset, f"/api/v1/home/admin/rule-presets/{preset.pk}/image/"


@pytest.fixture
def quick_url(db):
    from apps.homecontent.models import QuickEntry

    entry = QuickEntry.objects.first()
    return entry, f"/api/v1/home/admin/quick-entries/{entry.pk}/image/"


def _post(api_client, url, uploaded):
    return api_client.post(url, {"file": uploaded}, format="multipart")


# --------------------------------------------------------------------------
# 2a. 元数据要按字节验
# --------------------------------------------------------------------------

SECRET_MARKERS = [b"SecretCamera", b"\xe6\x8b\x8d\xe6\x91\x84\xe8\x80\x85"]  # Make / Model(拍摄者)


def test_三档输出里一个原始元数据字节都不许剩(api_client, staff_user, preset_url):
    """`read_exif()` 只看 EXIF；这里直接在输出字节里搜相机型号与 XMP 标记。

    为什么加这一条：重编码是否剥干净，取决于「Pillow 往新文件里 copy 了哪些块」，
    而 EXIF 只是其中一种。把断言下沉到字节层，结论才是可证伪的。
    """
    from apps.gallery.tests.conftest import exif_with_gps, make_image_bytes

    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    raw = make_image_bytes(exif=exif_with_gps())
    assert any(marker in raw for marker in SECRET_MARKERS), "夹具本身要带得进标记"

    assert _post(api_client, url, image_upload(data=raw)).status_code == 200
    preset.refresh_from_db()
    for field in (preset.image_full, preset.image_card, preset.image_thumb):
        blob = Path(field.path).read_bytes()
        for marker in SECRET_MARKERS:
            assert marker not in blob, f"{field.name} 里还留着原始元数据 {marker!r}"
        assert b"GPS" not in blob
        assert b"http://ns.adobe.com/xap" not in blob  # XMP 包头
        assert Image.open(io.BytesIO(blob)).format == "WEBP"


def test_快速选择那一档也要剥干净(api_client, staff_user, quick_url):
    """现有 EXIF 用例只验了规则预设的三档，快速选择那条独立路径没人验过。"""
    from apps.gallery.tests.conftest import exif_with_gps, make_image_bytes, read_exif

    entry, url = quick_url
    api_client.force_authenticate(staff_user)
    raw = make_image_bytes(exif=exif_with_gps())

    assert _post(api_client, url, image_upload(data=raw)).status_code == 200
    entry.refresh_from_db()
    blob = Path(entry.image.path).read_bytes()
    assert not read_exif(blob)
    for marker in SECRET_MARKERS:
        assert marker not in blob
    assert Image.open(io.BytesIO(blob)).format == "WEBP"


def test_尾部夹带的载荷会被重编码丢掉(api_client, staff_user, preset_url):
    """经典 polyglot：一张真 JPEG 后面接一段 HTML/PHP。

    重编码之后那段字节必须消失 —— 否则一个 `.webp` 在公开 media 目录里
    同时也是一份可被别的解析器捡起来的载荷。
    """
    from apps.gallery.tests.conftest import make_image_bytes

    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    payload = b"<?php system($_GET[0]); ?><script>alert(1)</script>"
    raw = make_image_bytes() + payload

    assert _post(api_client, url, image_upload(data=raw)).status_code == 200
    preset.refresh_from_db()
    for field in (preset.image_full, preset.image_card, preset.image_thumb):
        assert payload not in Path(field.path).read_bytes()


# --------------------------------------------------------------------------
# 2b. 落盘位置
# --------------------------------------------------------------------------


def test_落盘只在公开media的homecontent目录下(api_client, staff_user, preset_url, settings):
    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    assert _post(api_client, url, image_upload()).status_code == 200
    preset.refresh_from_db()

    media_root = Path(settings.MEDIA_ROOT).resolve()
    protected_root = Path(settings.PROTECTED_MEDIA_ROOT).resolve()
    for field in (preset.image_full, preset.image_card, preset.image_thumb):
        stored = Path(field.path).resolve()
        assert stored.is_relative_to(media_root), f"{stored} 逃出了 MEDIA_ROOT"
        assert not stored.is_relative_to(protected_root), f"{stored} 落进了受保护目录"
        assert field.name.startswith("homecontent/")
        assert field.name.count("/") == 1, f"存储名多了层级：{field.name}"
        assert field.url.startswith(settings.MEDIA_URL)
        assert "protected" not in field.url


def test_不同上传之间文件名不可预测(api_client, staff_user, preset_url):
    """站长内容图走公开直出，文件名就是它唯一的「地址」。两次上传不得撞名。"""
    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    names = set()
    for _ in range(3):
        assert _post(api_client, url, image_upload(name="同一个名字.jpg")).status_code == 200
        preset.refresh_from_db()
        names.add(preset.image_full.name)
    assert len(names) == 3, f"三次上传撞名了：{names}"


def test_换图之后旧文件真的从磁盘上消失(api_client, staff_user, preset_url):
    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    assert _post(api_client, url, image_upload()).status_code == 200
    preset.refresh_from_db()
    old = [Path(f.path) for f in (preset.image_full, preset.image_card, preset.image_thumb)]
    assert all(p.exists() for p in old)

    assert _post(api_client, url, image_upload(data=png_bytes(), name="新图.png")).status_code == 200
    for path in old:
        assert not path.exists(), f"旧文件还留在磁盘上：{path}"


# --------------------------------------------------------------------------
# 2c. 退化输入只许 400
# --------------------------------------------------------------------------


#: (标签, 文件名, 字节, content-type)。在用例里现场构造 —— Django 的
#: `SimpleUploadedFile` 自己就会拒掉一部分病态文件名（那是 Django 的闸，不是本 app 的），
#: 收集期构造会把整个模块拖成 collection error。
DEGENERATE = [
    ("空文件", "empty.jpg", b"", "image/jpeg"),
    ("一个字节", "tiny.jpg", b"\xff", "image/jpeg"),
    ("截断的JPEG", "cut.jpg", None, "image/jpeg"),
    ("只有魔数", "magic.png", b"\x89PNG\r\n\x1a\n", "image/png"),
    ("没有扩展名", "noext", None, "image/jpeg"),
    ("只有点", ".", None, "image/jpeg"),
    ("斜杠开头", "/etc/passwd.jpg", None, "image/jpeg"),
    ("双扩展名", "x.jpg.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
    ("NUL截断名", "x.php\x00.jpg", None, "image/jpeg"),
    ("超长文件名", "长" * 300 + ".jpg", None, "image/jpeg"),
    ("HTML伪装成webp", "x.webp", b"<html><script>alert(1)</script></html>", "image/webp"),
    ("PDF伪装成avif", "x.avif", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "image/avif"),
    ("zip伪装成png", "x.png", b"PK\x03\x04" + b"\x00" * 64, "image/png"),
    ("ELF伪装成jpg", "x.jpg", b"\x7fELF" + b"\x00" * 64, "image/jpeg"),
]


@pytest.mark.parametrize(
    ("label", "name", "data", "content_type"), DEGENERATE, ids=[c[0] for c in DEGENERATE]
)
def test_退化输入一律400不得5xx(api_client, staff_user, preset_url, label, name, data, content_type):
    """合格答案只有两种：Django/DRF 在更外层拒掉，或者本 app 回 400。5xx 一个都不行。"""
    from django.core.exceptions import SuspiciousFileOperation

    from apps.gallery.tests.conftest import make_image_bytes

    if data is None:
        good = make_image_bytes()
        data = good[:200] if label == "截断的JPEG" else good

    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    try:
        uploaded = SimpleUploadedFile(name, data, content_type)
    except SuspiciousFileOperation:
        pytest.skip(f"{label}：Django 在构造 UploadedFile 时就拒了，轮不到本 app")
    response = _post(api_client, url, uploaded)
    assert response.status_code < 500, f"{label} → {response.status_code}"
    if response.status_code == 200:
        preset.refresh_from_db()
        blob = Path(preset.image_full.path).read_bytes()
        assert Image.open(io.BytesIO(blob)).format == "WEBP", f"{label} 被接受且输出不是 WebP"
        assert preset.image_full.name.startswith("homecontent/")
        assert ".." not in preset.image_full.name
    else:
        assert response.status_code == 400, f"{label} → {response.status_code}"


def test_字段名写错或不带文件都是400(api_client, staff_user, preset_url):
    preset, url = preset_url
    api_client.force_authenticate(staff_user)
    assert api_client.post(url, {}, format="multipart").status_code == 400
    assert api_client.post(
        url, {"image": image_upload()}, format="multipart"
    ).status_code == 400
    assert api_client.post(url, {"file": "不是文件只是字符串"}, format="multipart").status_code == 400


def test_对不存在的资源换图是404不是500(api_client, staff_user):
    api_client.force_authenticate(staff_user)
    for url in (
        "/api/v1/home/admin/rule-presets/999999/image/",
        "/api/v1/home/admin/quick-entries/999999/image/",
    ):
        response = api_client.post(url, {"file": image_upload()}, format="multipart")
        assert response.status_code == 404, f"{url} → {response.status_code}"


# --------------------------------------------------------------------------
# 2d. 限速确实挂在上传口上
# --------------------------------------------------------------------------


def test_两个上传视图都挂着upload限速档():
    """`throttle_scope` 写了但 `ScopedRateThrottle` 没注册 = 完全没限速
    （base.py 里那条注释就是为这个坑写的）。这里两头都确认一遍。"""
    from rest_framework.settings import api_settings
    from rest_framework.throttling import ScopedRateThrottle

    from apps.homecontent.views import AdminQuickEntryImageView, AdminRulePresetImageView

    scoped = "rest_framework.throttling.ScopedRateThrottle"
    assert scoped in api_settings.user_settings.get(
        "DEFAULT_THROTTLE_CLASSES", []
    ) or ScopedRateThrottle in api_settings.DEFAULT_THROTTLE_CLASSES
    assert "upload" in api_settings.DEFAULT_THROTTLE_RATES
    for view in (AdminRulePresetImageView, AdminQuickEntryImageView):
        assert view.throttle_scope == "upload"
        assert any(isinstance(t, ScopedRateThrottle) for t in view().get_throttles())
