"""全站共用的抽象模型。"""

from django.db import models


class TimeStampedModel(models.Model):
    """带创建/更新时间的抽象基类。时间一律 timezone-aware。"""

    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True
