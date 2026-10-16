"""pytest 全局夹具。"""

from __future__ import annotations

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清缓存：siteconfig 单例与 allauth 限速计数都存在缓存里，会串味。"""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user_factory(db):
    """造一个已验证邮箱的普通用户。"""
    from allauth.account.models import EmailAddress

    from apps.accounts.models import User

    counter = {"n": 0}

    def make(*, nickname: str | None = None, email: str | None = None, password: str = "testpass1234", **extra):
        counter["n"] += 1
        nickname = nickname or f"玩家{counter['n']}"
        email = email or f"user{counter['n']}@example.com"
        user = User.objects.create_user(email=email, nickname=nickname, password=password, **extra)
        EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
        return user

    return make


@pytest.fixture
def site_config(db):
    from apps.siteconfig.services import get_config

    return get_config()
