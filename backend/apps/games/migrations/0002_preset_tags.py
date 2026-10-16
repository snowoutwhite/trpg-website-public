"""预置「战役」「西征」两枚标签。"""

from django.db import migrations

PRESET_TAG_NAMES = ["战役", "西征"]


def create_preset_tags(apps, schema_editor):
    Tag = apps.get_model("games", "Tag")
    for name in PRESET_TAG_NAMES:
        Tag.objects.update_or_create(name=name, defaults={"is_preset": True})


def remove_preset_tags(apps, schema_editor):
    Tag = apps.get_model("games", "Tag")
    Tag.objects.filter(name__in=PRESET_TAG_NAMES, is_preset=True).delete()


class Migration(migrations.Migration):
    dependencies = [("games", "0001_initial")]

    operations = [migrations.RunPython(create_preset_tags, remove_preset_tags)]
