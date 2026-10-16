"""五档边界改为「两个赞占比下限 + 两个倒赞占比下限」。

旧 `level_mixed_min` / `level_mostly_negative_min` 是**赞比例**下限（0.4 / 0.2），新口径要的是
**倒赞占比**下限（0.6 / 0.4）。语义不同，所以删旧加新、不做重命名：
若改名沿用旧列，站主以前调过的数值会带着错的语义进入新判定。新字段一律取默认值。
"""

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("siteconfig", "0004_siteconfig_anon_throttle"),
    ]

    operations = [
        migrations.RemoveField(model_name="siteconfig", name="level_mixed_min"),
        migrations.RemoveField(model_name="siteconfig", name="level_mostly_negative_min"),
        migrations.AddField(
            model_name="siteconfig",
            name="level_overwhelmingly_negative_dislike_min",
            field=models.DecimalField(
                decimal_places=3, default=Decimal("0.600"), max_digits=4, verbose_name="差评如潮下限（倒赞占比）"
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="level_mostly_negative_dislike_min",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.400"),
                help_text="赞占比与倒赞占比恰好同时达标时（如赞 60%、倒赞 40%）先按好评判",
                max_digits=4,
                verbose_name="倒赞居多下限（倒赞占比）",
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="level_overwhelmingly_positive_min",
            field=models.DecimalField(
                decimal_places=3, default=Decimal("0.800"), max_digits=4, verbose_name="好评如潮下限（赞占比）"
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="level_mostly_positive_min",
            field=models.DecimalField(
                decimal_places=3, default=Decimal("0.600"), max_digits=4, verbose_name="好评居多下限（赞占比）"
            ),
        ),
    ]
