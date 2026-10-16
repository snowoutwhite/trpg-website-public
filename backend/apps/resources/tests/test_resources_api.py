"""资源区接口：游客可读已审核、上传走权限位、黑名单扩展名、外链协议、鉴权下载。"""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile

from apps.resources.models import Resource, ResourceKind

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/resources/"


def make_file_resource(*, title="跑团速查表", uploader=None, is_approved=True, filename="a.pdf"):
    resource = Resource(
        title=title, kind=ResourceKind.FILE, uploader=uploader, is_approved=is_approved
    )
    resource.file.save(filename, ContentFile(b"%PDF-1.7 fake"), save=False)
    resource.save()
    return resource


# --------------------------------------------------------------------------
# 游客可见范围
# --------------------------------------------------------------------------

def test_游客只见已审核资源(api_client):
    make_file_resource(title="已审核的表", is_approved=True)
    make_file_resource(title="待审核的表", is_approved=False)
    data = api_client.get(LIST_URL).json()
    assert [item["title"] for item in data["results"]] == ["已审核的表"]


def test_游客看不到未审核详情(api_client):
    pending = make_file_resource(is_approved=False)
    assert api_client.get(f"{LIST_URL}{pending.pk}/").status_code == 404


def test_上传者能看到自己待审的投稿(api_client, user_factory):
    author = user_factory()
    pending = make_file_resource(title="我的投稿", uploader=author, is_approved=False)
    api_client.force_authenticate(user=author)
    assert api_client.get(f"{LIST_URL}{pending.pk}/").status_code == 200
    titles = [item["title"] for item in api_client.get(LIST_URL).json()["results"]]
    assert titles == ["我的投稿"]

    # 换个普通登录用户就看不到了
    api_client.force_authenticate(user=user_factory())
    assert api_client.get(LIST_URL).json()["results"] == []
    assert api_client.get(f"{LIST_URL}{pending.pk}/").status_code == 404


def test_列表不泄露文件存储路径(api_client):
    resource = make_file_resource()
    item = api_client.get(LIST_URL).json()["results"][0]
    assert item["download_url"] == f"{LIST_URL}{resource.pk}/download/"
    assert "file" not in item
    assert resource.file.name not in api_client.get(LIST_URL).content.decode()


# --------------------------------------------------------------------------
# 上传权限走权限位，而不是 is_superuser
# --------------------------------------------------------------------------

def test_无权限位上传403(api_client, user_factory, pdf_upload):
    api_client.force_authenticate(user=user_factory())
    response = api_client.post(
        LIST_URL, {"title": "私传的东西", "kind": "file", "file": pdf_upload()}, format="multipart"
    )
    assert response.status_code == 403
    assert Resource.objects.count() == 0


def test_游客上传403(api_client, pdf_upload):
    response = api_client.post(
        LIST_URL, {"title": "游客投稿", "kind": "file", "file": pdf_upload()}, format="multipart"
    )
    assert response.status_code in (401, 403)
    assert Resource.objects.count() == 0


def test_授予add_resource权限位后上传201且待审(api_client, user_factory, grant_perm, pdf_upload):
    """「头衔」用户：有上传权限位、没有审核权限位 → 投稿进待审队列。"""
    uploader = grant_perm(user_factory(), "add_resource")
    api_client.force_authenticate(user=uploader)
    response = api_client.post(
        LIST_URL,
        {"title": "COC 速查", "kind": "file", "category": "规则书", "file": pdf_upload()},
        format="multipart",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["is_approved"] is False
    assert body["uploader"]["id"] == uploader.pk
    assert "email" not in body["uploader"]

    resource = Resource.objects.get(pk=body["id"])
    assert resource.file.name.startswith("protected/resources/")
    assert resource.file.name.endswith(".pdf")
    assert "跑团速查" not in resource.file.name  # 存储名随机化，不可枚举


def test_有审核权限者上传默认已审核(api_client, user_factory, grant_perm, pdf_upload):
    """站主自己传的不用自己再审一遍。"""
    owner = grant_perm(user_factory(), "add_resource", "approve_resource")
    api_client.force_authenticate(user=owner)
    response = api_client.post(
        LIST_URL, {"title": "站主整理的资料", "kind": "file", "file": pdf_upload()}, format="multipart"
    )
    assert response.status_code == 201
    assert response.json()["is_approved"] is True


def test_超级管理员无需显式授权即可上传(api_client, user_factory, pdf_upload):
    """站主 = 超级管理员，has_perm() 恒为真；代码里没有一处判断 is_superuser。"""
    owner = user_factory(is_superuser=True, is_staff=True)
    api_client.force_authenticate(user=owner)
    response = api_client.post(
        LIST_URL, {"title": "站主资料", "kind": "file", "file": pdf_upload()}, format="multipart"
    )
    assert response.status_code == 201
    assert response.json()["is_approved"] is True


# --------------------------------------------------------------------------
# 文件与外链校验
# --------------------------------------------------------------------------

@pytest.mark.parametrize("filename", ["外挂.exe", "run.sh", "go.bat", "x.js", "首页.html", "icon.svg"])
def test_黑名单扩展名被拒(api_client, user_factory, grant_perm, pdf_upload, filename):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    response = api_client.post(
        LIST_URL,
        {"title": "危险文件", "kind": "file", "file": pdf_upload(name=filename, content=b"x")},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "blocked_file_type"
    assert Resource.objects.count() == 0


def test_双扩展名也拦得住(api_client, user_factory, grant_perm, pdf_upload):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    response = api_client.post(
        LIST_URL,
        {"title": "伪装", "kind": "file", "file": pdf_upload(name="payload.js.txt", content=b"x")},
        format="multipart",
    )
    assert response.status_code == 400
    assert Resource.objects.count() == 0


def test_普通扩展名放行且不设大小上限(api_client, user_factory, grant_perm, pdf_upload):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    big = pdf_upload(name="模组合集.zip", content=b"0" * (6 * 1024 * 1024))
    response = api_client.post(
        LIST_URL, {"title": "模组合集", "kind": "file", "file": big}, format="multipart"
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "bad_url",
    ["javascript:alert(1)", "ftp://example.com/a.pdf", "file:///etc/passwd", "data:text/html,x"],
)
def test_外链只接受http或https(api_client, user_factory, grant_perm, bad_url):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    response = api_client.post(LIST_URL, {"title": "外链", "kind": "link", "url": bad_url})
    assert response.status_code == 400, response.json()
    assert Resource.objects.count() == 0


def test_合法外链可以创建(api_client, user_factory, grant_perm):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    response = api_client.post(
        LIST_URL, {"title": "官方规则站", "kind": "link", "url": "https://example.com/srd"}
    )
    assert response.status_code == 201
    assert response.json()["download_url"] is None


def test_文件类缺文件被拒(api_client, user_factory, grant_perm):
    api_client.force_authenticate(user=grant_perm(user_factory(), "add_resource"))
    response = api_client.post(LIST_URL, {"title": "空的", "kind": "file"})
    assert response.status_code == 400


# --------------------------------------------------------------------------
# 下载：走鉴权视图，不走直出目录
# --------------------------------------------------------------------------

def test_游客不能下载(api_client):
    resource = make_file_resource()
    response = api_client.get(f"{LIST_URL}{resource.pk}/download/")
    assert response.status_code in (401, 403)


def test_登录用户可以下载已审核资源(api_client, user_factory):
    resource = make_file_resource(title="跑团/速查:表")
    api_client.force_authenticate(user=user_factory())
    response = api_client.get(f"{LIST_URL}{resource.pk}/download/")
    assert response.status_code == 200
    assert response["X-Content-Type-Options"] == "nosniff"
    # 文件名用标题而不是随机存储名，且路径分隔符被替换掉
    assert "attachment" in response["Content-Disposition"]
    assert "%2F" not in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == b"%PDF-1.7 fake"


def test_未审核资源对普通登录用户404(api_client, user_factory):
    resource = make_file_resource(is_approved=False)
    api_client.force_authenticate(user=user_factory())
    assert api_client.get(f"{LIST_URL}{resource.pk}/download/").status_code == 404


def test_上传者可以下载自己待审的资源(api_client, user_factory):
    author = user_factory()
    resource = make_file_resource(uploader=author, is_approved=False)
    api_client.force_authenticate(user=author)
    assert api_client.get(f"{LIST_URL}{resource.pk}/download/").status_code == 200


def test_外链资源没有可下载文件(api_client, user_factory):
    resource = Resource.objects.create(
        title="外链", kind=ResourceKind.LINK, url="https://example.com/", is_approved=True
    )
    api_client.force_authenticate(user=user_factory())
    response = api_client.get(f"{LIST_URL}{resource.pk}/download/")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_a_file_resource"


# --------------------------------------------------------------------------
# 修改与删除
# --------------------------------------------------------------------------

def test_他人不能改删(api_client, user_factory):
    resource = make_file_resource(uploader=user_factory())
    api_client.force_authenticate(user=user_factory())
    assert api_client.patch(f"{LIST_URL}{resource.pk}/", {"title": "改掉"}).status_code == 403
    assert api_client.delete(f"{LIST_URL}{resource.pk}/").status_code == 403
    assert Resource.objects.filter(pk=resource.pk).exists()


def test_上传者可以改自己的资源(api_client, user_factory):
    author = user_factory()
    resource = make_file_resource(uploader=author)
    api_client.force_authenticate(user=author)
    response = api_client.patch(f"{LIST_URL}{resource.pk}/", {"title": "新标题"})
    assert response.status_code == 200
    assert response.json()["title"] == "新标题"


def test_非审核者换文件后重新待审(api_client, user_factory, grant_perm, pdf_upload):
    author = grant_perm(user_factory(), "add_resource")
    resource = make_file_resource(uploader=author, is_approved=True)
    api_client.force_authenticate(user=author)
    response = api_client.patch(
        f"{LIST_URL}{resource.pk}/", {"file": pdf_upload(name="新版.pdf")}, format="multipart"
    )
    assert response.status_code == 200
    assert response.json()["is_approved"] is False


def test_有审核权限者可以删别人的资源(api_client, user_factory, grant_perm):
    resource = make_file_resource(uploader=user_factory())
    api_client.force_authenticate(user=grant_perm(user_factory(), "approve_resource"))
    assert api_client.delete(f"{LIST_URL}{resource.pk}/").status_code == 204
    assert not Resource.objects.filter(pk=resource.pk).exists()


def test_审核权限位可见未审核条目(api_client, user_factory, grant_perm):
    make_file_resource(title="待审", is_approved=False)
    api_client.force_authenticate(user=grant_perm(user_factory(), "approve_resource"))
    titles = [item["title"] for item in api_client.get(LIST_URL).json()["results"]]
    assert titles == ["待审"]


# --------------------------------------------------------------------------
# W5：分类清单接口
# --------------------------------------------------------------------------

CATEGORIES_URL = "/api/v1/resources/categories/"


def _categorized(category: str, *, title: str, is_approved: bool = True, uploader=None):
    resource = make_file_resource(title=title, is_approved=is_approved, uploader=uploader)
    resource.category = category
    resource.save(update_fields=["category"])
    return resource


def test_分类清单去重计数并按条数倒序(api_client):
    _categorized("规则书", title="规则书甲")
    _categorized("规则书", title="规则书乙")
    _categorized("模组", title="模组甲")

    body = api_client.get(CATEGORIES_URL).json()

    assert body["results"] == [
        {"category": "规则书", "count": 2},
        {"category": "模组", "count": 1},
    ]


def test_分类清单游客可读(api_client):
    _categorized("规则书", title="规则书甲")
    assert api_client.get(CATEGORIES_URL).status_code == 200


def test_分类清单不数未审核条目(api_client, user_factory):
    """未审核投稿只对上传者与审核者可见；把它算进公开计数等于告诉所有人有这么一条稿。"""
    uploader = user_factory(nickname="投稿人")
    _categorized("规则书", title="已审核的", is_approved=True)
    _categorized("暗号分类", title="还没过审的", is_approved=False, uploader=uploader)

    for viewer in (None, uploader):
        api_client.force_authenticate(viewer)
        body = api_client.get(CATEGORIES_URL).json()
        assert [row["category"] for row in body["results"]] == ["规则书"]


def test_分类清单跳过空分类(api_client):
    make_file_resource(title="没填分类的", is_approved=True)
    _categorized("规则书", title="填了分类的")

    body = api_client.get(CATEGORIES_URL).json()

    assert body["results"] == [{"category": "规则书", "count": 1}]


def test_分类清单为空时也是合法响应(api_client):
    assert api_client.get(CATEGORIES_URL).json() == {"results": []}
