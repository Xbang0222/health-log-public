"""饮食与体重共用的日历日期解释；归属由各领域决定。"""

from __future__ import annotations

import re
from datetime import date, timedelta

from hl.language.normalize import number_value
from hl.language.phrases import _DAY_WORDS, _NOT_DAY_BEFORE, DAYS
from hl.language.weight_normalize import _range_at
from hl.language.weight_patterns import _CN_CHARS

# 说体重时说是哪天的（R16）：“今天、昨天、前天”“昨晚、前晚”（DAYS、_DAY_WORDS，从说这句话的那天
# 往前数），“上周五、上个星期天、周五”，“3天前”，“10月7号、7号”，“2026-10-07”。
# 没说哪一周的“周五”、没说哪个月的“9号”是最近的、不晚于说话那天的那一个；“这周五”还没到的不算。
# 写了哪一年的（“2025年10月7号”）是那一年的。引擎认不全的说法也不算（第十轮 W-1，规则 21）：
# 带修饰的“上上周五、下周五、上个月7号、下个月5号、去年10月7号”，范围“两三天前、2-3天前”
_WEEKDAY_OF = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


_RELATIVE_DAY = "|".join(
    f"(?<![{_NOT_DAY_BEFORE}])" * word.startswith("前") + word
    for word in sorted({**DAYS, **_DAY_WORDS, "今晨": 0}, key=len, reverse=True)
)


_SAID_DAY = re.compile(
    r"(?P<which>上上个?|下下个?|上个?|下个?|这个?|本)?(?<![每一])(?:周|星期|礼拜)"
    r"(?P<weekday>[一二三四五六日天])"
    rf"|(?<![\d.{_CN_CHARS}])(?P<back>\d{{1,3}}|[{_CN_CHARS}]{{1,4}})\s*天[以之]?前"
    r"|(?<![\d.])(?P<year>\d{4})-(?P<y_month>\d{1,2})-(?P<y_day>\d{1,2})(?![\d.])"
    rf"|(?<![\d.{_CN_CHARS}])(?:(?:(?P<c_year>\d{{4}})\s*年\s*)?"
    rf"(?P<month>\d{{1,2}}|[{_CN_CHARS}]{{1,3}})\s*月\s*)?"
    rf"(?P<day>\d{{1,2}}|[{_CN_CHARS}]{{1,3}})\s*[号日](?!常|记)"
    rf"|(?P<relative>{_RELATIVE_DAY})"
)

# 日子词前面带着的修饰，引擎认不全：说了哪一年（“去年、今年、二〇二五年”，四位数的年份另认）、
# 哪个月（“上个月、下个月、这个月”），或者是范围的头一个数（“2-3天前”“2到3天前”“两、三天前”）
_DAY_PREFIX = re.compile(rf"(?:年|[上下这本]个?月份?|[\d{_CN_CHARS}]\s*[-~〜到至、])\s*的?\s*$")


def _said_date(hit: re.Match[str], base: date) -> date | None:
    """日子词（见 _SAID_DAY）说的是哪天，从说这句话的那天 base 往前数；说的日子还没到、
    不是真的日子（“13月”“32号”）、引擎认不全的（“上上周五”“下周五”“两三天前”“上个月7号”
    “去年10月7号”，第十轮 W-1）返回 None。"""
    if hit.group("relative"):
        word = hit.group("relative")
        return base - timedelta(days=DAYS.get(word, _DAY_WORDS.get(word, 0)))
    if hit.group("weekday"):
        which = hit.group("which") or ""
        if which.startswith(("上上", "下")):
            return None
        day = base - timedelta(days=base.weekday() - _WEEKDAY_OF[hit.group("weekday")])
        if which.startswith("上"):
            return day - timedelta(days=7)
        if day > base:  # 没说哪一周的是最近的那个；“这周五”还没到
            return None if which else day - timedelta(days=7)
        return day
    if _DAY_PREFIX.search(hit.string, 0, hit.start()):
        return None
    if hit.group("back"):
        if _range_at(hit.group("back")) is not None:  # “两三天前”“一两天前”说的是范围
            return None
        back = number_value(hit.group("back"))
        return base - timedelta(days=int(back)) if 0 < back <= 366 and back == int(back) else None
    try:
        if hit.group("year"):
            day = date(int(hit.group("year")), int(hit.group("y_month")), int(hit.group("y_day")))
            return day if day <= base else None
        number = number_value(hit.group("day"))
        if hit.group("c_year"):  # “2025年10月7号”
            month = int(number_value(hit.group("month")))
            day = date(int(hit.group("c_year")), month, int(number))
            return day if day <= base else None
        if hit.group("month"):  # 没说哪年：最近的、不晚于这天的那个
            month = int(number_value(hit.group("month")))
            day = date(base.year, month, int(number))
            return day if day <= base else date(base.year - 1, month, int(number))
    except ValueError:
        return None
    for back in range(12):  # 没说哪个月的“9号”：最近的、不晚于这天的那个
        month = (base.month - back - 1) % 12 + 1
        year = base.year - (base.month - back <= 0)
        try:
            day = date(year, month, int(number))
        except ValueError:
            continue
        if day <= base and number == int(number):
            return day
    return None
