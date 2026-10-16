"""预置首页内容：规则预设（从现有 JSON 列表生成）+ 快速选择六项。"""

from django.db import migrations


RULE_COPY = {
    "DND": {
        "kicker": "DUNGEONS & DRAGONS",
        "title": "龙与地下城",
        "tagline": "奇幻冒险 · 探索 · 社交 · 战斗",
        "intro_hero": "掷下骰子，让想象中的世界成为你的冒险。",
        "intro_body": "扮演奇幻世界中的冒险者，与同伴一起探索未知、与角色互动，并面对战斗挑战。骰子与角色能力共同影响行动结果。",
        "intro_fit": "如果你喜欢组队探险、扮演角色与战斗中的决策，可以从这里了解。",
        "official_url": "https://www.dndbeyond.com/sources/dnd/br-2024/playing-the-game",
        "tone": "dark",
    },
    "COC": {
        "kicker": "CALL OF CTHULHU",
        "title": "克苏鲁的呼唤",
        "tagline": "秘密 · 调查 · 恐怖",
        "intro_hero": "在未知的阴影里，寻找被遗忘的真相。",
        "intro_body": "扮演调查员，追寻秘密、拼合线索，面对难以理解的恐怖。故事的重心是谜团与调查，而非单纯击败敌人。",
        "intro_fit": "如果你喜欢悬疑、探索真相与恐怖氛围，可以从这里了解。",
        "official_url": "https://cthulhuwiki.chaosium.com/rules/",
        "tone": "dark",
    },
    "三角机构": {
        "kicker": "TRIANGLE AGENCY",
        "title": "三角机构",
        "tagline": "超自然调查 · 企业恐怖 · 荒诞幽默",
        "intro_hero": "欢迎入职。今天的异常，等你处理。",
        "intro_body": "作为机构的一员，运用足以扭曲现实的能力处理异常，同时应对官僚流程与日常生活的责任。",
        "intro_fit": "如果你喜欢超自然事件、荒诞职场与黑色幽默，可以从这里了解。",
        "official_url": "https://hauntedtable.itch.io/triangle-agency",
        "tone": "light",
    },
    "FU": {
        "kicker": "FABULA ULTIMA",
        "title": "最终物语",
        "tagline": "日式角色扮演游戏灵感 · 奇幻冒险",
        "intro_hero": "与你的伙伴，共写下一段物语。",
        "intro_body": "一款受日式电子游戏 RPG 启发的桌面角色扮演游戏，把奇幻世界中的冒险带到共同讲述的故事里。",
        "intro_fit": "如果你喜欢日式 RPG 的冒险气氛，可以从这里了解。",
        "official_url": "https://need.games/fabula-ultima/",
        "tone": "light",
    },
}


QUICK_ENTRIES = [
    {
        "key": "newbie",
        "label": "我是新人",
        "description": "先弄懂跑团怎么进行",
        "icon": "sprout",
        "kicker": "START YOUR FIRST ADVENTURE",
        "title": "第一次跑团，\n从这里开始。",
        "body": "不必先读完所有规则。先了解跑团如何进行，再找到适合新人的第一场冒险。",
        "button_text": "阅读新人指南",
        "route": "/guide",
    },
    {
        "key": "recruit",
        "label": "寻找团局",
        "description": "看看谁在招人",
        "icon": "compass",
        "kicker": "FIND YOUR TABLE",
        "title": "找到下一场冒险。",
        "body": "浏览规则、时间与招募要求，找到适合自己的团，再进入公告查看报名方式。",
        "button_text": "浏览全部招募",
        "route": "/recruit",
    },
    {
        "key": "host",
        "label": "我要开团",
        "description": "发布招募，管理报名",
        "icon": "flag",
        "kicker": "HOST A GAME",
        "title": "让你的故事，\n等到同伴。",
        "body": "发布招募、说明规则和时间，在团务中管理报名与角色卡。开团需要 GM 身份。",
        "button_text": "发布我的招募",
        "route": "/games/new",
    },
    {
        "key": "resources",
        "label": "寻找资源",
        "description": "人物卡、清单、规则书",
        "icon": "folder",
        "kicker": "GET READY",
        "title": "把冒险需要的资料备齐。",
        "body": "寻找人物卡、开团清单和规则书获取渠道。列表对所有人开放，下载需要登录。",
        "button_text": "进入资源区",
        "route": "/resources",
    },
    {
        "key": "reports",
        "label": "阅读战报",
        "description": "别人的团发生了什么",
        "icon": "book",
        "kicker": "READ THE STORIES",
        "title": "看看别人经历的冒险。",
        "body": "在战报中重访精彩片段，也把自己的故事记录下来。",
        "button_text": "阅读大家的战报",
        "route": "/reports",
    },
    {
        "key": "cards",
        "label": "角色卡池",
        "description": "公开的角色，随时可看",
        "icon": "contact",
        "kicker": "BRING YOUR CHARACTER",
        "title": "带上你的角色出发。",
        "body": "探索公开的角色卡，或整理自己的角色与参加过的团。",
        "button_text": "进入角色卡池",
        "route": "/cards",
    },
]

DEFAULT_PRESETS = ["FU", "COC", "DND", "三角机构"]


def seed(apps, schema_editor):
    SiteConfig = apps.get_model("siteconfig", "SiteConfig")
    RuleSystemPreset = apps.get_model("homecontent", "RuleSystemPreset")
    QuickEntry = apps.get_model("homecontent", "QuickEntry")

    config = SiteConfig.objects.filter(pk=1).first()
    names = list((config.rule_system_presets if config else None) or DEFAULT_PRESETS)

    for index, name in enumerate(names):
        name = str(name).strip()
        if not name:
            continue
        copy = dict(RULE_COPY.get(name, {}))
        copy["sort"] = index * 10
        # 历史模型没有 image_alt 之外的默认值问题；用 update_or_create 保证迁移可重跑。
        RuleSystemPreset.objects.update_or_create(name=name, defaults=copy)

    for index, entry in enumerate(QUICK_ENTRIES):
        data = dict(entry)
        key = data.pop("key")
        data["sort"] = index * 10
        QuickEntry.objects.update_or_create(key=key, defaults=data)

    # JSON 镜像按新表的顺序重写一遍（从这一刻起它由表同步）。
    if config is not None:
        mirror = list(
            RuleSystemPreset.objects.order_by("sort", "id").values_list("name", flat=True)
        )
        if list(config.rule_system_presets or []) != mirror:
            config.rule_system_presets = mirror
            config.save(update_fields=["rule_system_presets"])


def unseed(apps, schema_editor):
    RuleSystemPreset = apps.get_model("homecontent", "RuleSystemPreset")
    QuickEntry = apps.get_model("homecontent", "QuickEntry")
    SiteConfig = apps.get_model("siteconfig", "SiteConfig")

    names = list(RuleSystemPreset.objects.order_by("sort", "id").values_list("name", flat=True))
    RuleSystemPreset.objects.all().delete()
    QuickEntry.objects.filter(key__in=[e["key"] for e in QUICK_ENTRIES]).delete()

    config = SiteConfig.objects.filter(pk=1).first()
    if config is not None and names:
        config.rule_system_presets = names
        config.save(update_fields=["rule_system_presets"])


class Migration(migrations.Migration):
    dependencies = [
        ("homecontent", "0001_initial"),
        ("siteconfig", "0003_siteconfig_featured_photos_enabled_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
