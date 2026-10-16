"""战报后台：站主在这里打「精选」标记、处理举报。"""

from __future__ import annotations

from django.contrib import admin

from apps.reports import services
from apps.reports.models import (
    ABUSE_DISMISSED,
    ABUSE_RESOLVED,
    Report,
    ReportAttachment,
    ReportReport,
)


class ReportAttachmentInline(admin.TabularInline):
    model = ReportAttachment
    extra = 0
    fields = ["original_name", "size", "mime", "uploaded_by", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        # 附件只能从前台带着白名单 + 魔数校验上传，后台不开旁路。
        return False


class ReportAbuseInline(admin.TabularInline):
    model = ReportReport
    extra = 0
    fields = ["reporter", "reason", "status", "handled_by", "handled_at", "created_at"]
    readonly_fields = ["reporter", "reason", "created_at"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["title", "author_nickname", "game", "visibility", "is_featured", "created_at"]
    list_filter = ["is_featured", "visibility"]
    list_editable = ["is_featured"]
    search_fields = ["title", "author__nickname", "game__title"]
    autocomplete_fields = ["author"]
    readonly_fields = ["game", "author", "created_at", "updated_at"]
    inlines = [ReportAttachmentInline, ReportAbuseInline]
    actions = ["mark_featured", "unmark_featured"]

    @admin.display(description="作者", ordering="author__nickname")
    def author_nickname(self, obj: Report) -> str:
        return obj.author.nickname

    def has_add_permission(self, request) -> bool:
        # 战报只能由作者从前台提交（提交条件与积分都在 service 里），后台不新建。
        return False

    @admin.action(description="标记为精选（游客可见）")
    def mark_featured(self, request, queryset) -> None:
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"已精选 {updated} 篇战报。")

    @admin.action(description="取消精选")
    def unmark_featured(self, request, queryset) -> None:
        updated = queryset.update(is_featured=False)
        self.message_user(request, f"已取消 {updated} 篇战报的精选。")


@admin.register(ReportReport)
class ReportReportAdmin(admin.ModelAdmin):
    list_display = ["report", "reporter_nickname", "status", "handled_by", "created_at"]
    list_filter = ["status"]
    search_fields = ["report__title", "reporter__nickname", "reason"]
    readonly_fields = ["report", "reporter", "reason", "created_at", "handled_at"]
    actions = ["mark_resolved", "mark_dismissed"]

    @admin.display(description="举报人", ordering="reporter__nickname")
    def reporter_nickname(self, obj: ReportReport) -> str:
        return obj.reporter.nickname

    def has_add_permission(self, request) -> bool:
        return False

    @admin.action(description="标记为已处理")
    def mark_resolved(self, request, queryset) -> None:
        for abuse in queryset:
            services.handle_abuse(abuse, status=ABUSE_RESOLVED, by=request.user)
        self.message_user(request, f"已处理 {queryset.count()} 条举报。")

    @admin.action(description="驳回举报")
    def mark_dismissed(self, request, queryset) -> None:
        for abuse in queryset:
            services.handle_abuse(abuse, status=ABUSE_DISMISSED, by=request.user)
        self.message_user(request, f"已驳回 {queryset.count()} 条举报。")
