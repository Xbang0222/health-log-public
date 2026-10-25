"""份量token、完整数字读法及量词词法。"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterator
from dataclasses import dataclass

from hl.language.normalize import cn_number
from hl.language.units import (
    _CN_DIGITS,
    _CN_UNITS,
    _FILLERS,
    _NEED_NUMBER,
    _UNIT_SYNONYMS,
    COUNTERS,
    UNIT_FORMS,
)


# ---------- 份量（R4；增补第 4、6 节） ----------
@dataclass(frozen=True)
class Quantity:
    """原话里的一处份量：数、单位、在原话里的起止位置。

    n 是引擎记下的数：约数（“两三个”）是中间值，“一碗半”是 1.5，“一斤二两”是 1.2 斤。
    readings 是模型传哪个数都认的：约数的两头和中间值，分数四舍五入到两三位的；别的只有 n。
    parts 是用户连着说的一整个份量里的一截（“一碗半”的 1 碗，“一斤二两”的 1 斤、2 两）：
    模型只传其中一截要拒绝。rough：份量是大概的（约数、“200多克”、量词前有大小）；
    约数词（“大概”）另看，见 hedge_near。bare：量词前面没有数字，记 1（“吃了个苹果”）。
    """

    n: float
    unit: str
    start: int
    end: int
    rough: bool = False
    readings: tuple[float, ...] = ()
    parts: tuple[tuple[float, str], ...] = ()
    bare: bool = False


_QTY_DIGITS = "一二两三四五六七八九"


_QTY_CHARS = "零〇一二三四五六七八九十百千"  # 不含“两”：见 _QTY_INT

# 份量里的中文数字。“两”在开头，或者后面还连着数字（“一千两百”）时是数；“二两”“十两”的“两”是单位。
# “千克”的“千”是单位：“两千克”是 2 公斤，“2千克”不是“2千”加“克”
_QTY_INT = rf"(?!千克)[{_QTY_CHARS}两](?:(?!千克)[{_QTY_CHARS}]|两(?=[{_QTY_CHARS}]))*"


_QTY_CN = rf"{_QTY_INT}(?:点[零〇一二三四五六七八九]+)?"


_QTY_NUMBER = re.compile(rf"\d+(?:\.\d+)?|{_QTY_CN}")

# 有界约数：十几到九十几，按个位1至9的中间值记；只有“几/几十”仍追问。
_QTY_OPEN_TEN = re.compile(r"(?P<base>[一二两三四五六七八九]?十)几")


_QTY_TERM = re.compile(rf"{_QTY_OPEN_TEN.pattern}|{_QTY_NUMBER.pattern}")


_QTY_LINK = re.compile(r"\s*(?:-|−|~|〜|到|至|或(?:者)?|、)\s*")

# 分数是数：“二分之一”“1/2”（“½”折成半角是“1⁄2”）
_QTY_FRACTION = re.compile(
    rf"(?P<den>\d+|{_QTY_INT})分之(?P<num>\d+|{_QTY_INT})|(?P<a>\d+)\s*[/⁄]\s*(?P<b>\d+)(?![\d.])"
)

# 约数：“2-3个”“2~3个”“两到三个”“一至两碗”，“两、三个”“1、2个”（一位数连着的两个）
_QTY_SPAN = re.compile(
    rf"(?P<lo>{_QTY_NUMBER.pattern})\s*(?:-|~|〜|到|至)\s*(?P<hi>{_QTY_NUMBER.pattern})"
)


_QTY_LISTED = re.compile(
    rf"(?P<lo>[{_QTY_DIGITS}1-9])、(?P<hi>[{_QTY_DIGITS}1-9])(?![\d.{_QTY_CHARS}两])"
)

# 两个个位数连写的约数：“两三个”“三五个”“二三十”“两三百”“一百五六十”“十一二个”“二十三四个”。
# “三两个”是两三个（后面得跟量词，“三两米饭”是三两）
_QTY_PAIR = re.compile(
    rf"(?P<pre>(?:[{_QTY_DIGITS}]?(?!千克)[十百千])+)?(?P<lo>[{_QTY_DIGITS}])(?P<hi>[{_QTY_DIGITS}])"
    rf"(?P<times>(?!千克)[十百千])?(?![\d.点{_QTY_CHARS}])"
)


_QTY_START = re.compile(rf"\d|[{_QTY_CHARS}两半俩仨]")

# 夹在数和量词中间、说明份量是大概的字（“200多克”“一大碗”）；“一整个”不算
_ROUGH_FILLERS = "多来余大小满"

# 数前面是这些字的，不是在说份量：序数（第二碗）、每个、不确定的数（几十克）
_NOT_A_COUNT = "第每几数"

# 说两个人的“俩、仨”（“我们俩”“他仨”“哥俩”）不是 2 个、3 个
_PEOPLE_BEFORE = "们他她它咱你我哥姐娘爷妹弟"

# 量词后面跟着这些，说的是人、钱、时间（“一个人”“一块钱”“一个半小时”“一个多月”），不是份量。
# “月饼、年糕”是吃的
_NOT_FOOD_AFTER = re.compile(
    r"\s*(?:人(?!参)|钱|元|小时|钟头|钟|分钟|秒|月(?!饼)|星期|礼拜|周(?!黑)|年(?!糕)|岁|天|时间)"
)

# 量词连着下一个字是别的词（“包子”的“包”，“份量”的“份”，“一块儿”是一起）
_IN_WORDS = ("包子", "包菜", "份量", "块儿")

# 斤后面的几两：“一斤二两”“1斤2两”“一斤零二两”；没说“两”的只认紧挨着、说到这儿就停的
# 一位数（“牛肉一斤二”）。“两斤五花肉”的“五”是下一个词的头
_QTY_LIANG = re.compile(r"\s*零?\s*(?P<m>[一二三四五六七八九]|[1-9](?![\d.]))\s*两(?P<half>半)?")


_QTY_LIANG_ALONE = re.compile(
    r"零?(?P<m>[一二三四五六七八九]|[1-9](?![\d.]))(?=$|[^\w]|[了啊呀呢吧哦嘛的哈])"
)


@functools.cache
def _unit_word(extra: tuple[str, ...]) -> re.Pattern[str]:
    """紧跟在数后面的单位或量词（中间可以夹一个“多、来、大、小”这类字），长的先认。

    extra 是概念、菜谱自己的量词（“小碗”）：先按整个词认，再按“小”加“碗”认。
    字母单位后面不能再连着字母（“2lb”不是 2 升）。
    """
    words = sorted({*_UNIT_SYNONYMS, *COUNTERS, *extra}, key=len, reverse=True)
    alternatives = "|".join(re.escape(w) + ("(?![a-z])" if w.isascii() else "") for w in words)
    return re.compile(
        rf"\s*(?:(?P<unit>{alternatives})|(?P<filler>[{_FILLERS}])\s*(?P<filled>{alternatives}))",
        re.IGNORECASE,
    )


@functools.cache
def _bare_word(extra: tuple[str, ...]) -> re.Pattern[str]:
    """前面没有数字的量词（“吃了个苹果”“大碗面”）。通用重量体积单位必须带数，不在这里。"""
    words = sorted({*COUNTERS, *extra} - set(_NEED_NUMBER), key=len, reverse=True)
    return re.compile(rf"(?P<filler>[大小满整])?(?P<unit>{'|'.join(map(re.escape, words))})")


def _unit_of(word: str) -> str:
    """原话里的单位写法 → 引擎记下的叫法（“千克”→公斤，“克”→g）；量词照原样。"""
    return _UNIT_SYNONYMS.get(word.casefold(), word)


def unit_name(unit: str) -> str:
    """问话、说明里怎么念这个单位：g 念“克”，ml 念“毫升”，别的照原样。"""
    return next((form for form in UNIT_FORMS.get(unit, ()) if not form.isascii()), unit)


@dataclass(frozen=True)
class _Count:
    """数后面还没接单位的那个数。whole：整数，后面可以接“半”、斤后面可以接几两。
    needs_counter：“一两”“三两”读成约数，只有后面跟着量词才成立。"""

    n: float
    readings: tuple[float, ...]
    end: int
    rough: bool = False
    whole: bool = False
    needs_counter: bool = False


def _qty_value(word: str) -> float:
    return float(word) if word[0].isdigit() else cn_number(word)


def _span(lo: float, hi: float, end: int, needs_counter: bool = False) -> _Count:
    middle = (lo + hi) / 2
    return _Count(middle, (lo, hi, middle), end, rough=True, needs_counter=needs_counter)


def _counts_at(text: str, pos: int) -> Iterator[_Count]:
    """从 pos 开始的数的各种读法，先试的优先：分数、约数，再是一个数。"""
    if text[pos] == "半":
        yield _Count(0.5, (0.5,), pos + 1)
        return
    if found := _QTY_OPEN_TEN.match(text, pos):
        base = int(cn_number(found["base"]))
        yield _Count(base + 5, tuple(range(base + 1, base + 10)), found.end(), rough=True)
        return
    if found := _QTY_FRACTION.match(text, pos):
        den, num = (found["den"], found["num"]) if found["den"] else (found["b"], found["a"])
        if _qty_value(den):
            value = _qty_value(num) / _qty_value(den)
            rounded = (value, round(value, 2), round(value, 3))
            yield _Count(value, tuple(dict.fromkeys(rounded)), found.end())
        return
    found = _QTY_SPAN.match(text, pos) or _QTY_LISTED.match(text, pos)
    if found:
        lo, hi = _qty_value(found["lo"]), _qty_value(found["hi"])
        listed = found.re is _QTY_LISTED
        if lo < hi and (not listed or hi - lo == 1 or (lo, hi) == (3, 5)):
            yield _span(lo, hi, found.end())
    if found := _QTY_PAIR.match(text, pos):
        lo, hi = _CN_DIGITS[found["lo"]], _CN_DIGITS[found["hi"]]
        if hi - lo == 1 or (lo, hi) == (3, 5) or found.group("lo", "hi") == ("三", "两"):
            pre = found["pre"]
            if found["times"]:
                times = _CN_UNITS[found["times"]]
            else:  # “一百五六”的五六是五十、六十；“十一二”“二十三四”是个位
                times = _CN_UNITS.get(pre[-1], 10) // 10 if pre else 1
            base = cn_number(pre) if pre else 0
            low, high = sorted((base + lo * times, base + hi * times))
            yield _span(low, high, found.end(), needs_counter=found["hi"] == "两")
    if found := _QTY_NUMBER.match(text, pos):
        word = found.group()
        # 逐位读的中文数字（“二五个”）不是份量的说法，认不准
        if word[0].isdigit() or len(word) == 1 or any(ch in word for ch in "十百千点"):
            value = _qty_value(word)
            yield _Count(value, (value,), found.end(), whole=value.is_integer())
