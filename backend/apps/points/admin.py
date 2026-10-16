"""积分与称号后台。"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages

from apps.points import services
from apps.points.models import PointsLedger, Title, UserTitle
from common.exceptions import ApiError


class PointsLedgerForm(forms.ModelForm):
    """手工发分的表单校验。

    0 分会被 `services.grant()` 直接拒掉，而 `save_model` 里抛出的业务异常
    在后台是**没人接的 500**，站主只会看到一个错误页。所以拦在表单层，
    让它以字段错误的形式显示出来（对抗测试 `test_adversarial_points.py`）。
    """

    class Meta:
        model = PointsLedger
        fields = ["user", "amount", "reason", "note", "dedupe_key"]

    def clean_amount(self) -> int:
        amount = self.cleaned_data.get("amount")
        if amount == 0:
            raise forms.ValidationError("积分变动不能为 0")
        return amount


@admin.register(PointsLedger)
class PointsLedgerAdmin(admin.ModelAdmin):
    form = PointsLedgerForm
    list_display = ["user_nickname", "amount", "reason", "note", "revoked", "created_at"]
    list_filter = ["reason"]
    search_fields = ["user__nickname", "note"]
    autocomplete_fields = ["user"]
    readonly_fields = ["ref_content_type", "ref_object_id", "revokes", "created_by", "created_at", "updated_at"]
    fields = ["user", "amount", "reason", "note", "dedupe_key", "ref_content_type", "ref_object_id", "revokes", "created_by", "created_at"]
    actions = ["revoke_selected"]

    @admin.display(description="用户", ordering="user__nickname")
    def user_nickname(self, obj: PointsLedger) -> str:
        return obj.user.nickname

    @admin.display(description="已撤销", boolean=True)
    def revoked(self, obj: PointsLedger) -> bool:
        return obj.is_revoked

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return self.readonly_fields
        # 已落库的流水一律只读：账本只增不改。
        return [f for f in self.fields if f != "note"] + ["updated_at"]

    def save_model(self, request, obj, form, change) -> None:
        if change:
            super().save_model(request, obj, form, change)
            return
        entry = services.grant(
            obj.user,
            obj.amount,
            obj.reason or "manual",
            dedupe_key=obj.dedupe_key or None,
            created_by=request.user,
            note=obj.note,
        )
        # 落库的是 `grant()` 新建的那一行，表单里这个实例从没被保存过。
        # 不把主键回填给 admin 的话，`obj.pk` 一直是 None：「保存并继续编辑」
        # 会跳到 `.../None/change/`，操作日志也记不到对象 id。
        obj.pk = entry.pk
        obj.refresh_from_db()

    @admin.action(description="撤销选中的积分流水（写负数行，不删行）")
    def revoke_selected(self, request, queryset) -> None:
        done = 0
        for entry in queryset:
            try:
                services.revoke(entry, by=request.user)
            except ApiError as exc:
                self.message_user(request, f"#{entry.pk}：{exc.detail}", level=messages.WARNING)
            else:
                done += 1
        if done:
            self.message_user(request, f"已撤销 {done} 条积分流水。", level=messages.SUCCESS)


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ["name", "cost", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(UserTitle)
class UserTitleAdmin(admin.ModelAdmin):
    list_display = ["user_nickname", "title", "granted_at"]
    list_filter = ["title"]
    search_fields = ["user__nickname", "title__name"]
    autocomplete_fields = ["user", "title"]

    @admin.display(description="用户", ordering="user__nickname")
    def user_nickname(self, obj: UserTitle) -> str:
        return obj.user.nickname
