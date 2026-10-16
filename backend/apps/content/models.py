"""术语速查表、新人指南、FAQ（需求整理第 3 节）。游客可读，站主在后台维护。"""

from __future__ import annotations

from django.db import models

from common.models import TimeStampedModel


class PublishedQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)


class GlossaryTerm(TimeStampedModel):
    """跑团术语。别名用于前端搜索命中（如 DM/KP 指向同一条）。"""

    term = models.CharField("术语", max_length=60, unique=True)
    definition = models.TextField("定义")
    aliases = models.JSONField("别名", default=list, blank=True, help_text="字符串数组")
    order = models.IntegerField("排序", default=0, help_text="越小越靠前")
    is_published = models.BooleanField("已发布", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "术语"
        verbose_name_plural = "术语表"
        ordering = ["order", "term"]

    def __str__(self) -> str:
        return self.term


class Guide(TimeStampedModel):
    """新人指南，正文用 Markdown。"""

    title = models.CharField("标题", max_length=120)
    slug = models.SlugField("短链标识", max_length=120, unique=True)
    body_markdown = models.TextField("正文（Markdown）")
    order = models.IntegerField("排序", default=0)
    is_published = models.BooleanField("已发布", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "新人指南"
        verbose_name_plural = "新人指南"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.title


class FAQ(TimeStampedModel):
    question = models.CharField("问题", max_length=200)
    answer = models.TextField("回答")
    order = models.IntegerField("排序", default=0)
    is_published = models.BooleanField("已发布", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "常见问题"
        verbose_name_plural = "常见问题"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.question
