from django.contrib import admin

from apps.profiles.models import GMCard, PlayerCard


@admin.register(PlayerCard)
class PlayerCardAdmin(admin.ModelAdmin):
    list_display = ["user", "games_played", "reviews_received", "likes", "dislikes", "level"]
    search_fields = ["user__nickname"]
    readonly_fields = ["games_played", "reviews_received", "likes", "dislikes", "level"]


@admin.register(GMCard)
class GMCardAdmin(admin.ModelAdmin):
    list_display = ["user", "games_hosted", "reviews_received", "likes", "dislikes", "level"]
    search_fields = ["user__nickname"]
    readonly_fields = ["games_hosted", "reviews_received", "likes", "dislikes", "level"]
