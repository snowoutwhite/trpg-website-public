from rest_framework import serializers

from apps.content.models import FAQ, GlossaryTerm, Guide


class GlossaryTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlossaryTerm
        fields = ["id", "term", "definition", "aliases", "order"]
        read_only_fields = fields


class GuideListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guide
        fields = ["id", "title", "slug", "order"]
        read_only_fields = fields


class GuideDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guide
        fields = ["id", "title", "slug", "body_markdown", "order", "updated_at"]
        read_only_fields = fields


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["id", "question", "answer", "order"]
        read_only_fields = fields
