"""User 管理器：以邮箱为唯一登录标识。"""

from __future__ import annotations

from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, nickname: str, password: str | None, **extra):
        if not email:
            raise ValueError("必须提供邮箱")
        if not nickname:
            raise ValueError("必须提供昵称")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, nickname=nickname, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, nickname: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, nickname, password, **extra)

    def create_superuser(self, email: str, nickname: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("超级用户必须 is_staff=True 且 is_superuser=True")
        return self._create_user(email, nickname, password, **extra)
