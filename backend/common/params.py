"""查询参数/路径参数的解析小工具。

只有「把外部来的东西解析成主键」这一件事，但 reports / charactercards /
homecontent 三处都要用 —— 各抄一份的下场是某处漏了位数闸，同一类输入在一个接口
是 404、在另一个接口是 500。

为什么不是简单的 `int(raw)`：
- 库里主键是 32 位整数，越界值在 PostgreSQL 上会抛 `DataError` → 500；
- Python 3.11+ 对超过 4300 位的数字串直接 `int()` 就会抛 `ValueError` → 同样 500；
- 上标「²」、全角「１」这类字符 `str.isdigit()` 为真但 `int()` 会抛 ValueError。
所以先按位数挡一道（连 `int()` 都不调），再比大小，几种 500 一起堵掉。

对抗测试：`apps/reports/tests/test_adversarial_reports.py::test_列表过滤器收到超长数字不得打成500`、
`apps/homecontent/tests/test_redteam_featured_leak.py`。
"""

from __future__ import annotations

#: PostgreSQL integer 的上界，也是 Django `AutoField` / `PositiveIntegerField` 的上界。
PK_MAX = 2**31 - 1
PK_MAX_DIGITS = len(str(PK_MAX))


def parse_pk(raw: str | int | None) -> int | None:
    """把外部输入解析成合法主键；不合法一律回 `None`（调用方按「查不到」处理）。

    `int` 直接进来也照样过范围闸 —— URL 里 `<int:pk>` 转换器只保证是数字，
    不保证落在 32 位整数范围内。
    """
    if isinstance(raw, bool):  # bool 是 int 的子类，别让 True 变成主键 1
        return None
    if isinstance(raw, int):
        number = raw
    else:
        value = (raw or "").strip()
        if not value.isascii() or not value.isdigit() or len(value) > PK_MAX_DIGITS:
            return None
        number = int(value)
    return number if 0 < number <= PK_MAX else None
