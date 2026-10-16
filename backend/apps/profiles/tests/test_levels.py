"""业务规则与安全约束。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.profiles import levels
from apps.profiles.services import level_for

pytestmark = pytest.mark.django_db


def test_评价数不足公布阈值返回None(site_config):
    assert site_config.like_level_publish_threshold == 10
    assert level_for(9, 0, 9) is None


def test_公布阈值把无评价也算进被评次数(site_config):
    """被评价次数 = 赞 + 倒赞 + 无评价：5 赞 + 5 无评价 = 10 次，够默认阈值。"""
    assert site_config.like_level_publish_threshold == 10
    assert level_for(5, 0, 10) == levels.MIXED  # 赞占比 0.5，倒赞 0 → 中性


def test_站配默认值是两个赞占比下限加两个倒赞占比下限(site_config):
    assert site_config.level_overwhelmingly_positive_min == Decimal("0.800")
    assert site_config.level_mostly_positive_min == Decimal("0.600")
    assert site_config.level_overwhelmingly_negative_dislike_min == Decimal("0.600")
    assert site_config.level_mostly_negative_dislike_min == Decimal("0.400")
    assert not hasattr(site_config, "level_mixed_min")
    assert not hasattr(site_config, "level_mostly_negative_min")


@pytest.mark.parametrize(
    "like,dislike,none,expected",
    [
        # 只有赞与倒赞（无评价 0）
        (80, 20, 0, levels.OVERWHELMINGLY_POSITIVE),
        (79, 21, 0, levels.MOSTLY_POSITIVE),
        (60, 40, 0, levels.MOSTLY_POSITIVE),  # 赞 60 / 倒赞 40 同时达标：先看好评，归好评居多
        (59, 41, 0, levels.MOSTLY_NEGATIVE),  # 倒赞 41% ≥ 40%
        (41, 59, 0, levels.MOSTLY_NEGATIVE),
        (40, 60, 0, levels.OVERWHELMINGLY_NEGATIVE),  # 倒赞恰好 60%
        (0, 100, 0, levels.OVERWHELMINGLY_NEGATIVE),
        (100, 0, 0, levels.OVERWHELMINGLY_POSITIVE),
        # 无评价计入分母
        (80, 0, 20, levels.OVERWHELMINGLY_POSITIVE),  # 赞 80%
        (79, 0, 21, levels.MOSTLY_POSITIVE),
        (80, 10, 10, levels.OVERWHELMINGLY_POSITIVE),
        (70, 0, 30, levels.MOSTLY_POSITIVE),
        (59, 0, 41, levels.MIXED),  # 赞不到 60%，倒赞 0
        (50, 39, 11, levels.MIXED),  # 赞 50%，倒赞 39%
        (50, 40, 10, levels.MOSTLY_NEGATIVE),  # 倒赞恰好 40%
        (20, 59, 21, levels.MOSTLY_NEGATIVE),
        (20, 60, 20, levels.OVERWHELMINGLY_NEGATIVE),
        (10, 10, 80, levels.MIXED),  # 无评价占比最高 → 中性
        (0, 0, 100, levels.MIXED),  # 全是无评价 → 中性
        (0, 39, 61, levels.MIXED),
    ],
)
def test_五档边界_无评价计入分母不计入分子(site_config, like, dislike, none, expected):
    site_config.like_level_publish_threshold = 1
    site_config.save()
    assert level_for(like, dislike, like + dislike + none) == expected


def test_同样的赞倒赞_无评价越多越向中性靠拢(site_config):
    site_config.like_level_publish_threshold = 1
    site_config.save()
    assert level_for(9, 1, 10) == levels.OVERWHELMINGLY_POSITIVE  # 赞 0.9
    assert level_for(9, 1, 12) == levels.MOSTLY_POSITIVE  # 赞 0.75
    assert level_for(9, 1, 16) == levels.MIXED  # 赞 0.5625
    assert level_for(1, 9, 10) == levels.OVERWHELMINGLY_NEGATIVE  # 倒赞 0.9
    assert level_for(1, 9, 20) == levels.MOSTLY_NEGATIVE  # 倒赞 0.45
    assert level_for(1, 9, 30) == levels.MIXED  # 倒赞 0.3


def test_关闭赞功能后不公布档位(site_config):
    site_config.like_feature_enabled = False
    site_config.save()
    assert level_for(90, 10, 100) is None


def test_站主调整边界后生效(site_config):
    site_config.level_overwhelmingly_positive_min = Decimal("0.950")
    site_config.save()
    assert level_for(90, 10, 100) == levels.MOSTLY_POSITIVE
    assert level_for(96, 4, 100) == levels.OVERWHELMINGLY_POSITIVE


def test_站主调整倒赞边界后生效(site_config):
    site_config.like_level_publish_threshold = 1
    site_config.level_overwhelmingly_negative_dislike_min = Decimal("0.500")
    site_config.level_mostly_negative_dislike_min = Decimal("0.300")
    site_config.save()
    assert level_for(40, 50, 100) == levels.OVERWHELMINGLY_NEGATIVE
    assert level_for(50, 30, 100) == levels.MOSTLY_NEGATIVE
    assert level_for(50, 29, 100) == levels.MIXED


def test_分母为0返回None(site_config):
    site_config.like_level_publish_threshold = 1
    site_config.save()
    assert level_for(0, 0, 0) is None
