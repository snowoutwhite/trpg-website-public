"""用户输入短文本的共用字符闸。

目前只有一件事：**双向控制字符**（RTL override 之流）。它们能让一段文字在页面上
视觉倒序、把后面的静态文案一起「拽」过去，是冒充与误导的经典载体。

范围：
- U+202A–U+202E：LRE / RLE / PDF / LRO / RLO（嵌入与覆盖）；
- U+2066–U+2069：LRI / RLI / FSI / PDI（隔离）；
- U+200E / U+200F / U+061C：LRM / RLM / ALM（方向标记）。

口径与昵称、标签一致（architecture 第 6 节第 6 条）：**直接拒绝（400），不静默剥离**。
昵称与标签本就整类拒绝 Cc/Cf，是本集合的超集，不必再挂这道闸；
这里服务的是「允许换行、允许 ZWJ 组合 emoji」、因而不能整类拒 Cf 的文案字段。
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

#: 正则字符类片段，供其他地方拼进自己的字符类（如资源区后缀归一化）。
BIDI_CONTROL_CLASS = r"؜‎‏‪-‮⁦-⁩"

_BIDI_CONTROL_RE = re.compile(f"[{BIDI_CONTROL_CLASS}]")


def contains_bidi_control(text: str | None) -> bool:
    return bool(text) and _BIDI_CONTROL_RE.search(text) is not None


def validate_no_bidi_controls(value: str | None) -> None:
    """可直接挂在 DRF / Django 字段的 `validators` 上。"""
    if contains_bidi_control(value):
        raise ValidationError("不能包含文字方向控制字符（如 RTL 覆盖）", code="bidi_control")
