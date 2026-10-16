"""资源区对抗性测试：权限位越权、审核状态绕过、扩展名黑名单绕过、外链协议、下发头、CSRF。

纪律（安全测试规则）：每条都先写成能复现问题的用例，
修复后才转绿。
"""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.resources.models import Resource, ResourceKind

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/resources/"


def detail_url(resource: Resource) -> str:
    return f"{LIST_URL}{resource.pk}/"


def download_url(resource: Resource) -> str:
    return f"{LIST_URL}{resource.pk}/download/"


def make_file_resource(*, title="跑团速查表", uploader=None, is_approved=True, filename="a.pdf"):
    resource = Resource(
        title=title, kind=ResourceKind.FILE, uploader=uploader, is_approved=is_approved
    )
    resource.file.save(filename, ContentFile(b"%PDF-1.7 fake"), save=False)
    resource.save()
    return resource


def upload(name: str, data: bytes = b"%PDF-1.7 fake"):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


# --------------------------------------------------------------------------
# 1. 路由矩阵
# --------------------------------------------------------------------------


def test_未登录时每条路由的状态码都在预期内(api_client, user_factory):
    approved = make_file_resource(title="已审核", is_approved=True)
    pending = make_file_resource(title="待审核", is_approved=False, uploader=user_factory())

    # W5 状态码统一：未登录访问需登录接口一律 401（原先被 DRF 降级成 403）。
    expected = {
        ("get", LIST_URL): 200,  # 资源列表对游客可见
        ("post", LIST_URL): 401,
        ("get", detail_url(approved)): 200,
        ("patch", detail_url(approved)): 401,
        ("delete", detail_url(approved)): 401,
        ("get", download_url(approved)): 401,  # 下发必须登录
        ("get", detail_url(pending)): 404,  # 未审核：看不见就 404，不用 403 暴露存在
        ("get", download_url(pending)): 401,
    }
    actual = {
        (method, url): getattr(api_client, method)(url).status_code for method, url in expected
    }
    assert actual == expected


def test_列表不混入未审核条目(api_client, user_factory):
    make_file_resource(title="已审核", is_approved=True)
    make_file_resource(title="别人的待审", is_approved=False, uploader=user_factory())

    # 游客
    assert [r["title"] for r in api_client.get(LIST_URL).json()["results"]] == ["已审核"]
    # 普通登录用户（不是上传者、没有审核权限）
    api_client.force_authenticate(user=user_factory(nickname="路人"))
    assert [r["title"] for r in api_client.get(LIST_URL).json()["results"]] == ["已审核"]


def test_未审核条目对他人下载也是404(api_client, user_factory):
    pending = make_file_resource(is_approved=False, uploader=user_factory())
    api_client.force_authenticate(user=user_factory(nickname="路人"))
    assert api_client.get(download_url(pending)).status_code == 404
    assert api_client.get(detail_url(pending)).status_code == 404


# --------------------------------------------------------------------------
# 2. 权限位与审核状态
# --------------------------------------------------------------------------


def test_无上传权限位的用户不能新建资源(api_client, user_factory):
    api_client.force_authenticate(user=user_factory())
    response = api_client.post(
        LIST_URL, {"title": "偷传", "kind": "file", "file": upload("x.pdf")}, format="multipart"
    )
    assert response.status_code == 403
    assert Resource.objects.count() == 0


def test_无权限位用户不能改删他人资源(api_client, user_factory, grant_perm):
    owner = grant_perm(user_factory(), "add_resource")
    resource = make_file_resource(uploader=owner, is_approved=True, title="站主的表")
    api_client.force_authenticate(user=user_factory(nickname="路人"))

    assert api_client.patch(detail_url(resource), {"title": "被改了"}).status_code == 403
    assert api_client.delete(detail_url(resource)).status_code == 403
    resource.refresh_from_db()
    assert resource.title == "站主的表"


def test_上传者不能把自己的投稿直接置为已审核(api_client, user_factory, grant_perm):
    """只有 add_resource、没有 approve_resource 的人投稿后必须待审。"""
    contributor = grant_perm(user_factory(nickname="有头衔的GM"), "add_resource")
    api_client.force_authenticate(user=contributor)

    response = api_client.post(
        LIST_URL,
        {"title": "投稿", "kind": "file", "file": upload("x.pdf"), "is_approved": "true"},
        format="multipart",
    )
    assert response.status_code == 201, response.content
    resource = Resource.objects.get()
    assert resource.is_approved is False

    # PATCH 也不行
    assert api_client.patch(detail_url(resource), {"is_approved": True}).status_code in (200, 400)
    resource.refresh_from_db()
    assert resource.is_approved is False


def test_上传者换掉文件后条目重新待审(api_client, user_factory, grant_perm):
    contributor = grant_perm(user_factory(), "add_resource")
    resource = make_file_resource(uploader=contributor, is_approved=True)
    api_client.force_authenticate(user=contributor)

    response = api_client.patch(
        detail_url(resource), {"file": upload("新文件.pdf")}, format="multipart"
    )
    assert response.status_code == 200, response.content
    resource.refresh_from_db()
    assert resource.is_approved is False, "换了文件还保持已审核 = 过审后偷换内容"


# --------------------------------------------------------------------------
# 3. 扩展名黑名单
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "木马.exe",
        "木马.EXE",
        "卡.pdf.exe",
        "payload.js.txt",
        "页面.htm",
        "页面.html",
        "矢量.svg",
        "包.jar",
        "脚本.py",
        "脚本.ps1",
        "库.dll",
        "屏保.scr",
        "脚本.vbs",
        # 以下是归一化绕过：Django 落盘时会把尾随空白/制表符去掉，还原成真正的扩展名
        "木马.exe ",
        "木马.exe\t",
        "木马.exe\xa0",
        "木马.EXE ",
        "矢量.svg ",
        "页面.html ",
        # Python 3.12 的 Path.suffixes 对「结尾是点」「开头是点」的名字返回空列表
        "木马.exe.",
        ".exe",
        ".html",
    ],
)
def test_黑名单扩展名的各种变形都拦得住(api_client, user_factory, grant_perm, filename):
    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=uploader)

    response = api_client.post(
        LIST_URL,
        {"title": "危险", "kind": "file", "file": upload(filename, b"MZ\x90\x00")},
        format="multipart",
    )
    assert response.status_code == 400, f"{filename!r} 被放行了：{response.content}"
    assert response.json()["error"]["code"] == "blocked_file_type", response.content
    assert Resource.objects.count() == 0


@pytest.mark.parametrize(
    "filename", ["木马.ex\u202ee", "木马.exe\u202a", "木马.e\u2066xe", "矢量.sv\u2069g"]
)
def test_后缀里夹双向控制字符也拦得住(filename):
    """业务规则与安全约束。"""
    from apps.resources.services import BlockedFileType, assert_extension_allowed

    with pytest.raises(BlockedFileType):
        assert_extension_allowed(filename)


@pytest.mark.parametrize("filename", ["速查.pdf", "地图.PNG", "材料包.zip", "音频.mp3", "说明.txt"])
def test_正常素材不被黑名单误伤(api_client, user_factory, grant_perm, filename):
    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=uploader)
    response = api_client.post(
        LIST_URL, {"title": "素材", "kind": "file", "file": upload(filename)}, format="multipart"
    )
    assert response.status_code == 201, response.content


def test_PATCH换文件同样过黑名单(api_client, user_factory, grant_perm):
    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    resource = make_file_resource(uploader=uploader)
    api_client.force_authenticate(user=uploader)

    response = api_client.patch(
        detail_url(resource), {"file": upload("木马.exe ", b"MZ")}, format="multipart"
    )
    assert response.status_code == 400, response.content


# --------------------------------------------------------------------------
# 4. 外链协议
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://example.com/\nX-Evil: 1",
        "//example.com/x",
        "http://",
        " javascript:alert(1) ",
    ],
)
def test_外链只接受http与https(api_client, user_factory, grant_perm, url):
    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=uploader)
    response = api_client.post(
        LIST_URL, {"title": "外链", "kind": "link", "url": url}, format="json"
    )
    assert response.status_code == 400, f"{url!r} 被放行了：{response.content}"
    assert Resource.objects.count() == 0


def test_链接类资源调下载接口不会读到文件(api_client, user_factory, grant_perm):
    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=uploader)
    created = api_client.post(
        LIST_URL,
        {"title": "外链", "kind": "link", "url": "https://example.com/x"},
        format="json",
    ).json()
    assert created["download_url"] is None

    response = api_client.get(f"{LIST_URL}{created['id']}/download/")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_a_file_resource"


# --------------------------------------------------------------------------
# 5. 下发与隐私
# --------------------------------------------------------------------------


def test_任何序列化输出都不含存储路径与邮箱(api_client, user_factory, grant_perm):
    uploader = grant_perm(user_factory(nickname="站主", email="boss@example.com"), "add_resource")
    resource = make_file_resource(uploader=uploader, is_approved=True)
    api_client.force_authenticate(user=uploader)

    for url in (LIST_URL, detail_url(resource)):
        raw = api_client.get(url).content.decode()
        assert "boss@example.com" not in raw, url
        assert "protected/" not in raw, url
        assert "/media/" not in raw, url
        assert resource.file.name not in raw, url
    assert set(api_client.get(detail_url(resource)).json()["uploader"]) == {
        "id",
        "nickname",
        "avatar",
        "is_gm",
    }


def test_下发头是附件且禁止嗅探(api_client, user_factory):
    resource = make_file_resource(title="速查表", is_approved=True)
    api_client.force_authenticate(user=user_factory())
    response = api_client.get(download_url(resource))
    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"].startswith("attachment;")


@pytest.mark.parametrize(
    "title",
    ['恶意"; X-Injected: 1; x="', "换\r\n行", "超长" * 200, "外挂.exe"],
)
def test_标题不会造成响应头注入或危险下发名(api_client, user_factory, title):
    resource = make_file_resource(title=title, is_approved=True)
    api_client.force_authenticate(user=user_factory())
    response = api_client.get(download_url(resource))

    assert response.status_code == 200
    assert "X-Injected" not in response
    disposition = response["Content-Disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "text/html" not in response["Content-Type"]


def test_无后缀文件的下发名不会被标题塞进危险扩展名(api_client, user_factory):
    """存储名没有后缀时，下发名 = 标题；标题里的 .exe 不能直接变成扩展名。"""
    resource = Resource(title="外挂.exe", kind=ResourceKind.FILE, is_approved=True)
    resource.file.save("README", ContentFile(b"data"), save=False)
    resource.save()

    api_client.force_authenticate(user=user_factory())
    response = api_client.get(download_url(resource))
    assert response.status_code == 200
    assert ".exe" not in response["Content-Disposition"], response["Content-Disposition"]


# --------------------------------------------------------------------------
# 6. CSRF
# --------------------------------------------------------------------------


def test_写接口缺少csrf_token时被拒(db, user_factory, grant_perm):
    from rest_framework.test import APIClient

    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    resource = make_file_resource(uploader=uploader)

    client = APIClient(enforce_csrf_checks=True)
    assert client.login(email=uploader.email, password="testpass1234")

    assert client.post(
        LIST_URL, {"title": "无 token", "kind": "file", "file": upload("x.pdf")}, format="multipart"
    ).status_code == 403
    assert client.patch(detail_url(resource), {"title": "无 token"}, format="json").status_code == 403
    assert client.delete(detail_url(resource)).status_code == 403

    resource.refresh_from_db()
    assert resource.title == "跑团速查表"
    assert Resource.objects.count() == 1


# --------------------------------------------------------------------------
# 7. 存储与下发通道
# --------------------------------------------------------------------------


def test_生产模式下走X_Accel且不把字节交给Django(api_client, user_factory, settings):
    settings.USE_X_ACCEL_REDIRECT = True
    resource = make_file_resource(is_approved=True)
    api_client.force_authenticate(user=user_factory())

    response = api_client.get(download_url(resource))
    assert response.status_code == 200
    redirect = response["X-Accel-Redirect"]
    assert redirect.startswith(settings.X_ACCEL_REDIRECT_PREFIX)
    assert ".." not in redirect and "//" not in redirect.removeprefix("/")
    assert response.content == b""


def test_路径穿越文件名不会逃出受保护目录(api_client, user_factory, grant_perm, settings):
    import re

    uploader = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=uploader)

    for name in ["../../../../etc/passwd.pdf", "..\\..\\windows\\x.pdf"]:
        response = api_client.post(
            LIST_URL, {"title": "素材", "kind": "file", "file": upload(name)}, format="multipart"
        )
        assert response.status_code == 201, response.content
        stored = Resource.objects.order_by("-id").first().file.name
        prefix = f"{settings.PROTECTED_MEDIA_DIRNAME}/resources/"
        assert stored.startswith(prefix), stored
        assert ".." not in stored
        assert re.fullmatch(r"[0-9a-f]{32}\.pdf", stored[len(prefix):]), stored
        assert "passwd" not in stored and "windows" not in stored

    # 超长文件名：被挡在 400，不落库、不落盘
    before = Resource.objects.count()
    response = api_client.post(
        LIST_URL, {"title": "素材", "kind": "file", "file": upload("材" * 400 + ".pdf")},
        format="multipart",
    )
    assert response.status_code == 400, response.content
    assert Resource.objects.count() == before


def test_资源标题含RTL覆盖字符一律400(api_client, user_factory, grant_perm):
    """业务规则与安全约束。"""
    owner = grant_perm(user_factory(), "add_resource")
    resource = make_file_resource(uploader=owner, is_approved=True, title="正常表")
    api_client.force_authenticate(user=owner)
    response = api_client.patch(detail_url(resource), {"title": "坏\u202e表"}, format="json")
    assert response.status_code == 400, response.content
    resource.refresh_from_db()
    assert resource.title == "正常表"
