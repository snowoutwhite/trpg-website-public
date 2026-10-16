"""昵称的归一化与合法性校验。

昵称是全站唯一的公开身份标识（个人空间、招募列表、评价列表都只显示它），
所以它同时是**冒充攻击的载体**：不可见字符、双向控制字符、全角同形字都能做出
一个「看起来和站主一模一样」的昵称。注册与改昵称两条路径必须用同一份规则，
否则只补一边等于没补。

规则：
1. Unicode NFKC 归一化 —— 把全角 `Ａｄｍｉｎ`、兼容字符折叠回 `Admin`，
   让唯一性检查能真正拦住同形冒充。
2. 所有空白（含全角空格、不换行空格）折叠成一个普通空格，首尾去掉。
3. 拒绝控制字符（Unicode 类别 Cc/Cf/Cs/Co/Cn）—— 零宽空格、RTL override、
   BOM、换行、制表符都在内。
4. 归一化后长度必须在 1..NICKNAME_MAX_LENGTH 之间。
"""

from __future__ import annotations

import re
import unicodedata

from django.core.exceptions import ValidationError

from apps.accounts.models import NICKNAME_MAX_LENGTH

# 归一化后仍然要拒绝的字符类别：控制字符、格式字符、代理项、私用区、未分配。
_FORBIDDEN_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn"}
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_nickname(raw: str | None) -> str:
    """把用户提交的昵称归一化成可入库的形式；不合法时抛 `ValidationError`。"""
    text = unicodedata.normalize("NFKC", raw or "")
    text = _WHITESPACE_RUN.sub(" ", text).strip()

    if not text:
        raise ValidationError("昵称不能为空，请填写。")

    bad = {ch for ch in text if unicodedata.category(ch) in _FORBIDDEN_CATEGORIES}
    if bad:
        raise ValidationError("昵称不能包含不可见字符。")

    if len(text) > NICKNAME_MAX_LENGTH:
        raise ValidationError(f"昵称最长 {NICKNAME_MAX_LENGTH} 个字，请缩短后重试。")

    return text
