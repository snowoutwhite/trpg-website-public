from django.urls import path

from apps.content.views import FAQListView, GlossaryListView, GuideDetailView, GuideListView

app_name = "content"

urlpatterns = [
    path("glossary/", GlossaryListView.as_view(), name="glossary"),
    path("guides/", GuideListView.as_view(), name="guides"),
    path("guides/<slug:slug>/", GuideDetailView.as_view(), name="guide-detail"),
    path("faqs/", FAQListView.as_view(), name="faqs"),
]
