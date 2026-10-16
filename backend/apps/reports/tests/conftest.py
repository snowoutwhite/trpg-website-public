"""战报测试的共用夹具。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


def upload(name: str = "战报附件.pdf", data: bytes = PDF_BYTES):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """每个用例一个干净的 MEDIA_ROOT，避免测试文件留在仓库里。"""
    settings.MEDIA_ROOT = tmp_path
    settings.PROTECTED_MEDIA_ROOT = tmp_path / settings.PROTECTED_MEDIA_DIRNAME
    return tmp_path


@pytest.fixture
def gm_factory(db, user_factory):
    def make(**kwargs):
        user = user_factory(**kwargs)
        user.is_gm = True
        user.save(update_fields=["is_gm"])
        return user

    return make


@pytest.fixture
def game_factory(db, gm_factory):
    """直接造团（不跑完整状态机），默认「已结团」。"""
    from apps.games.models import GAME_FINISHED, Game

    def make(gm=None, *, status: str = GAME_FINISHED, **kwargs):
        gm = gm or gm_factory()
        start_at = kwargs.pop("start_at", timezone.now() - timedelta(days=3))
        kwargs.setdefault("title", "深潜者之夏")
        kwargs.setdefault("rule_system", "COC")
        kwargs.setdefault("card_deadline", start_at)
        kwargs.setdefault(
            "finished_at", timezone.now() - timedelta(days=1) if status == GAME_FINISHED else None
        )
        return Game.objects.create(gm=gm, start_at=start_at, status=status, **kwargs)

    return make


@pytest.fixture
def attendee_factory(db, user_factory):
    """给某个团加一个「成功报团且到场」的 PL。"""
    from apps.games.models import SIGNUP_ACCEPTED, Signup

    def make(game, player=None, *, attended: bool = True, status: str = SIGNUP_ACCEPTED):
        player = player or user_factory()
        Signup.objects.create(
            game=game,
            player=player,
            order=game.signups.count() + 1,
            status=status,
            attended=attended,
        )
        return player

    return make


@pytest.fixture
def report_factory(db):
    """直接建一份战报（绕过提交条件，用来铺可见性用例）。"""
    from apps.reports.models import VISIBILITY_PUBLIC, Report

    def make(game, author, **kwargs):
        kwargs.setdefault("title", "第一次深潜")
        kwargs.setdefault("body_markdown", "# 标题\n正文")
        kwargs.setdefault("visibility", VISIBILITY_PUBLIC)
        return Report.objects.create(game=game, author=author, **kwargs)

    return make


@pytest.fixture
def moderator(db, user_factory):
    """持 `reports.moderate_report` 权限位的站主（不判断 is_superuser）。"""
    from django.contrib.auth.models import Permission

    user = user_factory(nickname="站主")
    user.user_permissions.add(Permission.objects.get(codename="moderate_report"))
    return type(user).objects.get(pk=user.pk)  # 刷掉权限缓存
