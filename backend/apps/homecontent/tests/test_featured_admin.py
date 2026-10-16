"""业务规则与安全约束。"""

from __future__ import annotations

import pytest

from apps.gallery import services as gallery_services
from apps.homecontent import services
from apps.homecontent.views import FEATURED_PHOTO_LIMIT

pytestmark = pytest.mark.django_db

ADMIN_LIST = "/api/v1/home/admin/featured-photos/"
CANDIDATES = "/api/v1/home/admin/featured-photos/candidates/"


def test_站主侧精选列表不套首页上限(api_client, staff_user, public_photo, site_config):
    photos = [public_photo() for _ in range(FEATURED_PHOTO_LIMIT + 1)]
    for photo in photos:
        services.set_photo_featured(photo, True)
    site_config.featured_photos_enabled = True
    site_config.save()

    api_client.force_authenticate(staff_user)
    admin_rows = api_client.get(ADMIN_LIST).json()
    assert len(admin_rows) == FEATURED_PHOTO_LIMIT + 1

    # 首页门面仍然只给上限那么多
    home_rows = api_client.get("/api/v1/home/").json()["featured_photos"]["results"]
    assert len(home_rows) == FEATURED_PHOTO_LIMIT


def test_候选池只列已公开照片并带精选现状(api_client, staff_user, public_photo):
    featured = public_photo()
    plain = public_photo()
    hidden = public_photo()
    services.set_photo_featured(featured, True)
    gallery_services.take_down_photo(hidden, reason="下架的不该出现在候选里")

    api_client.force_authenticate(staff_user)
    response = api_client.get(CANDIDATES)
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"count", "results"}
    rows = {row["id"]: row for row in body["results"]}
    assert set(rows) == {featured.pk, plain.pk}
    assert rows[featured.pk]["is_featured"] is True
    assert rows[plain.pk]["is_featured"] is False
    # 字节走相册的鉴权出口，不走首页那条只放行「已精选」的出口
    assert rows[plain.pk]["thumbnail_url"].endswith(f"/api/v1/gallery/photos/{plain.pk}/file/?size=thumb")
    assert "uploader" not in rows[plain.pk]
    assert set(rows[plain.pk]) == {
        "id", "caption", "game_id", "game_title", "width", "height",
        "thumbnail_url", "preview_url", "is_featured", "created_at",
    }


def test_候选池按团筛选_不合法团号给空页(api_client, staff_user, public_photo):
    first = public_photo()
    second = public_photo()  # 另一个团（fixture 每次新建 GM 与团）
    assert first.game_id != second.game_id

    api_client.force_authenticate(staff_user)
    only_first = api_client.get(CANDIDATES, {"game": first.game_id}).json()["results"]
    assert [row["id"] for row in only_first] == [first.pk]
    for bad in ("abc", "-1", "99999999999999999999"):
        assert api_client.get(CANDIDATES, {"game": bad}).json()["results"] == []


def test_候选池分页最新在前(api_client, staff_user, public_photo):
    photos = [public_photo() for _ in range(3)]
    api_client.force_authenticate(staff_user)
    page = api_client.get(CANDIDATES, {"page_size": 2}).json()
    assert page["count"] == 3
    assert [row["id"] for row in page["results"]] == [photos[2].pk, photos[1].pk]


def test_候选池只有站主能看(api_client, user_factory, public_photo):
    public_photo()
    assert api_client.get(CANDIDATES).status_code == 401
    api_client.force_authenticate(user_factory(nickname="路人"))
    assert api_client.get(CANDIDATES).status_code == 403
    gm = user_factory(nickname="非站主GM")
    gm.is_gm = True
    gm.save(update_fields=["is_gm"])
    api_client.force_authenticate(gm)
    assert api_client.get(CANDIDATES).status_code == 403
