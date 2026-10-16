"""业务规则与安全约束。"""

OVERWHELMINGLY_POSITIVE = "overwhelmingly_positive"
MOSTLY_POSITIVE = "mostly_positive"
MIXED = "mixed"
MOSTLY_NEGATIVE = "mostly_negative"
OVERWHELMINGLY_NEGATIVE = "overwhelmingly_negative"

LEVEL_LABELS = {
    OVERWHELMINGLY_POSITIVE: "好评如潮",
    MOSTLY_POSITIVE: "好评居多",
    MIXED: "中性",
    MOSTLY_NEGATIVE: "倒赞居多",
    OVERWHELMINGLY_NEGATIVE: "差评如潮",
}

LEVEL_CHOICES = list(LEVEL_LABELS.items())
# 从高到低；判定逻辑见 `services.level_for`
LEVEL_ORDER = [
    OVERWHELMINGLY_POSITIVE,
    MOSTLY_POSITIVE,
    MIXED,
    MOSTLY_NEGATIVE,
    OVERWHELMINGLY_NEGATIVE,
]
