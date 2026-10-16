"""站级配置的读取入口。

所有业务代码读开关与阈值都走 `get_config()`，它带进程级缓存，写入时自动失效。
"""

from __future__ import annotations

from django.core.cache import cache

from apps.siteconfig.models import SiteConfig

CACHE_KEY = "siteconfig:singleton"
CACHE_TTL = 300  # 秒；写入时会主动失效，TTL 只是兜底


def get_config() -> SiteConfig:
    """返回唯一的 SiteConfig 实例，不存在时用默认值创建。"""
    config = cache.get(CACHE_KEY)
    if config is None:
        config, _ = SiteConfig.objects.get_or_create(pk=SiteConfig.SINGLETON_PK)
        cache.set(CACHE_KEY, config, CACHE_TTL)
    return config


def clear_config_cache() -> None:
    cache.delete(CACHE_KEY)


# --------------------------------------------------------------------------
# 「其他」筛选（v2 首页与筛选条的第五个筹码）
# --------------------------------------------------------------------------

#: 前端筛选「其他」时传的哨兵值。**大小写敏感**：只有一模一样的 `__other__` 才算哨兵，
#: `__OTHER__`、`__Other__` 一律当成普通规则名（于是匹配不到任何团），
#: 免得「哨兵的识别规则」和「规则名的比较规则」两套大小写口径混在一起互相打架。
OTHER_SENTINEL = "__other__"


def preset_rule_systems() -> list[str]:
    """站级规则预设列表（= `SiteConfig.rule_system_presets` 这面只读镜像）。

    真源是 `homecontent.RuleSystemPreset` 表，镜像由它同步过来
    （`apps.homecontent.services.sync_rule_system_presets`）。这里读镜像而不是读表，
    有两个好处：siteconfig 仍是零依赖的叶子模块；筛选口径与公开接口 `/api/v1/siteconfig/`
    吐给前端的那份列表**按构造相等**，不会出现「前端按 A 画筹码、后端按 B 过滤」。
    """
    presets = get_config().rule_system_presets or []
    return [str(name) for name in presets if str(name).strip()]


def exclude_preset_rule_systems(queryset, *, field: str = "rule_system"):
    """把「规则名命中站级预设」的行排掉，剩下的就是「其他」。

    大小写不敏感（`__iexact`）：站主配的是 `COC`，GM 填的是 `coc`，那也是 COC 的团，
    不该落进「其他」。`__iexact` 走的是 ORM 参数化，预设名里有 `%`、`_`、引号都无所谓。
    规则名为空的行会被保留 —— 空也不是任何一个预设。
    """
    for name in preset_rule_systems():
        queryset = queryset.exclude(**{f"{field}__iexact": name})
    return queryset
