"""角色卡后台。

注意：后台列表里不要显示持卡人邮箱（用户数据红线），用昵称。
文件版本只读展示，替换文件请走前台接口，以免绕过白名单与版本保留规则。
"""

from __future__ import annotations

from django.contrib import admin

from apps.charactercards.models import CardPlayRecord, CharacterCard, CharacterCardFile


class CharacterCardFileInline(admin.TabularInline):
    model = CharacterCardFile
    extra = 0
    can_delete = False
    fields = ["version", "original_name", "size", "mime", "uploaded_by", "uploaded_by_gm", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class CardPlayRecordInline(admin.TabularInline):
    model = CardPlayRecord
    extra = 0
    fields = ["game_id", "played_at", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(CharacterCard)
class CharacterCardAdmin(admin.ModelAdmin):
    list_display = ["name", "owner_nickname", "rule_system", "status", "is_public", "play_count", "created_at"]
    list_filter = ["status", "is_public", "rule_system"]
    search_fields = ["name", "rule_system", "owner__nickname"]
    readonly_fields = ["play_count", "created_at", "updated_at"]
    autocomplete_fields = ["owner"]
    inlines = [CharacterCardFileInline, CardPlayRecordInline]

    @admin.display(description="持卡人", ordering="owner__nickname")
    def owner_nickname(self, obj: CharacterCard) -> str:
        return obj.owner.nickname


@admin.register(CharacterCardFile)
class CharacterCardFileAdmin(admin.ModelAdmin):
    list_display = ["card", "version", "original_name", "size", "uploaded_by_gm", "created_at"]
    list_filter = ["uploaded_by_gm", "mime"]
    search_fields = ["original_name", "card__name"]
    readonly_fields = ["card", "file", "original_name", "size", "mime", "version", "uploaded_by", "uploaded_by_gm", "created_at", "updated_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(CardPlayRecord)
class CardPlayRecordAdmin(admin.ModelAdmin):
    list_display = ["card", "game_id", "played_at", "created_at"]
    search_fields = ["card__name"]
    readonly_fields = ["created_at", "updated_at"]
