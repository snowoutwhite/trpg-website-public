"""规则名大小写不敏感唯一（DB 层）+ 站内路由校验器挂到模型字段 + 公告预告口径。

三件事，都是把「只在 serializer 上守着」的约束落到模型/数据库这一层
（站长内容是 A 方案：站主在 Django 后台也能改，后台是与 API 同级的第二条写入路径）：

1. `RuleSystemPreset` 加 `UniqueConstraint(Lower("name"))`。
   **加约束前先清一次历史脏数据**：约束上线前写进去的大小写重名
   （`DND` / `dnd`）会让 `AddConstraint` 直接失败。处理口径是**按创建顺序保留第一条、
   删掉后来的重复条**（`pk` 升序即创建顺序）。删的是预设记录本身，
   团与角色卡的 `rule_system` 是自由文本、不是外键，不受影响；
   被删掉那条的名字仍然能被 `DND` 那条匹配到（筛选本来就是 `__iexact`）。
   去重的键与索引严格对齐：`name.lower()`，**不 strip** —— 索引上 `"   "` 与 `"\t"`
   本来就是两条不同的行。
2. `QuickEntry.route` 挂 `validate_internal_route`（只改 validators/help_text，不动列）。
3. `SiteAnnouncement.published_at` 的 help_text 改成新口径：预告到点后由
   `manage.py announcements_publish_due` 补推（见 `services.publish_due_announcements`）。

回滚：`reverse` 只去约束，删掉的重复预设不会回来（也回不来 —— 它们本来就是重复项）。
"""

import apps.homecontent.models
import django.db.models.functions.text
from django.db import migrations, models


def dedupe_case_insensitive_names(apps, schema_editor):
    """大小写重名只留创建顺序里的第一条，其余删掉（否则加不上唯一约束）。"""
    RuleSystemPreset = apps.get_model("homecontent", "RuleSystemPreset")
    seen: set[str] = set()
    doomed: list[int] = []
    for pk, name in RuleSystemPreset.objects.order_by("pk").values_list("pk", "name"):
        key = (name or "").lower()
        if key in seen:
            doomed.append(pk)
        else:
            seen.add(key)
    if doomed:
        RuleSystemPreset.objects.filter(pk__in=doomed).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('homecontent', '0002_seed_home_content'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quickentry',
            name='route',
            field=models.CharField(default='/', help_text='站内路由，必须以单个 / 开头，如 /recruit；不接受站外地址', max_length=120, validators=[apps.homecontent.models.validate_internal_route], verbose_name='目标路由'),
        ),
        migrations.AlterField(
            model_name='rulesystempreset',
            name='name',
            field=models.CharField(help_text='全站分类轴的取值，团与角色卡的 rule_system 字段按它对齐（大小写不敏感地唯一）；前后各两个下划线的名字（如 __other__）是保留形式', max_length=60, unique=True, validators=[apps.homecontent.models.validate_preset_name], verbose_name='规则名'),
        ),
        migrations.AlterField(
            model_name='siteannouncement',
            name='published_at',
            field=models.DateTimeField(db_index=True, help_text='未来时间 = 预告：到点之前不进公开列表也不推送；到点后由 `manage.py announcements_publish_due`（生产 cron 每小时）补推一轮，公开列表被访问时也会顺手补推。留空 = 此刻', verbose_name='发布时间'),
        ),
        migrations.RunPython(
            dedupe_case_insensitive_names, migrations.RunPython.noop, elidable=False
        ),
        migrations.AddConstraint(
            model_name='rulesystempreset',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('name'), name='homecontent_preset_name_ci_unique'),
        ),
    ]
