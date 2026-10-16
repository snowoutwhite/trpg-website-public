"""本人账号接口：隐私边界、昵称冷却、头像校验、GM 申请、注销匿名化。"""

from __future__ import annotations

import io

import pytest
from django.utils import timezone
from PIL import Image

from apps.accounts.models import ANONYMIZED_NICKNAME_PREFIX, GMApplication, NicknameHistory
from apps.accounts.services import NICKNAME_CHANGE_INTERVAL

pytestmark = pytest.mark.django_db

ME_URL = "/api/v1/accounts/me/"
NICKNAME_URL = "/api/v1/accounts/me/nickname/"
AVATAR_URL = "/api/v1/accounts/me/avatar/"
GM_URL = "/api/v1/accounts/me/gm-application/"
DEACTIVATE_URL = "/api/v1/accounts/me/deactivate/"


def image_bytes(fmt="PNG", size=(600, 400), color=(120, 30, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def upload(name: str, data: bytes, content_type: str):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, data, content_type=content_type)


def test_me只返回自己且含邮箱(api_client, user_factory):
    user = user_factory(email="mine@example.com", nickname="我自己")
    api_client.force_authenticate(user=user)
    data = api_client.get(ME_URL).json()
    assert data["email"] == "mine@example.com"
    assert data["nickname"] == "我自己"
    assert data["email_verified"] is True


def test_me不接受指定他人(api_client, user_factory):
    me = user_factory(nickname="甲")
    other = user_factory(nickname="乙", email="other@example.com")
    api_client.force_authenticate(user=me)
    # 接口根本不吃 id 参数，传了也只会返回自己
    data = api_client.get(f"{ME_URL}?id={other.pk}").json()
    assert data["id"] == me.pk
    assert data["email"] != other.email


def test_未登录不能访问me(api_client):
    # W5 状态码统一：未登录一律 401（原先被 DRF 的「无 WWW-Authenticate 头」降级成 403）
    assert api_client.get(ME_URL).status_code == 401


def test_改昵称成功并留痕(api_client, user_factory):
    user = user_factory(nickname="旧名")
    api_client.force_authenticate(user=user)
    response = api_client.post(NICKNAME_URL, {"nickname": "新名"}, format="json")
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.nickname == "新名"
    assert user.nickname_changed_at is not None
    assert NicknameHistory.objects.filter(user=user, old_nickname="旧名", new_nickname="新名").exists()


def test_改昵称30天内不可再改(api_client, user_factory):
    user = user_factory(nickname="一号")
    user.nickname_changed_at = timezone.now()
    user.save(update_fields=["nickname_changed_at"])
    api_client.force_authenticate(user=user)
    response = api_client.post(NICKNAME_URL, {"nickname": "二号"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "nickname_change_too_soon"
    user.refresh_from_db()
    assert user.nickname == "一号"


def test_改昵称满30天后可再改(api_client, user_factory):
    user = user_factory(nickname="甲甲")
    user.nickname_changed_at = timezone.now() - NICKNAME_CHANGE_INTERVAL
    user.save(update_fields=["nickname_changed_at"])
    api_client.force_authenticate(user=user)
    assert api_client.post(NICKNAME_URL, {"nickname": "乙乙"}, format="json").status_code == 200


def test_改昵称撞重名被拒(api_client, user_factory):
    user_factory(nickname="已存在")
    user = user_factory(nickname="想改名")
    api_client.force_authenticate(user=user)
    response = api_client.post(NICKNAME_URL, {"nickname": "已存在"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "nickname_taken"


def test_上传头像转webp并缩到256(api_client, user_factory):
    user = user_factory(nickname="有头像的")
    api_client.force_authenticate(user=user)
    response = api_client.post(
        AVATAR_URL,
        {"avatar": upload("a.png", image_bytes("PNG"), "image/png")},
        format="multipart",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.avatar.name.endswith(".webp")
    with user.avatar.open("rb") as fh:
        saved = Image.open(fh)
        assert saved.format == "WEBP"
        assert max(saved.size) <= 256


def test_头像拒绝非图片(api_client, user_factory):
    user = user_factory(nickname="传错的")
    api_client.force_authenticate(user=user)
    response = api_client.post(
        AVATAR_URL,
        {"avatar": upload("evil.png", b"this-is-not-an-image", "image/png")},
        format="multipart",
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert not user.avatar


def test_头像拒绝超大文件(api_client, user_factory, settings):
    settings.AVATAR_MAX_BYTES = 1024
    user = user_factory(nickname="传大的")
    api_client.force_authenticate(user=user)
    response = api_client.post(
        AVATAR_URL,
        {"avatar": upload("big.png", image_bytes("PNG", size=(2000, 2000)), "image/png")},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "image_too_large"


def test_申请GM并防重复(api_client, user_factory):
    user = user_factory(nickname="想当GM的")
    api_client.force_authenticate(user=user)
    response = api_client.post(GM_URL, {"reason": "跑过很多团，想开团"}, format="json")
    assert response.status_code == 201
    assert GMApplication.objects.filter(applicant=user, status="pending").count() == 1

    again = api_client.post(GM_URL, {"reason": "再申请一次"}, format="json")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "duplicate_gm_application"


def test_已是GM不能再申请(api_client, user_factory):
    user = user_factory(nickname="已经是GM")
    user.is_gm = True
    user.save()
    api_client.force_authenticate(user=user)
    response = api_client.post(GM_URL, {"reason": "重复申请"}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "already_gm"


def test_GM申请通过后建GM卡并发通知(user_factory):
    from apps.accounts.services import apply_for_gm, review_gm_application
    from apps.notifications import events
    from apps.notifications.models import Notification
    from apps.profiles.models import GMCard

    user = user_factory(nickname="待批的")
    staff = user_factory(nickname="站主", email="owner@example.com")
    application = apply_for_gm(user, "我有经验")
    review_gm_application(application, approved=True, reviewer=staff)

    user.refresh_from_db()
    assert user.is_gm is True
    assert GMCard.objects.filter(user=user).exists()
    assert Notification.objects.filter(
        recipient=user, event=events.GM_APPLICATION_RESULT
    ).exists()


def test_注销匿名化(api_client, user_factory):
    from allauth.account.models import EmailAddress

    user = user_factory(email="bye@example.com", nickname="要走了")
    api_client.force_authenticate(user=user)
    response = api_client.post(DEACTIVATE_URL, {}, format="json")
    assert response.status_code == 200

    user.refresh_from_db()
    assert user.email is None
    assert user.nickname == f"{ANONYMIZED_NICKNAME_PREFIX}#{user.pk}"
    assert user.is_active is False
    assert user.is_deactivated is True
    assert len(user.anonymized_email_hash) == 64
    assert not user.has_usable_password()
    assert not EmailAddress.objects.filter(user=user).exists()


def test_注销后个人空间不可见(api_client, user_factory):
    from apps.accounts.services import deactivate_account

    user = user_factory(nickname="消失的")
    deactivate_account(user)
    assert api_client.get(f"/api/v1/profiles/users/{user.pk}/").status_code == 404


def test_自动晋升GM按站点阈值(user_factory, site_config):
    from apps.accounts.services import maybe_promote_gm
    from apps.notifications import events
    from apps.notifications.models import Notification
    from apps.profiles.services import ensure_player_card

    user = user_factory(nickname="勤奋PL")
    card = ensure_player_card(user)

    card.games_played = site_config.gm_auto_promote_threshold - 1
    card.save()
    assert maybe_promote_gm(user) is False

    card.games_played = site_config.gm_auto_promote_threshold
    card.save()
    assert maybe_promote_gm(user) is True
    user.refresh_from_db()
    assert user.is_gm is True
    assert Notification.objects.filter(recipient=user, event=events.GM_AUTO_PROMOTED).exists()

    # 幂等：已是 GM 不再重复晋升
    assert maybe_promote_gm(user) is False
