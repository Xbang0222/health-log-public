"""原话清理、繁简归一、中文数字与单位同义归一。"""

from __future__ import annotations

import copy
import re
import unicodedata
from importlib import resources
from typing import Any

from hl.language.units import (
    _CN_DIGITS,
    _CN_UNITS,
    _KILO_UNITS,
    _NET_SYNONYMS,
    _STATE_SYNONYMS,
    _UNIT_SYNONYMS,
)
from hl.language.weight_patterns import _THOUSANDS, _WIDE_COMMA


def clean(text: str) -> str:
    """全角数字、字母、标点折成半角，后面的识别只面对一种写法。

    “1,800”里的千位分隔逗号去掉，当一个数认。全角逗号夹在两个数字之间是句读（“78，200克”），
    折成半角时在后面补一个空格，免得再折一遍被当成千位分隔。
    """
    text = _THOUSANDS.sub(lambda found: found.group().replace(",", ""), text)
    return unicodedata.normalize("NFKC", _WIDE_COMMA.sub("， ", text))


# 看不见的字符：格式字符（零宽空格、零宽连接符、BOM、方向标记……）和变体选择符
_INVISIBLE = re.compile(r"[\ufe00-\ufe0f\U000e0100-\U000e01ef]")


def visible(text: str) -> str:
    """去掉看不见的字符（多是复制粘贴带进来的）：“78\u200b.5”是 78.5，问话里也不念出空引号
    （第九轮 W-5、W-7）。认体重、hl add 的份量、hl plan 的数时用（第十轮 W-10）；
    核对原话（R2）照原样比。"""
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    return _INVISIBLE.sub("", text)


def fmt(value: float) -> str:
    """200.0 → "200"，0.5 → "0.5"。"""
    return str(int(value)) if float(value).is_integer() else f"{value:.10g}"


# ---------- 比较两句话用的归一化（R2、R11） ----------
def fold(text: str) -> str:
    """全角折成半角，大写折成小写。"""
    return clean(text).casefold()


def _simplified_table() -> dict[int, str]:
    """data/simplified.txt：每行“繁体<Tab>简体”，# 开头的是说明。"""
    text = resources.files("hl").joinpath("data", "simplified.txt").read_text(encoding="utf-8")
    pairs = [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]
    return {ord(old): new for old, new in pairs}


# 繁体字、异体字折成简体（“點”“兩”“於”“對”“錯”“觔”）：一个字换一个字，位置不变
_SIMPLIFIED = _simplified_table()


def simplified(text: str) -> str:
    """繁体字一个字换一个简体字，位置和长度不变：认体重（R16）、判断用户的回答（R19）都先折这一遍，
    给用户看原话时从折之前的同一处取。比较两句话（fold、compact）不折：它们决定记录的编号。"""
    return text.translate(_SIMPLIFIED)


def kind(ch: str) -> str:
    """字符的大类：L 字、N 数、P 标点、S 符号、Z 空白、C 控制符。"""
    return unicodedata.category(ch)[0]


def squeeze(folded: str) -> tuple[str, list[int]]:
    """去掉空白、标点、符号，返回留下的字符和它们在原文里的位置。

    两个数字之间的不去掉（符号照留，一串空白留一个空格）：1.5、1-2、1/2、1 2 都不是 12。
    """
    chars: list[str] = []
    places: list[int] = []
    last = None
    for pos, ch in enumerate(folded):
        if kind(ch) in "PZCS":
            continue
        if last is not None and folded[last].isdigit() and ch.isdigit():
            for between in range(last + 1, pos):
                blank = kind(folded[between]) in "ZC"
                if not (blank and chars[-1] == " "):
                    chars.append(" " if blank else folded[between])
                    places.append(between)
        chars.append(ch)
        places.append(pos)
        last = pos
    return "".join(chars), places


def compact(text: str) -> str:
    """去掉空白和标点后再比较；两个数字之间的留下，免得 72.6、7-2 和 726 混为一谈。"""
    return squeeze(fold(text))[0]


# ---------- 数字 ----------
def cn_number(word: str) -> float:
    """中文数字转数值："两百五十"→250，"一百五"→150，"十五"→15，"一点五"→1.5。"""
    whole, _, fraction = word.partition("点")
    if len(whole) > 1 and not any(ch in _CN_UNITS for ch in whole):
        value = float("".join(str(_CN_DIGITS[ch]) for ch in whole))  # "二零二六" 这类逐位读法
    else:
        total = current = 0
        last_unit = 1
        for ch in whole:
            if ch in _CN_DIGITS:
                current = _CN_DIGITS[ch]
            else:
                last_unit = _CN_UNITS[ch]
                total += (current or 1) * last_unit
                current = 0
        if current and last_unit >= 100 and whole[-2] in _CN_UNITS:
            current *= last_unit // 10  # "一百五" 的"五"是五十
        value = float(total + current)
    if fraction:  # 按小数的写法读，“七十九点一”和 79.1 是同一个数
        value = float(f"{value:.0f}." + "".join(str(_CN_DIGITS[ch]) for ch in fraction))
    return value


def number_value(token: str) -> float:
    return float(token) if token[0] in "0123456789" else cn_number(token)


def _readings(text: str, token: str, end: int) -> set[float]:
    """一个数字词的读法。它以"千"结尾、后面紧跟卡、克、焦时，"千"也可能属于单位。"""
    readings = [token]
    if token.endswith("千") and text[end : end + 1] in _KILO_UNITS:
        readings.append(token[:-1])
    return {number_value(reading) for reading in readings if reading.strip("百千")}


# ---------- 同义归一（R10） ----------
def normalize_unit(unit: str) -> str:
    key = clean(unit).strip()
    return _UNIT_SYNONYMS.get(key.casefold(), key)


def normalize_state(state: str) -> str:
    return _STATE_SYNONYMS.get(state.strip(), state.strip())


def normalize_net(net: str) -> str:
    return _NET_SYNONYMS.get(net.strip(), net.strip())


def normalize_items(payload: Any) -> Any:
    """结构校验之前把每一项的单位、生熟、带皮去皮归一；形状不对的原样留给结构校验去报。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return payload
    result = copy.deepcopy(payload)
    for item in result["items"]:
        if not isinstance(item, dict):
            continue
        amount = item.get("amount")
        if isinstance(amount, dict) and isinstance(amount.get("unit"), str):
            amount["unit"] = normalize_unit(amount["unit"])
        if isinstance(item.get("state"), str):
            item["state"] = normalize_state(item["state"])
        if isinstance(item.get("net"), str):
            item["net"] = normalize_net(item["net"])
    return result
