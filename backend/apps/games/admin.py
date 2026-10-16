"""团后台。

注意：列表与搜索一律用昵称，**不要显示报名者邮箱**（用户数据红线）。
结团 / 取消这类带副作用的动作请走前台接口或 services，别在后台直接改 status，
否则次数统计与通知不会触发。
"""

from __future__ import annotations

from django.contrib import admin

from apps.games.models import Game, Session, Signup, Tag


class SignupInline(admin.TabularInline):
    model = Signup
    extra = 0
    fields = ["order", "player", "status", "card", "card_uploaded_by_gm", "attended", "review_note"]
    readonly_fields = ["order", "player", "card", "card_uploaded_by_gm"]
    autocomplete_fields: list = []

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class SessionInline(admin.TabularInline):
    model = Session
    extra = 0
    fields = ["index", "label", "held_at"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "is_preset", "game_count", "created_at"]
    list_filter = ["is_preset"]
    search_fields = ["name"]

    @admin.display(description="团数")
    def game_count(self, obj: Tag) -> int:
        return obj.games.count()


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "gm_nickname",
        "rule_system",
        "start_at",
        "status",
        "signup_mode",
        "requires_card",
        "seats",
        "finished_at",
    ]
    list_filter = ["status", "signup_mode", "mode", "requires_card", "mutual_review", "auto_closed"]
    search_fields = ["title", "rule_system", "gm__nickname"]
    filter_horizontal = ["tags"]
    readonly_fields = ["finished_at", "auto_closed", "created_at", "updated_at"]
    inlines = [SignupInline, SessionInline]

    @admin.display(description="GM", ordering="gm__nickname")
    def gm_nickname(self, obj: Game) -> str:
        return obj.gm.nickname

    @admin.display(description="占位/上限")
    def seats(self, obj: Game) -> str:
        return f"{obj.occupied_seats}/{obj.max_players}"


@admin.register(Signup)
class SignupAdmin(admin.ModelAdmin):
    list_display = ["game", "player_nickname", "order", "status", "card", "attended", "created_at"]
    list_filter = ["status", "attended", "card_uploaded_by_gm"]
    search_fields = ["game__title", "player__nickname"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="报名者", ordering="player__nickname")
    def player_nickname(self, obj: Signup) -> str:
        return obj.player.nickname


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ["game", "index", "label", "held_at"]
    list_filter = ["game__status"]
    search_fields = ["game__title", "label"]
