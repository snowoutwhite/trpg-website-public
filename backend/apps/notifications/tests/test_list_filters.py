"""通知列表的 `?event=` 筛选。

前端通知面板原先一次拉 100 条再本地按事件过滤，超过 100 条的旧通知就筛不到；
改成服务端筛之后分页照常、计数是筛后的总数。
"""

from __future__ import annotations

import pytest

from apps.notifications import events
from apps.notifications.services import notify

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/notifications/"


@pytest.fixture
def inbox(user_factory):
    me = user_factory(nickname="收件人")
    other = user_factory(nickname="别人")
    notify(me, events.REVIEW_OPENED, payload={"message": "去评价"})
    notify(me, events.SIGNUP_RESULT, payload={"message": "报名结果一"})
    notify(me, events.SIGNUP_RESULT, payload={"message": "报名结果二"})
    notify(other, events.SIGNUP_RESULT, payload={"message": "别人的"})
    return me


def _events(response) -> list[str]:
    return [row["event"] for row in response.json()["results"]]


def test_event筛选命中且只含本人(api_client, inbox):
    api_client.force_authenticate(inbox)
    response = api_client.get(f"{LIST_URL}?event={events.SIGNUP_RESULT}")
    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert set(_events(response)) == {events.SIGNUP_RESULT}


@pytest.mark.parametrize("value", ["no_such_event", "SIGNUP_RESULT", "__other__", "' OR 1=1"])
def test_event非法值静默忽略(api_client, inbox, value):
    api_client.force_authenticate(inbox)
    response = api_client.get(f"{LIST_URL}?event={value}")
    assert response.status_code == 200
    assert response.json()["count"] == 3


def test_event与unread可叠加(api_client, inbox):
    from apps.notifications.models import Notification
    from apps.notifications.services import mark_read

    first = Notification.objects.filter(recipient=inbox, event=events.SIGNUP_RESULT).first()
    mark_read(inbox, [first.pk])
    api_client.force_authenticate(inbox)
    body = api_client.get(f"{LIST_URL}?event={events.SIGNUP_RESULT}&unread=1").json()
    assert body["count"] == 1


def test_event筛选分页计数是筛后总数(api_client, inbox):
    api_client.force_authenticate(inbox)
    body = api_client.get(f"{LIST_URL}?event={events.SIGNUP_RESULT}&page_size=1").json()
    assert body["count"] == 2
    assert body["next"] is not None
