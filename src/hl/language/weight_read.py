"""体重、身高及数值提及提取。"""

from __future__ import annotations

from hl.language.normalize import clean, number_value, simplified
from hl.language.units import _CN_DIGITS
from hl.language.weight_normalize import (
    _cn_value,
    _loose_unit,
    _range_at,
    _unit_note,
    _weight_text,
    _without_asides,
)
from hl.language.weight_patterns import (
    _AFTER_HEIGHT,
    _ANY_NUMBER,
    _HEIGHT_UNIT,
    _LETTERS,
    _METRES,
    _NOT_NUMBERS,
    _ODD_KG,
    _ODD_UNIT,
    _WEIGHT,
    _WEIGHT_UNITS,
    KG_PER,
)
from hl.language.weight_types import WeightMention


def _weight_marks(said: str, context: str | None = None) -> list[tuple[WeightMention, bool]]:
    """原话里可能是体重的每个数（阿拉伯数字和中文数字），和它是不是身高。

    一看就不是体重的数先去掉（见 _without_asides）；不看前后的词猜，像不像体重看换算成的公斤数。
    数字后面连着斤、磅就按斤、磅换算，再跟一个“半”是多半个单位，斤后面跟“M两”是多 M/10 斤；
    后面没有单位、而用户明说了单位（“单位是斤”“按斤算”）时按那个单位——这句话可以在
    context（原话所在的整条消息）的别的分句里。
    没带体重单位的中文数字记下它的写法（spoken）；一个字的（“一下”“一直”“老百姓”）不是在说数，
    两个字逐位读的（“五一”“六一”“九九”）是节日、编号，都不算。
    身高：前面是“身高”，后面是 cm、厘米、公分，“1.75 米”，或“1 米 75”里“米”后面的数。
    """
    seen = clean(said)  # 给用户看的从这里取：繁体字照原样
    text = simplified(seen)
    note = _unit_note(text, context)
    loose = note is not None or _loose_unit(text if context is None else _weight_text(context))
    plain = _without_asides(text)
    marks = []
    for match in _WEIGHT.finditer(plain):
        cn, said_unit = match.group("cn") or "", match.group("unit")
        if cn and said_unit is None and (len(cn) == 1 or not set(cn) & set(_CN_DIGITS)):
            continue
        number = _cn_value(cn) if cn else float(match.group("num"))
        whole = number if match.group("half") or match.group("liang") else None
        if match.group("half"):
            number += 0.5
        elif match.group("liang"):
            number = round(number + number_value(match.group("liang")) / 10, 6)
        unit = _WEIGHT_UNITS[said_unit.casefold()] if said_unit else note[0] if note else "公斤"
        height = said_unit is None and (
            _AFTER_HEIGHT.search(text[: match.start()]) is not None
            or _HEIGHT_UNIT.match(text, match.end()) is not None
            or (number < 3 and _METRES.match(text, match.end()) is not None)
        )
        # “五一”“九九”：节日、编号，不算；“一米七五”的“七五”是身高，“两三”“七八”是范围，照算
        coded = len(cn) == 2 and set(cn) <= set(_CN_DIGITS) and _range_at(cn) is None
        if cn and said_unit is None and coded and not height:
            continue
        # 原话里的写法从没涂过、没换过小数点的原文里取（“78点5”“七十八點五”照原样给用户看）
        figure = seen[match.start() : match.start("unit") if said_unit else match.end()].strip()
        letters = None if said_unit else _LETTERS.match(text, match.end())
        odd = letters.group(1) if letters else ""
        span = (match.start(), letters.end() if letters else match.end())
        noted = note[2] if note and not said_unit else None
        if said_unit:
            gap = " " if figure[-1].isdigit() else ""
            shown = figure + gap + seen[match.start("unit") : match.end()].strip()
        elif odd:  # “172 Ibs（引擎不认“Ibs”这个单位，按公斤算）”
            told = f"；原话说了“{note[1]}”，" if note else "，"
            shown = f"{figure} {odd}（引擎不认“{odd}”这个单位{told}按{unit}算）"
        elif note:
            shown = f"{figure}（原话说了“{note[1]}”，按{unit}算）"
        else:
            shown = f"{figure}（没写单位，按公斤算）"
        dian = "点" in text[match.start() : match.end()]
        is_plain = not cn and not dian and not odd and (said_unit is not None or not loose)
        spoken = seen[match.start("cn") : match.end("cn")] if cn and said_unit is None else ""
        written = seen[match.start("unit") : match.end("unit")] if said_unit else ""
        mention = WeightMention(
            number,
            number * KG_PER[unit],
            unit,
            whole,
            spoken,
            shown,
            is_plain,
            span,
            noted,
            written,
        )
        marks.append((mention, height))
    return marks


def weights_in(said: str, context: str | None = None) -> list[WeightMention]:
    """原话里除了身高的每个数，换算成公斤不像体重的也在（看 plausible）。

    context 是原话所在的整条消息（找单说的单位用）。
    """
    return [mention for mention, height in _weight_marks(said, context) if not height]


def heights_in(said: str) -> list[float]:
    """原话里说的是身高的数：不能当成体重。"""
    return [mention.number for mention, height in _weight_marks(said) if height]


def numbers_in(text: str) -> list[str]:
    """一段话里的每个数（R16 看体重一眼清不清楚用），宁可多算：多算只是多问一次，少算会记错。

    阿拉伯数字串（带一个小数点的算一个：“78.5”）、中文数字（含“两”“半”“万”）各算一个；
    钟点、日期、带着别的单位的数也都算。只排除几个明显不是在说数的词（“一下”“一直”）。
    """
    text = _weight_text(text)
    for word in _NOT_NUMBERS:
        text = text.replace(word, " " * len(word))
    return _ANY_NUMBER.findall(text)


def odd_weight_units(said: str) -> list[tuple[str, float]]:
    """原话里跟在数字后面、引擎不认的重量单位（英石、盎司、台斤、港斤），连同那个数换算成的公斤数。

    1 结尾（11 除外）、紧挨着 st 的是序数（“Oct 21st”“31st”），不是英石；“11st”是 11 英石。
    """
    found = []
    for hit in _ODD_UNIT.finditer(_weight_text(said)):
        unit, number = hit.group(2).casefold(), hit.group("n")
        ordinal = unit == "st" and hit.end("n") == hit.start(2) and number.endswith("1")
        if not ordinal or number.endswith("11"):
            found.append((unit, number_value(number) * _ODD_KG[unit]))
    return found
