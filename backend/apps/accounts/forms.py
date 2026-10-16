"""注册表单扩展。

挂点说明（已核对本机 allauth 65.19.4 源码）：
- `settings.ACCOUNT_SIGNUP_FORM_CLASS` 指向本类；`allauth.account.internal.flows.signup.
  base_signup_form_class()` 会让 `BaseSignupForm` 继承它，而 headless 的
  `allauth.headless.account.inputs.SignupInput` 又继承 `BaseSignupForm`，
  所以这里声明的字段会自动出现在 `POST /_allauth/browser/v1/auth/signup` 的入参里。
- 用户保存后，`BaseSignupForm.save()` 会调用 `custom_signup()` → 本类的 `signup()`。
- 昵称不在 `signup()` 里写，而是在 `AccountAdapter.save_user()` 里于首次 save 前写入，
  避免空昵称触发唯一约束冲突。
"""

from __future__ import annotations

from django import forms
from django.db import transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.models import NICKNAME_MAX_LENGTH, InviteCode, User
from apps.accounts.validators import normalize_nickname
from apps.siteconfig.services import get_config


class SignupExtraFieldsForm(forms.Form):
    """注册时的站内附加字段：昵称必填，邀请码按站级开关决定是否必填。"""

    nickname = forms.CharField(label="昵称", max_length=NICKNAME_MAX_LENGTH)
    invite_code = forms.CharField(label="邀请码", max_length=32, required=False)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if "invite_code" in self.fields:
            self.fields["invite_code"].required = get_config().invite_code_required

    def clean_nickname(self) -> str:
        # 归一化规则与改昵称接口共用一份，见 apps/accounts/validators.py
        nickname = normalize_nickname(self.cleaned_data.get("nickname"))
        if User.objects.filter(nickname__iexact=nickname).exists():
            raise forms.ValidationError("该昵称已被占用。")
        return nickname

    def clean_invite_code(self) -> str:
        raw = (self.cleaned_data.get("invite_code") or "").strip()
        if not raw:
            return ""
        if not get_config().invite_code_required:
            # **开关关闭时邀请码不是准入条件，带了也当没带**：既不校验也不消耗

            # 原来照样 `used_count += 1`，于是任何人都能在开关关闭期间把站主
            # 备好的码池刷空 —— 等站主想打开开关时，码已经全废了。
            return ""
        code = InviteCode.objects.filter(code__iexact=raw).first()
        if code is None or not code.is_available():
            raise forms.ValidationError("邀请码无效或已失效。")
        self._invite_code = code
        return code.code

    def signup(self, request: HttpRequest, user: User) -> None:
        """allauth 在用户落库后调用。此处只做邀请码计数。"""
        code = getattr(self, "_invite_code", None)
        if code is None:
            return
        with transaction.atomic():
            updated = InviteCode.objects.filter(
                pk=code.pk,
                is_active=True,
                used_count__lt=F("max_uses"),
            ).update(used_count=F("used_count") + 1, updated_at=timezone.now())
        if not updated:
            # 校验与落库之间被别人用光了。规模只有几十人，容忍这种极窄窗口，
            # 不因此回滚已创建的账号；站主可在后台看到 used_count 与实际不符。
            pass
