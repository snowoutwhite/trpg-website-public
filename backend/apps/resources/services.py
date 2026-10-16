"""资源区业务逻辑。视图只做鉴权与序列化，规则写在这里。

两条硬规则：
1. 上传/审核权限一律问 Django 权限位，不问 `is_superuser`（头衔机制的可开发余地）。
2. 资源文件不设大小上限，但扩展名黑名单挡掉可执行/脚本类。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from django.db.models import Count, Q, QuerySet

from apps.resources.models import Resource, ResourceKind
from common.exceptions import ApiError
from common.text import BIDI_CONTROL_CLASS

# 权限位常量：改名的话这里一处改完即可。
PERM_ADD = "resources.add_resource"
PERM_APPROVE = "resources.approve_resource"

#: 扩展名黑名单：可执行、脚本、以及能在浏览器里跑脚本的标记语言。
#: 站主上传不设大小上限，但这类文件一律不收——
#: 资源区是给几十人的小站分享跑团材料的，没有分发可执行文件的正当场景。
BLOCKED_EXTENSIONS = frozenset(
    {
        # Windows 可执行与脚本
        "exe", "msi", "com", "scr", "pif", "bat", "cmd", "vbs", "vbe", "wsf", "wsh",
        "ps1", "psm1", "psd1", "hta", "reg", "cpl", "msc", "lnk", "dll",
        # *nix / macOS 可执行与脚本
        "sh", "bash", "zsh", "csh", "ksh", "run", "bin", "so", "dylib", "app",
        "pkg", "dmg", "deb", "rpm", "appimage", "command", "scpt",
        # 解释型脚本
        "js", "mjs", "cjs", "jse", "py", "pyc", "pyo", "pyw", "rb", "pl", "php",
        "phtml", "lua", "jar", "class", "apk", "swf",
        # 能带脚本的标记/文档格式
        "html", "htm", "xhtml", "shtml", "svg", "xht", "mht", "mhtml",
        # 带宏的 Office 格式
        "docm", "xlsm", "pptm", "dotm", "xltm", "potm",
    }
)

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: 归一化后缀时要抹掉的不可见字符（空白、零宽、BOM、控制字符、双向控制字符）。
_INVISIBLE_CHARS = re.compile(
    rf'[\s\u200b-\u200f\u2028\u2029\ufeff\x00-\x1f{BIDI_CONTROL_CLASS}]'
)


class BlockedFileType(ApiError):
    default_code = "blocked_file_type"
    default_detail = "资源区不接受可执行文件或脚本文件。"


# --------------------------------------------------------------------------
# 权限判定（只问权限位，不问 is_superuser）
# --------------------------------------------------------------------------

def can_upload(user) -> bool:
    return bool(user and user.is_authenticated and user.has_perm(PERM_ADD))


def can_moderate(user) -> bool:
    """有审核权限 = 能看见未审核条目、能改别人的条目、能批准。"""
    return bool(user and user.is_authenticated and user.has_perm(PERM_APPROVE))


def can_edit(user, resource: Resource) -> bool:
    """仅上传者本人，或有审核权限的人。"""
    if not user or not user.is_authenticated:
        return False
    if can_moderate(user):
        return True
    return resource.uploader_id == user.pk


def can_download(user, resource: Resource) -> bool:
    """下载需登录。

    未审核的条目只有上传者本人与审核者能下。
    """
    if not user or not user.is_authenticated:
        return False
    if resource.is_approved:
        return True
    return can_edit(user, resource)


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

def visible_resources(user) -> QuerySet[Resource]:
    """当前访问者能看到哪些资源。

    - 游客 / 普通登录用户：只看已审核。
    - 上传者：额外能看到自己待审核的投稿。
    - 有审核权限者：全部。
    """
    queryset = Resource.objects.select_related("uploader")
    if can_moderate(user):
        return queryset
    if user and user.is_authenticated:
        return queryset.filter(Q(is_approved=True) | Q(uploader=user))
    return queryset.approved()


def approved_categories() -> list[dict]:
    """已审核资源的分类清单（去重 + 计数），给前端渲染筛选条用。

    **只数已审核的条目**：未审核投稿只对上传者本人与审核者可见，把它们算进
    公开的分类计数等于告诉所有人「有人投了一条 XX 分类的稿还没过审」。
    空分类（`category=""`）不出现在清单里。按条数倒序、同数按名字排，顺序稳定。
    """
    rows = (
        Resource.objects.approved()
        .exclude(category="")
        .values("category")
        .annotate(count=Count("id"))
    )
    return sorted(
        ({"category": row["category"], "count": row["count"]} for row in rows),
        key=lambda item: (-item["count"], item["category"]),
    )


# --------------------------------------------------------------------------
# 校验与落库
# --------------------------------------------------------------------------

def extension_parts(filename: str) -> list[str]:
    """把文件名拆成全部后缀段并归一化（小写、去空白与不可见字符、全角折半角）。

    **不能直接用 `Path.suffixes`**（这是本函数存在的理由，别改回去）：
    - Python 3.12 的 `Path.suffixes` 对「结尾是点」的名字（`木马.exe.`）和「只有前导点」的
      名字（`.exe`）都返回空列表，黑名单直接落空；
    - 尾随空白/制表符/不换行空格会粘在后缀上（`木马.exe `），黑名单比对不中，
      但 Django 落盘时 `get_valid_filename()` 会把它们去掉，文件又变回真正的 `.exe`。
    """
    name = unicodedata.normalize("NFKC", str(filename or "")).replace("\x00", "")
    parts = (_INVISIBLE_CHARS.sub("", part).strip().lower() for part in name.split(".")[1:])
    return [part for part in parts if part]


def assert_extension_allowed(filename: str) -> None:
    """扩展名黑名单校验。

    逐段检查全部后缀，`payload.js.txt` 这类双扩展名也会被拒。
    注意：这是黑名单而不是魔数校验——资源区收的是任意跑团材料（pdf/zip/图片/压缩包…），
    没有可枚举的白名单；真正的安全边界是「下发时一律 attachment + nosniff，且不走直出目录」。
    """
    hit = next((s for s in extension_parts(filename) if s in BLOCKED_EXTENSIONS), None)
    if hit:
        raise BlockedFileType(f"资源区不接受 .{hit} 等类型的文件。")


def download_filename(resource: Resource) -> str:
    """下发时给浏览器的文件名：用标题 + 存储后缀，避免暴露随机存储名。"""
    suffix = Path(resource.file.name).suffix
    safe = _UNSAFE_FILENAME_CHARS.sub("_", resource.title).strip() or "resource"
    if not suffix:
        # 存储名没有后缀时，下发名完全由标题决定，标题里的「.exe」会直接变成扩展名。
        # 黑名单管不到标题，所以这里把点号掐掉。
        safe = safe.replace(".", "_")
    return f"{safe[:80]}{suffix}"


def create_resource(*, uploader, **fields) -> Resource:
    """新建资源。

    站主（以及任何被授予审核权限的人）自己传的默认已审核；
    只有上传权限、没有审核权限的人（将来的「头衔」用户）投稿后待审。
    """
    resource = Resource(uploader=uploader, is_approved=can_moderate(uploader), **fields)
    _sync_kind_fields(resource)
    resource.full_clean(exclude=["uploader"])
    resource.save()
    return resource


#: 换掉这些字段 = 换了资源本体，非审核者改完要重新排队。
_CONTENT_FIELDS = frozenset({"kind", "file", "url"})


def update_resource(resource: Resource, *, editor, **fields) -> Resource:
    """改资源。非审核者换掉文件/外链后，条目重新进入待审。"""
    content_changed = any(
        name in _CONTENT_FIELDS and getattr(resource, name) != value for name, value in fields.items()
    )
    for name, value in fields.items():
        setattr(resource, name, value)
    _sync_kind_fields(resource)
    if content_changed and not can_moderate(editor):
        resource.is_approved = False
    resource.full_clean(exclude=["uploader"])
    resource.save()
    return resource


def _sync_kind_fields(resource: Resource) -> None:
    """kind 变了就把另一侧清掉，别留下孤儿文件路径或死链。"""
    if resource.kind == ResourceKind.FILE:
        resource.url = ""
    else:
        resource.file = None
