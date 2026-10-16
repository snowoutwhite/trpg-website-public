"""对抗性测试 · 战报「从文档导入」。

红队纪律（安全测试规则）：每条都是能复现的攻击面。

1. 伪装文件：改名的非 docx、改名的 zip、二进制改名 txt、UTF-16 txt、空文件、超 20 MB、非白名单后缀
2. 解压炸弹：高压缩比成员、解压总量超限、XML 实体膨胀（billion laughs）
3. 输出净化：`<script>` / 内联 HTML 被转义、双向控制与控制字符被剥、危险链接降级
4. 限速：走 `upload` 档
"""

from __future__ import annotations

import io
import struct
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle

from apps.reports.importing import IMPORT_MAX_BYTES

pytestmark = pytest.mark.django_db

URL = reverse("v1:reports:report-import-document")

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def handmade_docx(document_xml: str, extra: dict[str, bytes] | None = None) -> bytes:
    """用 zipfile 手搓最小 docx：对抗用例要造畸形包，python-docx 造不出来。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/document.xml", document_xml)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def paragraphs_xml(*texts: str) -> str:
    from xml.sax.saxutils import escape

    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(t)}</w:t></w:r></w:p>" for t in texts)
    return f'<?xml version="1.0" encoding="UTF-8"?><w:document {W_NS}><w:body>{body}</w:body></w:document>'


def upload(name: str, data: bytes):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


@pytest.fixture
def client_in_game(api_client, game_factory, attendee_factory):
    game = game_factory()
    user = attendee_factory(game)
    api_client.force_authenticate(user)

    def post(name: str, data: bytes):
        return api_client.post(URL, {"game": game.pk, "file": upload(name, data)}, format="multipart")

    return post


def code_of(response) -> str:
    return response.json()["error"]["code"]


# ---------------------------------------------------------------------------
# 1. 伪装文件
# ---------------------------------------------------------------------------


def test_改名成docx的PDF被拒(client_in_game):
    response = client_in_game("战报.docx", b"%PDF-1.7\n%%EOF\n")
    assert response.status_code == 400
    assert code_of(response) == "invalid_card_file"


def test_改名成docx的普通zip被拒(client_in_game):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    response = client_in_game("战报.docx", buffer.getvalue())
    assert response.status_code == 400
    assert code_of(response) == "invalid_card_file"


def test_有OOXML外壳但内容坏掉的docx回400不是500(client_in_game):
    response = client_in_game("战报.docx", handmade_docx("<w:document>没闭合"))
    assert response.status_code == 400
    assert code_of(response) == "import_unreadable"


def test_二进制改名成txt被拒(client_in_game):
    response = client_in_game("战报.txt", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00")
    assert response.status_code == 400


def test_UTF16文本明确要求另存(client_in_game):
    response = client_in_game("战报.txt", "雾港".encode("utf-16"))
    assert response.status_code == 400
    assert code_of(response) == "import_unknown_encoding"


@pytest.mark.parametrize("name", ["战报.pdf", "战报.md", "战报.html", "战报.docx.exe", "战报"])
def test_非docx_txt后缀一律拒(client_in_game, name):
    response = client_in_game(name, b"hello")
    assert response.status_code == 400
    assert code_of(response) == "import_unsupported_file"


@pytest.mark.parametrize("name", ["空.txt", "空.docx"])
def test_空文件被拒(client_in_game, name):
    response = client_in_game(name, b"")
    assert response.status_code == 400


@pytest.mark.parametrize("name", ["大.txt", "大.docx"])
def test_超20MB被拒(client_in_game, name):
    response = client_in_game(name, b"a" * (IMPORT_MAX_BYTES + 1))
    assert response.status_code == 400
    assert code_of(response) == "card_file_too_large"


# ---------------------------------------------------------------------------
# 2. 解压炸弹
# ---------------------------------------------------------------------------


def test_高压缩比成员的docx被拒(client_in_game):
    """30 MB 的零压成几十 KB：总量没超 50 MB，但压缩比远超 100。"""
    bomb = handmade_docx(paragraphs_xml("正常"), {"word/media/pad.bin": b"\x00" * (30 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024
    response = client_in_game("炸弹.docx", bomb)
    assert response.status_code == 400
    assert code_of(response) == "import_document_too_large"


def test_解压总量超50MB的docx被拒(client_in_game):
    """每个成员单独看压缩比不高，但总量超限。真造 50 MB 以上的内容文件本身就超 20 MB，
    所以这里伪造中央目录里的 file_size / compress_size —— 攻击者本来就能这么写。
    压缩比声明成 2 倍，确保拦下它的是「总量闸」而不是「压缩比闸」。"""
    data = handmade_docx(
        paragraphs_xml("正常"),
        {f"word/media/{i}.bin": b"x" for i in range(3)},
    )
    # 改写中央目录：每个 media 成员声明 压缩 10 MB → 解压 20 MB，三个合计 60 MB
    raw = bytearray(data)
    with zipfile.ZipFile(io.BytesIO(bytes(raw))) as archive:
        infos = archive.infolist()

    offset = raw.find(b"PK\x01\x02")
    for info in infos:
        name_len, extra_len, comment_len = struct.unpack("<HHH", raw[offset + 28 : offset + 34])
        if info.filename.startswith("word/media/"):
            raw[offset + 20 : offset + 24] = struct.pack("<I", 10 * 1024 * 1024)
            raw[offset + 24 : offset + 28] = struct.pack("<I", 20 * 1024 * 1024)
        offset += 46 + name_len + extra_len + comment_len
    response = client_in_game("总量.docx", bytes(raw))
    assert response.status_code == 400
    assert code_of(response) == "import_document_too_large"


def test_XML实体膨胀不会卡死而是400(client_in_game):
    lol = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lolololololololololol">'
        + "".join(
            f'<!ENTITY lol{i} "{("&lol" + (str(i - 1) if i > 1 else "") + ";") * 10}">' for i in range(1, 10)
        )
        + f"]><w:document {W_NS}><w:body><w:p><w:r><w:t>&lol9;</w:t></w:r></w:p></w:body></w:document>"
    )
    response = client_in_game("实体.docx", handmade_docx(lol))
    assert response.status_code == 400
    assert code_of(response) == "import_unreadable"


# ---------------------------------------------------------------------------
# 3. 输出净化
# ---------------------------------------------------------------------------


def test_txt里的script与内联HTML被转义(client_in_game):
    raw = '<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n<span style="x">字</span>'
    response = client_in_game("战报.txt", raw.encode())
    body = response.json()["body_markdown"]
    assert response.status_code == 200
    assert "<" not in body and ">" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_docx里的script文字被转义(client_in_game):
    data = handmade_docx(paragraphs_xml("<script>alert(1)</script>", '<a href="javascript:1">x</a>'))
    response = client_in_game("战报.docx", data)
    body = response.json()["body_markdown"]
    assert response.status_code == 200, response.content
    assert "<" not in body and ">" not in body
    assert "&lt;script&gt;" in body


def test_双向控制字符与控制字符被剥掉并提示(client_in_game):
    raw = "正‮文⁦反⁩转\x07铃\x1b[31m\t制表\n换行"
    response = client_in_game("战报.txt", raw.encode())
    data = response.json()
    body = data["body_markdown"]
    for bad in ("‮", "⁦", "⁩", "\x07", "\x1b"):
        assert bad not in body
    assert "\t制表\n\n换行" in body  # 制表符保留；换行保留（txt 逐行分段）
    assert any("特殊字符" in w for w in data["warnings"])


def test_docx里的双向控制字符同样被剥(client_in_game):
    response = client_in_game("战报.docx", handmade_docx(paragraphs_xml("坏‮报")))
    assert response.status_code == 200, response.content
    assert "‮" not in response.json()["body_markdown"]


def test_docx里的javascript链接降级为纯文字(client_in_game):
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document {W_NS} '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body><w:p><w:hyperlink r:id="rIdEvil"><w:r><w:t>点我</w:t></w:r></w:hyperlink>'
        '<w:hyperlink r:id="rIdGood"><w:r><w:t>官网</w:t></w:r></w:hyperlink></w:p></w:body></w:document>'
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdEvil" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="javascript:alert(1)" TargetMode="External"/>'
        '<Relationship Id="rIdGood" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.com/a_b" TargetMode="External"/>'
        "</Relationships>"
    )
    data = handmade_docx(document, {"word/_rels/document.xml.rels": doc_rels.encode()})
    response = client_in_game("链接.docx", data)
    body = response.json()["body_markdown"]
    assert response.status_code == 200, response.content
    assert "javascript" not in body.lower()
    assert "点我" in body
    assert "[官网](https://example.com/a_b)" in body
    assert any("链接" in w for w in response.json()["warnings"])


# ---------------------------------------------------------------------------
# 4. 限速
# ---------------------------------------------------------------------------


def test_导入走上传限速档(client_in_game, monkeypatch):
    monkeypatch.setattr(
        SimpleRateThrottle,
        "THROTTLE_RATES",
        {"anon": None, "user": None, "upload": "3/hour", "gm_application": None, "nickname_change": None},
    )
    codes = [client_in_game("战报.txt", b"x").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
