"""体重输入的时间过滤、单位注记与基础数字归一。"""

from __future__ import annotations

import re

from hl.language.normalize import clean, cn_number, number_value, simplified
from hl.language.units import _CN_DIGITS, _CN_UNITS, CLAUSE_END
from hl.language.weight_odd_patterns import _ASIDES
from hl.language.weight_patterns import (
    _ABOUT,
    _BY_VERB,
    _DATES,
    _DIGITS_AND_CN,
    _HOUR,
    _NOT_A_NOTE,
    _POINT,
    _POINT_UNIT,
    _SCALE_VERBS,
    _UNIT_NOTE,
    _UNIT_WORD,
    _WEIGHT,
    _WEIGHT_UNITS,
    KG_PER,
    PLAUSIBLE_KG,
)


def _weight_text(text: str) -> str:
    """认体重之前先折一遍：全角折成半角（见 clean），繁体字折成简体（“七十八點五”“155斤2兩”）。
    长度和 clean(text) 一样，给用户看原话的写法时从 clean(text) 的同一处取。"""
    return simplified(clean(text))


def _blank(found: re.Match[str]) -> str:
    return " " * len(found.group())


def _date(hit: re.Match[str]) -> str:
    """日期涂成空格；月份大于 12、号数大于 31、钟点大于 24、年份不是四位数的不是日期，原样留下。"""
    if hit.group("hour"):
        sure = int(hit.group("hour")) <= 24
    elif hit.group("month"):
        sure = int(hit.group("month")) <= 12 and int(hit.group("day")) <= 31
    elif hit.group("y"):
        year = hit.group("n")
        digits = all(ch in _CN_DIGITS for ch in year)
        sure = len(year) == 4 if year[0].isdigit() else len(year) > 1 and digits
    elif hit.group("n"):
        value = number_value(hit.group("n"))
        sure = value <= 12 if hit.group("m") else value <= 31
    else:
        sure = True
    return _blank(hit) if sure else hit.group()


def _clock_or_point(hit: re.Match[str]) -> str:
    """“N点M”后面紧跟着体重单位（见 _POINT_UNIT）怎么读：两种读法换算成公斤，只有按小数读像体重
    是 "point"（“22点5公斤”），只有按“N 点钟、M 个单位”读像体重是 "clock"（“8点70公斤”），
    都像是 "both"（“22点65公斤”）。都不像的按小数读，由取数的地方说它不像体重。
    “点”后面的中文数字带着十、百、千（“六十五”）不会是小数部分；混着写的另外挑
    （见 unclear_numbers）。
    """
    n, m = hit.group("n"), hit.group("m")
    if n[0].isdigit() != m[0].isdigit() or number_value(n) > 24:
        return "point"
    per = KG_PER[_WEIGHT_UNITS[hit.group("unit").casefold()]]
    clock = PLAUSIBLE_KG[0] <= number_value(m) * per <= PLAUSIBLE_KG[1]
    if m[0].isdigit():
        point = float(f"{n}.{m}")
    else:
        point = 0.0 if set(m) & set("十百千两") else cn_number(f"{n}点{m}")
    point_ok = PLAUSIBLE_KG[0] <= point * per <= PLAUSIBLE_KG[1]
    if clock and point_ok:
        return "both"
    return "clock" if clock else "point"


def without_times(text: str) -> str:
    """把明确的钟点和日期涂成空格（长度不变）：“早上 7 点称的”“10月8号”里的数不是在说量。

    “8点5”这种钟点、小数都说得通的不涂（见 _HOUR、unclear_numbers）。“8点70公斤”只有按钟点读
    才像体重，涂掉“8点”（见 _clock_or_point）。
    """

    def hour(hit: re.Match[str]) -> str:
        return _blank(hit) if number_value(hit.group(1)) <= 24 else hit.group()

    def clock(hit: re.Match[str]) -> str:
        if _clock_or_point(hit) != "clock":
            return hit.group()
        return " " * (hit.start("m") - hit.start()) + hit.group("m")

    return _DATES.sub(_date, _HOUR.sub(hour, _POINT_UNIT.sub(clock, text)))


def with_points(text: str) -> str:
    """认得准的“点”换成小数点（长度不变）：“78点5”→“78.5”，“22点5公斤”→“22.5公斤”（R16）。

    “点”前面的数不超过 24、后面又没带体重单位的不换：钟点（“7点5分”）不会被换，
    “8点5”钟点、小数都说得通，留给 unclear_numbers。“0点3”的“点”是小数点：钟点不这么说。
    """

    def point(hit: re.Match[str]) -> str:
        whole = int(hit.group("whole"))
        sure = whole > 24 or (whole == 0 and hit.group("minute") is None)
        if hit.group("unit") is not None and not sure:  # “22点5公斤”是小数，“8点70公斤”是钟点
            found = _POINT_UNIT.match(text, hit.start())
            sure = found is None or _clock_or_point(found) == "point"
        return hit.group("whole") + ("." if sure else "点")

    return _POINT.sub(point, text)


def _without_asides(text: str) -> str:
    """把一看就不是体重的数涂成空格（长度不变）：钟点、日期、百分比、序数、带着别的单位的数。"""
    return _ASIDES.sub(_blank, without_times(with_points(text)))


def _unit_note(text: str, context: str | None) -> tuple[str, str, tuple[int, int]] | None:
    """用户单说的单位（“单位是斤”“按斤算”）：（单位，那句话，那句话的位置）；没说过返回 None。

    说单位的那个分句是在问的（“单位是斤吗？”“按斤算是多少”）不算。位置在 context
    （没给 context 就是 text）里，“按斤算”连后面的“算”一起。
    """
    source = text if context is None else _weight_text(context)
    for note in _UNIT_NOTE.finditer(source):
        start, end = note.span(note.lastgroup)
        # 写在数前面的单位，往前隔着空白紧挨着别的数（“瘦了 2 斤 70”）：是那个数的单位（第十轮 W-5）
        if note.lastgroup == "before" and source[:start].rstrip()[-1:] in _DIGITS_AND_CN:
            continue
        head = max(source.rfind(ch, 0, start) for ch in CLAUSE_END) + 1
        tail = min((pos for ch in CLAUSE_END if (pos := source.find(ch, end)) >= 0), default=None)
        clause = source[head : None if tail is None else tail + 1]
        if not any(word in clause for word in _NOT_A_NOTE):
            unit = _WEIGHT_UNITS[note.group(note.lastgroup).casefold()]
            stop = note.end()
            if note.lastgroup == "by":
                stop = _BY_VERB.match(source, stop).end()
            return unit, note.group().strip(CLAUSE_END + " "), (note.start(), stop)
    return None


def _loose_unit(text: str) -> bool:
    """原话里有没跟在数后面的体重单位（“我习惯用斤”“这是磅吗”）：没写单位的数就不一定是公斤。"""
    for word in _SCALE_VERBS:
        text = text.replace(word, " " * len(word))
    attached = [hit.span("unit") for hit in _WEIGHT.finditer(text) if hit.group("unit")]
    return any(hit.span() not in attached for hit in _UNIT_WORD.finditer(text))


def _bare_unit(text: str, context: str | None) -> str:
    """数字后面没带单位时按什么算：用户明说了的（“单位是斤”“按斤算”），否则公斤。"""
    note = _unit_note(text, context)
    return note[0] if note else "公斤"


def _range_at(word: str) -> int | None:
    """中文数字里说范围的那两个数字的位置：“两三”“七八十”“一百五六十”“七十七八”“三五”。

    范围是挨着的两个数（差 1，或者“三五”）；“一米七五”的“七五”是逐位读的 75。
    没有十、百、千的长串也是逐位读的（“一七五”），不算范围。
    """
    head = word.partition("点")[0]
    if len(head) > 2 and not any(ch in _CN_UNITS for ch in head):
        return None
    for pos, (one, two) in enumerate(zip(head, head[1:], strict=False)):
        low, high = _CN_DIGITS.get(one, 0), _CN_DIGITS.get(two, 0)
        if low and high and (high - low == 1 or (low, high) == (3, 5)):
            return pos
    return None


def _cn_value(word: str) -> float:
    """体重里的中文数字的值；说的是范围时取大的那头（“两三”是 3，“七八十”是 80）。"""
    pos = _range_at(word)
    return cn_number(word if pos is None else word[:pos] + word[pos + 1 :])


def _rough_value(number: str) -> float:
    """约数里的数：“150 多”的 150，“七八十”的 80（范围取大的那头）。"""
    number = number.rstrip(_ABOUT + "xX?").strip()
    if not (number[-1].isalnum() or number[-1] in "点."):  # “78.*”“78.△”（第十轮 W-8）
        number = number[:-1]
    number = number.rstrip("点.")
    return float(number) if number[0].isdigit() else _cn_value(number)
