"""团后评价后台。"""

from __future__ import annotations

from django.contrib import admin

from apps.reviews.models import Review, ReviewWindowNotice


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["game", "reviewee_nickname", "reviewee_role", "verdict", "created_at"]
    list_filter = ["verdict", "reviewee_role", "created_at"]
    search_fields = ["game__title", "reviewee__nickname", "text"]
    list_select_related = ["game", "reviewee", "reviewer"]
    raw_id_fields = ["game", "reviewer", "reviewee"]
    ordering = ["-created_at"]

    @admin.display(description="被评者")
    def reviewee_nickname(self, obj: Review) -> str:
        return obj.reviewee.nickname

    @admin.display(description="评价人（仅超级用户可见）")
    def reviewer_nickname(self, obj: Review) -> str:
        return obj.reviewer.nickname

    # --- 匿名红线：非超级用户看不到评价人 ---

    @staticmethod
    def _is_owner(request) -> bool:
        return bool(getattr(request.user, "is_superuser", False))

    def get_list_display(self, request):
        base = list(self.list_display)
        if self._is_owner(request):
            return ["reviewer_nickname", *base]
        return base

    def get_search_fields(self, request):
        if self._is_owner(request):
            return [*self.search_fields, "reviewer__nickname"]
        return self.search_fields

    def get_fields(self, request, obj=None):
        fields = ["game", "reviewee", "reviewee_role", "verdict", "text", "created_at", "updated_at"]
        if self._is_owner(request):
            return ["reviewer", *fields]
        return fields

    def get_readonly_fields(self, request, obj=None):
        # 评价内容由本人在窗口内改，后台只读；要处理骚扰评价就整条删。
        return self.get_fields(request, obj)

    def lookup_allowed(self, lookup, value, request=None) -> bool:
        """挡住 `?reviewer__id__exact=` 这类直接拼 URL 的过滤（非超级用户）。"""
        if not self._is_owner(request) and lookup.split("__")[0] == "reviewer":
            return False
        return super().lookup_allowed(lookup, value, request)

    def has_add_permission(self, request) -> bool:
        # 后台新建会绕过「到场 / 窗口 / 唯一约束」这些规则，也不会刷新卡片统计。
        return False

    def delete_model(self, request, obj: Review) -> None:
        reviewee, role = obj.reviewee, obj.reviewee_role
        super().delete_model(request, obj)
        self._refresh(reviewee, role)

    def delete_queryset(self, request, queryset) -> None:
        affected = list(queryset.values_list("reviewee_id", "reviewee_role"))
        super().delete_queryset(request, queryset)
        from django.contrib.auth import get_user_model

        users = get_user_model().objects.in_bulk({pk for pk, _ in affected})
        for pk, role in set(affected):
            user = users.get(pk)
            if user is not None:
                self._refresh(user, role)

    @staticmethod
    def _refresh(user, role: str) -> None:
        from apps.reviews.services import refresh_reviewee_stats

        refresh_reviewee_stats(user, role)


@admin.register(ReviewWindowNotice)
class ReviewWindowNoticeAdmin(admin.ModelAdmin):
    list_display = ["game", "sent_at"]
    raw_id_fields = ["game"]
    readonly_fields = ["game", "sent_at"]

    def has_add_permission(self, request) -> bool:
        return False
