"""通知事件常量。"""

# 1 有人报名（发给 GM）
SIGNUP_RECEIVED = "signup_received"
# 2 报名结果（发给 PL）
SIGNUP_RESULT = "signup_result"
# 3 交卡截止前 24 小时提醒（发给未交卡的 PL）
CARD_DEADLINE_REMINDER = "card_deadline_reminder"
# 4 有人交卡（发给 GM）
CARD_SUBMITTED = "card_submitted"
# 5 交卡审批结果（发给 PL）
CARD_REVIEW_RESULT = "card_review_result"
# 6 开团前 24 小时提醒（发给团内所有人）
GAME_START_REMINDER = "game_start_reminder"
# 7 结团提醒（开团后 N 天，默认 3，发给 GM）
GAME_CLOSE_REMINDER = "game_close_reminder"
# 8 自动结团预警（发给 GM）
AUTO_CLOSE_WARNING = "auto_close_warning"
# 9 评价开放（结团后发给团内所有人）
REVIEW_OPENED = "review_opened"
# 10 评价窗口即将关闭
REVIEW_WINDOW_CLOSING = "review_window_closing"
# 11 GM 申请结果
GM_APPLICATION_RESULT = "gm_application_result"
# 12 自动晋升 GM
GM_AUTO_PROMOTED = "gm_auto_promoted"
# 13 照片举报处理结果
PHOTO_REPORT_RESULT = "photo_report_result"

#    唯一一个「全站广播」事件：一条公告给每位活跃用户各建一条站内通知，
#    邮件仍按各人的 EmailPreference 决定（总开关默认关 → 默认只站内不发信）。
SITE_ANNOUNCEMENT = "site_announcement"

EVENT_LABELS: dict[str, str] = {
    SIGNUP_RECEIVED: "有人报名了你的团",
    SIGNUP_RESULT: "报名结果",
    CARD_DEADLINE_REMINDER: "交卡截止前提醒",
    CARD_SUBMITTED: "有人交卡了",
    CARD_REVIEW_RESULT: "交卡审批结果",
    GAME_START_REMINDER: "开团前提醒",
    GAME_CLOSE_REMINDER: "该结团了",
    AUTO_CLOSE_WARNING: "自动结团预警",
    REVIEW_OPENED: "团后评价已开放",
    REVIEW_WINDOW_CLOSING: "评价窗口即将关闭",
    GM_APPLICATION_RESULT: "GM 申请结果",
    GM_AUTO_PROMOTED: "你已自动获得 GM 身份",
    PHOTO_REPORT_RESULT: "照片举报处理结果",
    SITE_ANNOUNCEMENT: "站长公告",
}

EVENT_CHOICES = list(EVENT_LABELS.items())
ALL_EVENTS = tuple(EVENT_LABELS.keys())
