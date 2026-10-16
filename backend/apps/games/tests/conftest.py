"""团测试的共用夹具。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


def upload(name: str = "卡.pdf", data: bytes = PDF_BYTES):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


def soon(**kwargs):
    return timezone.now() + timedelta(**kwargs)


def ago(**kwargs):
    return timezone.now() - timedelta(**kwargs)


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件留在仓库里。"""
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


@pytest.fixture
def gm_factory(db, user_factory):
    """造一个 GM 身份的用户。"""

    def make(**kwargs):
        user = user_factory(**kwargs)
        user.is_gm = True
        user.save(update_fields=["is_gm"])
        return user

    return make


@pytest.fixture
def game_factory(db, gm_factory):
    """造一个默认「7 天后开团、先到先得、需要交卡、上限 5 人」的团。"""
    from apps.games import services

    def make(gm=None, *, tags=None, **kwargs):
        gm = gm or gm_factory()
        kwargs.setdefault("title", "深潜者之夏")
        kwargs.setdefault("rule_system", "COC")
        kwargs.setdefault("start_at", soon(days=7))
        kwargs.setdefault("min_players", 1)
        kwargs.setdefault("max_players", 5)
        return services.create_game(gm, tags=tags, **kwargs)

    return make


@pytest.fixture
def card_factory(db):
    """造一张角色卡；默认私密、带一个文件版本。"""
    from apps.charactercards import services as card_services

    def make(owner, *, with_file: bool = True, **kwargs):
        kwargs.setdefault("name", "无名调查员")
        kwargs.setdefault("rule_system", "COC")
        card = card_services.create_card(owner, **kwargs)
        if with_file:
            card_services.add_file_version(card, upload(), uploaded_by=owner)
        return card

    return make


@pytest.fixture
def signed_up(db, game_factory, user_factory):
    """造「一个团 + 一个已报名的 PL」。"""
    from apps.games import services

    def make(game=None, player=None, **game_kwargs):
        game = game or game_factory(**game_kwargs)
        player = player or user_factory()
        return game, player, services.signup(game, player)

    return make
