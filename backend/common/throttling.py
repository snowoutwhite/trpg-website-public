"""可在后台调整的游客限速。

DRF 的 `AnonRateThrottle` 只认 settings 里写死的 `anon` 速率；这里改成每次请求时读
`SiteConfig.anon_throttle_per_minute`（走 siteconfig 的配置缓存，保存即失效），
站长在后台改一个数就生效，不用重新部署。settings 里的 `THROTTLE_ANON` 退化为两种兜底：
`None`（测试环境）= 关闭；其他值 = 配置表读不到时（迁移前、数据库故障）用的速率。
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle


class ConfigurableAnonRateThrottle(AnonRateThrottle):
    scope = "anon"

    def get_rate(self) -> str | None:
        # 读类属性而不是 api_settings：DRF 在类定义时把 DEFAULT_THROTTLE_RATES 绑成
        # `SimpleRateThrottle.THROTTLE_RATES`，测试夹具（common/tests）也是替换这个类属性
        fallback = self.THROTTLE_RATES.get(self.scope)
        if fallback is None:
            return None
        try:
            from apps.siteconfig.services import get_config

            per_minute = int(get_config().anon_throttle_per_minute)
        except Exception:  # noqa: BLE001 - 配置读不到就退回 settings，限速不能因为配置表故障而消失
            return fallback
        return f"{per_minute}/min" if per_minute > 0 else fallback
