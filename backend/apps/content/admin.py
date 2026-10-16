from django.contrib import admin

from apps.content.models import FAQ, GlossaryTerm, Guide


@admin.register(GlossaryTerm)
class GlossaryTermAdmin(admin.ModelAdmin):
    list_display = ["term", "order", "is_published", "updated_at"]
    list_filter = ["is_published"]
    search_fields = ["term", "definition"]
    list_editable = ["order", "is_published"]


@admin.register(Guide)
class GuideAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "order", "is_published", "updated_at"]
    list_filter = ["is_published"]
    search_fields = ["title", "body_markdown"]
    prepopulated_fields = {"slug": ("title",)}


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ["question", "order", "is_published", "updated_at"]
    list_filter = ["is_published"]
    search_fields = ["question", "answer"]
    list_editable = ["order", "is_published"]
