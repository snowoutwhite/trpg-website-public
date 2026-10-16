"""文件白名单、魔数、大小、版本保留 3 版。"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.charactercards.models import CharacterCardFile
from apps.charactercards.services import add_file_version, prune_old_versions
from apps.charactercards.validators import (
    CardFileTooLarge,
    InvalidCardFile,
    validate_card_file,
)

from .conftest import (
    EXE_BYTES,
    JPG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    TXT_BYTES,
    XLS_BYTES,
    ooxml_bytes,
    plain_zip_bytes,
    upload,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("卡.pdf", PDF_BYTES),
        ("卡.xlsx", ooxml_bytes("xlsx")),
        ("卡.docx", ooxml_bytes("docx")),
        ("卡.xls", XLS_BYTES),
        ("卡.txt", TXT_BYTES),
        ("卡.png", PNG_BYTES),
        ("卡.jpg", JPG_BYTES),
    ],
)
def test_白名单内的格式可以通过(name, data):
    result = validate_card_file(upload(name, data))
    assert result.size == len(data)
    assert result.original_name == name


def test_白名单外的扩展名被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("木马.exe", EXE_BYTES))


def test_无扩展名被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("卡", PDF_BYTES))


def test_魔数与扩展名不符被拒():
    # 内容是 PNG，却叫 .pdf —— 扩展名不可信，读魔数才拒得掉
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("伪装.pdf", PNG_BYTES))


def test_可执行文件改名成pdf被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("木马.pdf", EXE_BYTES))


def test_不信任上传端声明的content_type():
    # content_type 说自己是 pdf，实际是可执行文件
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("骗人的.pdf", EXE_BYTES, content_type="application/pdf"))


def test_普通zip改名成xlsx被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("伪装.xlsx", plain_zip_bytes()))


def test_docx内容改名成xlsx被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("错配.xlsx", ooxml_bytes("docx")))


def test_txt必须是可解码的UTF8():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("乱码.txt", b"\xff\xfe\x00\x01\x80\x81"))


def test_空文件被拒():
    with pytest.raises(InvalidCardFile):
        validate_card_file(upload("空.pdf", b""))


def test_超过大小上限被拒():
    big = PDF_BYTES + b"0" * 2048
    with pytest.raises(CardFileTooLarge):
        validate_card_file(upload("大.pdf", big), max_bytes=1024)


def test_超大txt也被拒而不是先去解码():
    with pytest.raises(CardFileTooLarge):
        validate_card_file(upload("大.txt", b"a" * 4096), max_bytes=1024)


def test_默认上限是20MB():
    from apps.charactercards.validators import CARD_FILE_MAX_BYTES

    assert CARD_FILE_MAX_BYTES == 20 * 1024 * 1024


def test_版本号递增且只保留最近三版(card_factory, user_factory):
    card = card_factory()
    paths = []
    for index in range(5):
        version = add_file_version(
            card, upload(f"卡{index}.pdf", PDF_BYTES + bytes([index])), uploaded_by=card.owner
        )
        paths.append(version.file.path)

    versions = list(
        CharacterCardFile.objects.filter(card=card).order_by("version").values_list("version", flat=True)
    )
    assert versions == [3, 4, 5]

    assert not any(Path(path).exists() for path in paths[:2]), "超出保留数的旧版文件应连同落盘文件一起删掉"
    assert all(Path(path).exists() for path in paths[2:])


def test_换文件不影响参团记录(card_factory):
    from apps.charactercards.services import games_played_for, record_play

    card = card_factory()
    add_file_version(card, upload("v1.pdf", PDF_BYTES), uploaded_by=card.owner)
    record_play(card, 101)
    add_file_version(card, upload("v2.pdf", PDF_BYTES), uploaded_by=card.owner)

    card.refresh_from_db()
    assert card.play_count == 1
    assert [item["game_id"] for item in games_played_for(card)] == [101]


def test_GM代传标记落在版本上(card_factory, user_factory):
    card = card_factory()
    gm = user_factory(nickname="代传的GM", is_gm=True)
    version = add_file_version(
        card, upload("代传.pdf", PDF_BYTES), uploaded_by=gm, uploaded_by_gm=True
    )
    assert version.uploaded_by_gm is True
    assert version.uploaded_by == gm
    assert version.card.owner == card.owner, "GM 代传的卡仍归 PL"


def test_存储路径不可猜且落在受保护目录(card_factory):
    card = card_factory()
    version = add_file_version(card, upload("我的卡.pdf", PDF_BYTES), uploaded_by=card.owner)
    assert version.file.name.startswith("protected/charactercards/")
    assert "我的卡" not in version.file.name
    assert len(version.file.name.rsplit("/", 1)[-1]) == len("0123456789abcdef0123456789abcdef.pdf")


def test_prune可单独调用且幂等(card_factory):
    card = card_factory()
    for index in range(4):
        add_file_version(card, upload(f"v{index}.pdf", PDF_BYTES), uploaded_by=card.owner)
    assert prune_old_versions(card) == 0
    assert CharacterCardFile.objects.filter(card=card).count() == 3
