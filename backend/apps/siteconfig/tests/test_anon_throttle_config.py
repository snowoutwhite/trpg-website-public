"""业务规则与安全约束。"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

from apps.siteconfig.services import clear_config_cache, get_config

pytestmark = pytest.mark.django_db

HEALTH = "/api/v1/health/"


@pytest.fixture
def anon_rate_on(monkeypatch):
    # 测试环境默认把 anon 设为 None（关闭）；这里打开兜底值，让可配置类真的去读配置表。
    # 与 common/tests 的 throttle_rates 夹具同法：替换类属性，override_settings 对限速无效。
    rates = {**SimpleRateThrottle.THROTTLE_RATES, "anon": "60/min"}
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", rates)
    cache.clear()
    yield
    cache.clear()


def _set_limit(n: int) -> None:
    config = get_config()
    config.anon_throttle_per_minute = n
    config.save(update_fields=["anon_throttle_per_minute", "updated_at"])
    clear_config_cache()


def test_默认值是60(db):
    assert get_config().anon_throttle_per_minute == 60


def test_后台改数立即生效_不用重启(api_client, anon_rate_on):
    _set_limit(2)
    assert api_client.get(HEALTH).status_code == 200
    assert api_client.get(HEALTH).status_code == 200
    third = api_client.get(HEALTH)
    assert third.status_code == 429, "第 3 次游客请求应被每分钟 2 次的配置拦住"
    assert third.json()["error"]["code"] == "throttled"

    _set_limit(5)  # 站长在后台调大：同一分钟内立刻放行
    assert api_client.get(HEALTH).status_code == 200


def test_登录用户不受游客限速影响(api_client, user_factory, anon_rate_on):
    _set_limit(1)
    api_client.force_authenticate(user_factory(nickname="登录不限"))
    for _ in range(3):
        assert api_client.get(HEALTH).status_code == 200


def test_测试环境anon为None时限速关闭(api_client):
    _set_limit(1)
    for _ in range(3):
        assert api_client.get(HEALTH).status_code == 200
