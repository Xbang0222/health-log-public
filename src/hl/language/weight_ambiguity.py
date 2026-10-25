"""体重模糊数字的完整识别与拒绝原因。"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator

from hl.language.normalize import clean, number_value, simplified
from hl.language.units import CLAUSE_END
from hl.language.weight_normalize import (
    _bare_unit,
    _clock_or_point,
    _range_at,
    _rough_value,
    _without_asides,
    with_points,
    without_times,
)
from hl.language.weight_odd_patterns import (
    _DIAN_PAIR,
    _FOREIGN_DIGITS,
    _FRACTION,
    _ODD_POINT,
    _ODD_SEPARATOR,
    _OTHER_AMOUNT,
    _ROUGH,
    _ROUGHLY,
    _SCRIPTED,
    _SPACED_FRACTION,
)
from hl.language.weight_patterns import (
    _CN_CHARS,
    _JIN_LEFTOVER,
    _POINT_UNIT,
    _UNIT_AFTER,
    _UNIT_LEFTOVER,
    _WEIGHT,
    _WEIGHT_UNITS,
    KG_PER,
    PLAUSIBLE_KG,
)
from hl.language.weight_words import _ENDS_WITH_WEIGHT_WORD, _KEYCAP_NUMBER


def unclear_numbers(message: str) -> list[tuple[str, str]]:
    """原话所在的整条消息里写法认不准的数，连同认不准在哪（R16）：有一处，整句都不拿来取体重。

    不是 0-9 的数字（“٧٨٫٥”，见 _FOREIGN_DIGITS）、分数（“78½”，见 _FRACTION）、
    上标下标数字（“78.5²”，见 _SCRIPTED）、
    句号逗号和别的符号当小数点写的（“78。5”“78,5kg”“78..5”“78·5”“78、5”，
    见 _ODD_POINT、_ODD_SEPARATOR）、单位后面还跟着没读进来的数的
    （“124斤6”“156斤 半”“78公斤5”，见 _JIN_LEFTOVER、_UNIT_LEFTOVER）认不准。
    明确的钟点和日期先去掉（见 without_times）。另外认不准的有四种：阿拉伯数字和中文数字用“点”
    混着写（“78点五”“8点五十”）；“点”前后夹着空格（“78 点 5”）；“点”前面的数不超过 24、
    后面没带单位，钟点和小数都说得通（“8点5”“七点三十”）；约数（“150多斤”“七十几”
    “77.6左右”“大概77.6”“七八十斤”，见 _ROUGH、_ROUGHLY）。
    第三种后面紧跟体重单位的，看两种读法换算成公斤哪种像体重（见 _clock_or_point）：只有小数像的
    按小数认（“22点5公斤”），只有钟点像的按钟点（“8点70公斤”），都像的认不准（“22点65公斤”）；
    带着别的单位、百分比里的（“5点5公里”“体脂22点5%”）怎么读都不是体重，也不算。
    约数换算成公斤不像体重的（“十来天”）不算。
    看整条消息，不只看模型抄的那段：抄窄一点（只抄“早上8点5”后面那一句）绕不过去。
    """
    seen = clean(message)  # 给用户看的从这里取：繁体字照原样
    text = simplified(seen)
    bare = _bare_unit(text, None)
    plain, pointed, rest = without_times(text), with_points(text), _without_asides(text)
    found = [
        (hit.group(), "是数字表情，不能按普通数字读取") for hit in _KEYCAP_NUMBER.finditer(seen)
    ]
    found += [(hit.group(), "用的不是 0-9 这样的数字") for hit in _FOREIGN_DIGITS.finditer(seen)]
    found += [(hit.group(), "是分数") for hit in _FRACTION.finditer(message)]
    found += [(hit.group(), "带着上标或下标数字") for hit in _SCRIPTED.finditer(message)]
    found += [(hit.group(), "是分数") for hit in _SPACED_FRACTION.finditer(seen)]
    odd_point = "中间夹的不是小数点，可能是一个数，也可能是两个数"
    for hit in _ODD_POINT.finditer(unicodedata.normalize("NFKC", message)):
        found.append((hit.group(), odd_point))
    for hit in _ODD_SEPARATOR.finditer(rest):  # 后面跟着量词的说的是别的（“10、20个”）
        if not _OTHER_AMOUNT.match(rest, hit.end()):
            found.append((seen[hit.start() : hit.end()], odd_point))
    # “124斤6”“78公斤5”：单位后面的 6、5 没读进来；后面再跟着量词的是别的数（“78公斤 3 天没称”）
    for hit in _WEIGHT.finditer(rest):
        unit = hit.group("unit")
        if not unit or hit.group("half") or hit.group("liang"):
            continue
        jin = _WEIGHT_UNITS[unit.casefold()] == "斤"
        left = (_JIN_LEFTOVER if jin else _UNIT_LEFTOVER).match(rest, hit.end())
        if left and not _OTHER_AMOUNT.match(rest, left.end()):
            said_unit = seen[hit.start("unit") : hit.end("unit")]
            why = "可能是几两，也可能是别的" if jin else "可能是小数，也可能是别的"
            found.append((seen[hit.start() : left.end()], f"{said_unit}后面还跟着数，{why}"))
    for hit in _DIAN_PAIR.finditer(plain):
        left, gap, right = hit.groups()
        spot = seen[hit.start() : hit.end()]
        if left == "一" and right[0].isdigit():
            continue  # “胖了一点140斤”“差一点70”：“一点”是“一点儿”，后面的是另一个数
        if left[0].isdigit() != right[0].isdigit():
            found.append((spot, "是阿拉伯数字和中文数字混着写的"))
        elif gap != "点":
            found.append((spot, "在“点”前后夹着空格"))
        elif (
            number_value(left) <= 24
            and rest[hit.start() : hit.end()] == hit.group()  # 没被涂掉，也没换成小数点
            and not _UNIT_AFTER.match(plain, hit.end())
        ):
            found.append((spot, "可能是钟点，也可能是小数"))
    for hit in _POINT_UNIT.finditer(plain):  # “22点65公斤”：22.65 公斤、22 点钟的 65 公斤都像体重
        if _clock_or_point(hit) == "both":
            found.append((seen[hit.start() : hit.end()], "可能是钟点，也可能是小数"))
    rough: list[tuple[int, int]] = []
    # 约数换算成公斤像体重才算（“十来天”“将近一个月”不算）；后面跟着天、个、次这些量词的
    # 说的是别的量（“二十多天”，见 _MEASURE_WORDS）；“78来着”是在回想，不拒绝（一眼清不清楚
    # 照样算它，见 at_a_glance）；中间涂掉过钟点的不算（“78 十点多”“大概8点 78”）；
    # 和已经挑出的重叠的不再算一遍
    for start, end, number, unit in _rough_hits(rest):
        kg = _rough_value(number) * KG_PER[_WEIGHT_UNITS[unit.casefold()] if unit else bare]
        if unit is None and (_OTHER_AMOUNT.match(rest, end) or rest[end - 1 : end + 1] == "来着"):
            continue
        if (
            PLAUSIBLE_KG[0] <= kg <= PLAUSIBLE_KG[1]
            and rest[start:end] == pointed[start:end]
            and not any(start < done_end and done_start < end for done_start, done_end in rough)
        ):
            rough.append((start, end))
    found += [(seen[start:end], "是约数") for start, end in sorted(rough)]
    return found


def _drawn_out(rest: str, start: int) -> bool:
    """rest[start] 是拖长音的“~”：紧跟在汉字或字母后面（“早~”“哈喽~”“hi~”），
    而前面不是说体重的词（“体重~78.5”“现在~78.5”的“~”照旧是约数）、中文数字（“七十八~七十九”
    是范围）。约数词、上下限词后面的（“大约~78.5”“超过~80”）连着那个词一起认（见 _HEDGE）。"""
    if start < 1 or rest[start] not in "~〜" or not rest[start - 1].isalpha():
        return False
    if rest[start - 1] in _CN_CHARS:  # “七十八~七十九”：范围（第十轮 W-6）
        return False
    return _ENDS_WITH_WEIGHT_WORD.search(rest, 0, start) is None


_PAIRED_MARKS = {"》": "《", "〉": "〈", "›": "‹", "»": "«", ">": "<"}


def _title_mark(rest: str, start: int) -> bool:
    """rest[start] 是成对的书名号、尖括号的后一半，括着的只有字、没有数（“《体重》78.5”
    “〈体重〉78.5”）：是标点，不是大于号（第十轮 W-9）。"""
    opener = _PAIRED_MARKS.get(rest[start]) if start > 0 else None
    head = rest.rfind(opener, 0, start) if opener else -1
    if head < 0 or head + 1 == start:
        return False
    inside = rest[head + 1 : start]
    return not any(ch.isdigit() or ch in CLAUSE_END + opener + rest[start] for ch in inside)


def _rough_hits(rest: str) -> Iterator[tuple[int, int, str, str | None]]:
    """每一处约数的说法（见 _ROUGH、_ROUGHLY）：（起，止，数，紧跟着的体重单位），不管它说的是什么。

    rest 是涂掉了一看就不是体重的数的原话（见 _without_asides）。
    """
    for hit in _ROUGH.finditer(rest):
        yield *hit.span("spot"), hit.group("num"), hit.group("unit")
    at = 0
    while hit := _ROUGHLY.search(rest, at):
        at = hit.end()
        if _drawn_out(rest, hit.start("hedged")) or _title_mark(rest, hit.start("hedged")):
            # 跳过这个“~”“》”，后面的数照样看有没有别的约数说法
            at = hit.start("hedged") + 1
            continue
        if hit.group("hedged"):
            yield *hit.span("hedged"), hit.group("said"), hit.group("said_unit")
        else:
            yield *hit.span("spot"), hit.group("num"), hit.group("unit") or hit.group("tail_unit")
    for hit in _WEIGHT.finditer(rest):  # “七八十斤”“一百五六十斤”：挨着的两个数说的是范围
        if hit.group("cn") and hit.group("unit") and _range_at(hit.group("cn")) is not None:
            yield hit.start(), hit.end("unit"), hit.group("cn"), hit.group("unit")
