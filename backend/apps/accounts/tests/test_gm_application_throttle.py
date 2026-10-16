"""GM 申请接口的限速只套 POST：GET 是「账户与通知」面板每次打开都发的读请求。"""

from __future__ import annotations

import pytest
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

GM_URL = "/api/v1/accounts/me/gm-application/"


@pytest.fixture
def throttle_rates(monkeypatch):
    """只打开指定的限速档（与 `test_adversarial_me.py` 同一做法：`override_settings` 改不动
    `SimpleRateThrottle.THROTTLE_RATES`，它在类定义时就绑死了那个 dict）。"""

    def apply(**rates):
        base = {
            "anon": None,
            "user": None,
            "upload": None,
            "gm_application": None,
            "nickname_change": None,
        }
        base.update(rates)
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", base)

    return apply


def test_读申请状态不占提交配额(api_client, user_factory, throttle_rates):
    throttle_rates(gm_application="5/day")
    user = user_factory(nickname="常看面板")
    api_client.force_authenticate(user)

    # 远超 5/天：读一律 200
    for _ in range(8):
        assert api_client.get(GM_URL).status_code == 200

    # 读过 8 次后提交仍然可以（配额没被读吃掉）
    first = api_client.post(GM_URL, {"reason": "想开团"}, format="json")
    assert first.status_code == 201


def test_提交仍受gm_application限速(api_client, user_factory, throttle_rates):
    throttle_rates(gm_application="5/day")
    user = user_factory(nickname="狂点提交")
    api_client.force_authenticate(user)

    statuses = [
        api_client.post(GM_URL, {"reason": "想开团"}, format="json").status_code for _ in range(6)
    ]
    # 第 1 次 201，之后重复申请 400，第 6 次撞到 5/天 → 429（限速在视图逻辑之前判）
    assert statuses[0] == 201
    assert set(statuses[1:5]) == {400}
    assert statuses[5] == 429
    # 被限速的是写，读照常
    assert api_client.get(GM_URL).status_code == 200
