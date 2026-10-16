"""角色卡、角色卡文件版本、卡的参团记录。"""

from __future__ import annotations

import posixpath
import uuid

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel

# 卡状态
STATUS_ALIVE = "alive"
STATUS_TORN = "torn"
STATUS_CHOICES = [
    (STATUS_ALIVE, "尚存"),
    (STATUS_TORN, "撕卡"),
]

# 保留最近 N 版，提案 N = 3。
KEEP_FILE_VERSIONS = 3


def card_file_upload_to(instance: CharacterCardFile, filename: str) -> str:
    """受保护目录 + uuid 文件名：路径不可猜，且带上真实扩展名便于下发时猜 MIME。"""
    extension = posixpath.splitext(filename)[1].lower()
    return posixpath.join(
        settings.PROTECTED_MEDIA_DIRNAME,
        "charactercards",
        f"{uuid.uuid4().hex}{extension}",
    )


class CharacterCard(TimeStampedModel):
    """一张角色卡：元数据归卡，源文件归版本表。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="character_cards",
        verbose_name="持卡人",
    )
    name = models.CharField("角色卡名称", max_length=60)
    rule_system = models.CharField(
        "对应规则",
        max_length=60,
        blank=True,
        default="",
        help_text="可选站点预设（siteconfig.rule_system_presets），也可自定义文本",
    )
    is_public = models.BooleanField(
        "公开", default=False, help_text="公开后进入角色卡池，登录用户可下载源文件"
    )
    status = models.CharField(
        "状态", max_length=16, choices=STATUS_CHOICES, default=STATUS_ALIVE
    )
    note = models.TextField("备注", blank=True, default="")
    play_count = models.PositiveIntegerField(
        "参团次数", default=0, help_text="缓存字段：成功结团后由 games 调用 services.record_play 递增"
    )

    class Meta:
        verbose_name = "角色卡"
        verbose_name_plural = "角色卡"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["is_public", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.name}（{self.owner.nickname}）"

    @property
    def is_usable_for_signup(self) -> bool:
        """能不能拿去交卡（games 阶段读这个属性，前端的交卡下拉也按它过滤）。

        两个条件（缺陷 D3）：
        1. 没撕卡 —— 撕卡后不能再用于报名/交卡；
        2. **至少有一个文件版本** —— 只填了名字的空壳卡交上去，GM 在名单里看得到卡名，
           点开下载却是 404 `card_file_missing`，「交卡并通过 = 成功报团」在这条路径上是空转。
        """
        return self.status == STATUS_ALIVE and self.has_file

    @property
    def latest_file(self) -> CharacterCardFile | None:
        return self.files.order_by("-version").first()

    @property
    def has_file(self) -> bool:
        return self.files.exists()


class CharacterCardFile(TimeStampedModel):
    """角色卡的一个文件版本。换文件 = 加一版，只保留最近 KEEP_FILE_VERSIONS 版。"""

    card = models.ForeignKey(
        CharacterCard, on_delete=models.CASCADE, related_name="files", verbose_name="角色卡"
    )
    file = models.FileField("文件", upload_to=card_file_upload_to, max_length=255)
    original_name = models.CharField("原始文件名", max_length=255)
    size = models.PositiveIntegerField("字节数", default=0)
    mime = models.CharField("MIME 类型", max_length=100, blank=True, default="")
    version = models.PositiveIntegerField("版本号")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_character_card_files",
        verbose_name="上传者",
    )
    uploaded_by_gm = models.BooleanField(
        "GM 代传", default=False, help_text="卡归 PL，注明「GM 上传」"
    )

    class Meta:
        verbose_name = "角色卡文件版本"
        verbose_name_plural = "角色卡文件版本"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["card", "version"], name="uniq_card_file_version")
        ]

    def __str__(self) -> str:
        return f"{self.card.name} v{self.version}"


class CardPlayRecord(TimeStampedModel):
    """这张卡跑过的团。

    games 尚未实现，这里只存团的整数主键（`game_id`），**本 app 不 import games**；
    games 落地后由它在结团时调用 `services.record_play(card, game)` 写入，
    并可通过 `services.register_play_detail_provider()` 补齐团名等展示字段。
    """

    card = models.ForeignKey(
        CharacterCard, on_delete=models.CASCADE, related_name="play_records", verbose_name="角色卡"
    )
    game_id = models.PositiveBigIntegerField("团 ID", db_index=True)
    played_at = models.DateTimeField("结团时间", null=True, blank=True)

    class Meta:
        verbose_name = "角色卡参团记录"
        verbose_name_plural = "角色卡参团记录"
        ordering = ["-played_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["card", "game_id"], name="uniq_card_game")
        ]

    def __str__(self) -> str:
        return f"{self.card.name} @ game#{self.game_id}"
