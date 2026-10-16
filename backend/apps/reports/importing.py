"""战报「从文档导入」：把 .docx / .txt 转成 Markdown 正文，**不落库、不建附件**。"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field

from apps.charactercards.validators import (
    CardFileTooLarge,
    InvalidCardFile,
    validate_card_file,
)
from apps.reports.models import BODY_MAX_LENGTH
from common.exceptions import ApiError
from common.text import BIDI_CONTROL_CLASS

# 单个导入文件的上限：与附件 / 角色卡同一个 20 MB。
IMPORT_MAX_BYTES = 20 * 1024 * 1024
IMPORT_EXTENSIONS = ("docx", "txt")

# docx 解压闸：解压总量、成员数、单成员压缩比（仅对解压后超过 1 MB 的成员判比例，
# 正常 Word 文档的 XML 压缩比一般在几倍到几十倍，小成员判比例只会误伤）。
DOCX_MAX_UNCOMPRESSED = 50 * 1024 * 1024
DOCX_MAX_MEMBERS = 2000
DOCX_MAX_RATIO = 100
DOCX_RATIO_MIN_SIZE = 1024 * 1024

TXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk")

# 控制字符：C0（保留 \t \n）+ DEL + C1；\r 在换行归一化时已经处理掉。
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BIDI_RE = re.compile(f"[{BIDI_CONTROL_CLASS}]")
_SAFE_HREF_RE = re.compile(r"^(?:https?://|mailto:)[^\s<>()\"'`\\]+$", re.IGNORECASE)

# 只转换这些标签；其余标签剥掉、保留文字（markdownify 的 `convert` 白名单）。
_CONVERT_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br",
    "strong", "b", "em", "i",
    "ul", "ol", "li",
    "blockquote",
    "a",
    "table", "thead", "tbody", "tr", "th", "td",
]

WARN_IMAGES_DROPPED = "文档中的图片没有导入。如果需要展示图片，请把图片作为附件上传。"
WARN_TABLES = "文档中的表格已尽量转换为表格格式，排版可能与原文不同，请在预览中核对。"
WARN_LINKS_DROPPED = "部分链接的网址无法使用，已只保留链接文字。"
WARN_CONTROLS_REMOVED = "文件中有一些不可见的特殊字符，已自动去除。"
WARN_GBK = "这份文本文件不是 UTF-8 编码，已按简体中文（GBK）编码读取。如果预览中出现乱码，请把文件另存为 UTF-8 编码后重新导入。"
WARN_EMPTY = "没有从文件中读到文字内容。"


class ImportUnsupportedFile(ApiError):
    default_code = "import_unsupported_file"
    default_detail = "只能导入 Word 文档（.docx）或纯文本文件（.txt）。"


class ImportUnreadable(ApiError):
    default_code = "import_unreadable"
    default_detail = (
        "这份文档无法读取，可能已经损坏。请用 Word 或 WPS 打开后重新另存为 .docx 文件，再导入一次。"
    )


class ImportUnknownEncoding(ApiError):
    default_code = "import_unknown_encoding"
    default_detail = (
        "无法识别这份文本文件的编码。请用记事本等工具打开文件，另存为 UTF-8 编码后重新导入。"
    )


class ImportTooLarge(ApiError):
    default_code = "import_document_too_large"
    default_detail = (
        "这份文档展开后的内容过大，无法导入。请删除文档中的大图片，或把文档拆成几份后再试。"
    )


@dataclass
class ImportResult:
    body_markdown: str
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def import_document(uploaded_file) -> ImportResult:
    """入口：按扩展名分派，返回转换好的正文（未截断前已清洗、已转义）。"""
    name = posixpath.basename(str(getattr(uploaded_file, "name", "") or "")).strip()
    extension = posixpath.splitext(name)[1].lower().lstrip(".")
    if extension not in IMPORT_EXTENSIONS:
        raise ImportUnsupportedFile()

    warnings: list[str] = []
    if extension == "docx":
        validate_card_file(uploaded_file, max_bytes=IMPORT_MAX_BYTES)
        _check_zip_budget(uploaded_file)
        text = _docx_to_markdown(uploaded_file, warnings)
    else:
        text = _txt_to_markdown(uploaded_file, warnings)

    text = _clean(text, warnings)
    text, truncated = _truncate(text)
    if not text.strip():
        warnings.append(WARN_EMPTY)
    return ImportResult(body_markdown=text, truncated=truncated, warnings=warnings)


# ---------------------------------------------------------------------------
# docx
# ---------------------------------------------------------------------------


def _check_zip_budget(uploaded_file) -> None:
    uploaded_file.seek(0)
    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ImportUnreadable() from exc
    finally:
        uploaded_file.seek(0)

    if len(infos) > DOCX_MAX_MEMBERS:
        raise ImportTooLarge()
    total = 0
    for info in infos:
        total += info.file_size
        if total > DOCX_MAX_UNCOMPRESSED:
            raise ImportTooLarge()
        if info.file_size > DOCX_RATIO_MIN_SIZE:
            if info.compress_size <= 0 or info.file_size / info.compress_size > DOCX_MAX_RATIO:
                raise ImportTooLarge()


def _docx_to_markdown(uploaded_file, warnings: list[str]) -> str:
    import mammoth
    from markdownify import ATX, MarkdownConverter

    seen = {"images": 0, "links_dropped": 0}

    def drop_image(image):
        # mammoth 的 convert_image 回调返回 HTML 节点列表；空列表 = 这张图什么都不输出，
        # 也不读图片字节（默认的 data_uri 会把整张图 base64 进 HTML）。
        seen["images"] += 1
        return []

    class _Converter(MarkdownConverter):
        def process_text(self, el, parent_tags=None):
            # 放在 process_text 而不是 escape：escape 在 pre / code 里会被跳过
            return _escape_angle(super().process_text(el, parent_tags=parent_tags))

        def convert_a(self, el, text, parent_tags):
            href = (el.get("href") or "").strip()
            if href and not _SAFE_HREF_RE.match(href):
                if not href.startswith("#"):  # 文内锚点（脚注）静默降级，不算「丢了链接」
                    seen["links_dropped"] += 1
                el.attrs.pop("href", None)
            el.attrs.pop("title", None)
            return super().convert_a(el, text, parent_tags)

    uploaded_file.seek(0)
    try:
        result = mammoth.convert_to_html(
            uploaded_file,
            convert_image=drop_image,
            include_embedded_style_map=False,
        )
        html = result.value
        markdown = _Converter(
            convert=_CONVERT_TAGS,
            heading_style=ATX,
            bullets="-",
            autolinks=False,
            table_infer_header=True,
        ).convert(html)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - mammoth / XML 解析的异常种类不收敛，一律按「读不了」处理
        raise ImportUnreadable() from exc
    finally:
        uploaded_file.seek(0)

    if seen["images"]:
        warnings.append(WARN_IMAGES_DROPPED)
    if "<table" in html:
        warnings.append(WARN_TABLES)
    if seen["links_dropped"]:
        warnings.append(WARN_LINKS_DROPPED)
    return markdown


# ---------------------------------------------------------------------------
# txt
# ---------------------------------------------------------------------------


def _txt_to_markdown(uploaded_file, warnings: list[str]) -> str:
    size = getattr(uploaded_file, "size", None)
    if size is not None and size > IMPORT_MAX_BYTES:
        raise CardFileTooLarge(f"单个文件不能超过 {IMPORT_MAX_BYTES // 1024 // 1024} MB。")
    uploaded_file.seek(0)
    raw = uploaded_file.read(IMPORT_MAX_BYTES + 1)
    uploaded_file.seek(0)
    if len(raw) > IMPORT_MAX_BYTES:
        raise CardFileTooLarge(f"单个文件不能超过 {IMPORT_MAX_BYTES // 1024 // 1024} MB。")
    if not raw:
        raise InvalidCardFile("这个文件内容为空。")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        # UTF-16（记事本旧版的「Unicode」）：不在支持的编码里，明确让用户另存
        raise ImportUnknownEncoding()
    if b"\x00" in raw:
        # 纯文本不会有 NUL；有就是改了后缀的二进制文件
        raise InvalidCardFile("文件内容与后缀不符，请更换文件。")

    text = None
    for encoding in TXT_ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "gbk":
            warnings.append(WARN_GBK)
        break
    if text is None:
        raise ImportUnknownEncoding()
    # 文本文件按 Markdown 解释（用户可能本来就按 Markdown 写），只转义尖括号挡住内联 HTML；
    # 但记事本写的战报通常「一行一段」，Markdown 的单换行会把整篇并成一段，所以逐行分段
    return _escape_angle(_one_line_one_paragraph(text))


def _one_line_one_paragraph(text: str) -> str:
    """单换行 → 空一行；连续的 `|` 开头的行（Markdown 表格）保持相连，不拆。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for index, line in enumerate(lines):
        out.append(line)
        if index == len(lines) - 1:
            break
        following = lines[index + 1]
        if line.lstrip().startswith("|") and following.lstrip().startswith("|"):
            out.append("\n")
        else:
            out.append("\n\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# 共用收尾
# ---------------------------------------------------------------------------


def _escape_angle(text: str) -> str:
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _clean(text: str, warnings: list[str]) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _BIDI_RE.sub("", _CONTROL_RE.sub("", text))
    if cleaned != text:
        warnings.append(WARN_CONTROLS_REMOVED)
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip("\n")


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= BODY_MAX_LENGTH:
        return text, False
    cut = text[:BODY_MAX_LENGTH]
    # 尽量断在段落 / 行边界上；最后 2000 字内找不到换行就硬切
    boundary = cut.rfind("\n", BODY_MAX_LENGTH - 2000)
    if boundary > 0:
        cut = cut[:boundary]
    # 别把转义实体切成半截（`&l` 之类）
    cut = re.sub(r"&[a-z]{0,3}$", "", cut)
    return cut.rstrip(), True
