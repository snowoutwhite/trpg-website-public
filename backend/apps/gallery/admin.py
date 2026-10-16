"""活动相册后台。

站主在这里做「公开前审核」与「举报处置」。两类动作都走 `services.*`，
**不要在后台直接改 status**：举报处置要给举报人发通知，绕过 service 就不会发。

隐私：列表与搜索一律用昵称，不显示邮箱；也不显示任何文件存储路径。
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from apps.gallery import services
from apps.gallery.models import (
    PHOTO_PUBLIC,
    RESULT_RESTORED,
    RESULT_TAKEN_DOWN,
    Photo,
    PhotoReport,
)


class PhotoReportInline(admin.TabularInline):
    model = PhotoReport
    extra = 0
    fields = ["reporter", "reason", "reason_text", "status", "result", "result_note", "created_at"]
    readonly_fields = ["reporter", "reason", "reason_text", "created_at"]

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class PhotoAdminForm(forms.ModelForm):
    """后台改照片时的闸：**非公开照片不能被勾成首页精选**。

    数据库层另有 `featured_photo_must_be_public` 约束，但那条约束抛的是
    IntegrityError（后台会变成 500）；这里先在表单层给出人话提示。
    """

    class Meta:
        model = Photo
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status", getattr(self.instance, "status", None))
        if cleaned.get("is_featured") and status != PHOTO_PUBLIC:
            raise forms.ValidationError("只有已公开的照片能设为首页精选。")
        return cleaned


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    form = PhotoAdminForm
    list_display = ["id", "game", "uploader_nickname", "status", "is_featured", "thumb_preview", "size", "created_at"]
    # 故意**不开** `list_editable`：列表页的批量编辑走的是 Django 自己造的
    # 默认 ModelForm，绕过 `PhotoAdminForm.clean()`，于是「把一张已下架的照片
    # 勾成精选」会一路撞到数据库约束，站主看到的是 500 而不是人话。
    # 批量操作用下面两个 action。
    list_filter = ["status", "is_featured", "created_at"]
    search_fields = ["caption", "uploader__nickname", "game__title"]
    readonly_fields = [
        "game",
        "uploader",
        "original",
        "preview",
        "thumbnail",
        "width",
        "height",
        "size",
        "created_at",
        "updated_at",
    ]
    inlines = [PhotoReportInline]
    actions = ["action_approve", "action_take_down", "action_feature", "action_unfeature"]

    @admin.display(description="上传者")
    def uploader_nickname(self, obj: Photo) -> str:
        return obj.uploader.nickname

    @admin.display(description="缩略")
    def thumb_preview(self, obj: Photo):
        """缩略预览走鉴权视图，不渲染 media 直链 —— 相册文件全在 protected/ 里。"""
        if not obj.thumbnail:
            return "—"
        from django.urls import reverse

        url = reverse("v1:gallery:photo-file", kwargs={"pk": obj.pk}) + "?size=thumb"
        return format_html('<img src="{}" style="height:48px;border-radius:4px" alt="">', url)

    def has_add_permission(self, request) -> bool:
        # 照片只能经 GM 的上传接口进来（那里才有 EXIF 剥离与三档生成）。
        return False

    @admin.action(description="审核通过（置为已公开）")
    def action_approve(self, request, queryset) -> None:
        count = 0
        for photo in queryset.exclude(status=PHOTO_PUBLIC):
            try:
                services.approve_photo(photo)
            except Exception as exc:  # noqa: BLE001 - 后台批量动作逐条容错
                self.message_user(request, f"#{photo.pk} 跳过：{exc}", level=messages.WARNING)
            else:
                count += 1
        self.message_user(request, f"已通过 {count} 张照片")

    @admin.action(description="下架所选照片")
    def action_take_down(self, request, queryset) -> None:
        for photo in queryset:
            services.take_down_photo(photo, reason="站主在后台下架")
        self.message_user(request, f"已下架 {queryset.count()} 张照片")

    @admin.action(description="设为首页精选（仅限已公开）")
    def action_feature(self, request, queryset) -> None:
        from apps.homecontent.services import set_photo_featured

        count = 0
        for photo in queryset:
            try:
                set_photo_featured(photo, True)
            except Exception as exc:  # noqa: BLE001 - 后台批量动作逐条容错
                self.message_user(request, f"#{photo.pk} 跳过：{exc}", level=messages.WARNING)
            else:
                count += 1
        self.message_user(request, f"已精选 {count} 张照片")

    @admin.action(description="取消首页精选")
    def action_unfeature(self, request, queryset) -> None:
        updated = queryset.update(is_featured=False)
        self.message_user(request, f"已取消 {updated} 张照片的精选")


@admin.register(PhotoReport)
class PhotoReportAdmin(admin.ModelAdmin):
    list_display = ["id", "photo", "reporter_nickname", "reason", "status", "result", "created_at"]
    list_filter = ["status", "reason", "result"]
    search_fields = ["reason_text", "reporter__nickname"]
    readonly_fields = ["photo", "reporter", "reason", "reason_text", "created_at", "updated_at"]
    actions = ["action_restore", "action_confirm_take_down"]

    @admin.display(description="举报人")
    def reporter_nickname(self, obj: PhotoReport) -> str:
        return obj.reporter.nickname

    def has_add_permission(self, request) -> bool:
        return False

    def _handle(self, request, queryset, action: str, label: str) -> None:
        count = 0
        for report in queryset.select_related("photo"):
            try:
                services.handle_report(report, by=request.user, action=action)
            except Exception as exc:  # noqa: BLE001 - 后台批量动作逐条容错
                self.message_user(request, f"#{report.pk} 跳过：{exc}", level=messages.WARNING)
            else:
                count += 1
        self.message_user(request, f"已{label} {count} 条举报")

    @admin.action(description="恢复照片展示并结案")
    def action_restore(self, request, queryset) -> None:
        self._handle(request, queryset, RESULT_RESTORED, "恢复")

    @admin.action(description="确认下架并结案")
    def action_confirm_take_down(self, request, queryset) -> None:
        self._handle(request, queryset, RESULT_TAKEN_DOWN, "下架")
