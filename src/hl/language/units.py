"""通用份量单位、中文数字字典及规范值。"""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml

MEALS = ("早餐", "午餐", "晚餐", "加餐")  # 两份 schema 里的 meal 枚举与它一致（有测试钉住）


HEDGES = ("大概", "大约", "差不多", "左右", "估计", "目测")


_AFTER_HEDGES = ("左右",)  # 说在数后面的估计用词（“150克左右”）


def _units_table() -> dict[str, Any]:
    """data/units.yaml：通用重量体积单位、通用量词表（增补第 4、6 节）。"""
    text = resources.files("hl").joinpath("data", "units.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


_UNITS = _units_table()


GRAMS = {unit: spec["g"] for unit, spec in _UNITS["weight"].items()}  # 一个通用重量单位合多少克


MILLILITRES = {unit: spec["ml"] for unit, spec in _UNITS["volume"].items()}  # 合多少毫升

# 通用单位的写法，第一个是引擎记下的叫法：“千克、kg”都记成公斤，“克、公克”都记成 g
UNIT_FORMS = {
    unit: tuple(spec["forms"])
    for kind in ("weight", "volume")
    for unit, spec in _UNITS[kind].items()
}


COUNTERS = tuple(_UNITS["counters"])  # 通用量词表


NOT_PORTIONS = tuple(_UNITS["not_portions"])  # 是量词，说的却不是份量（“两个人”“一次”）


_NEED_NUMBER = tuple(_UNITS["need_number"])  # 前面没有数字时多半不是量词（“只吃了”“把鸡蛋吃了”）

# 份量的量词：概念表和菜谱里用到的量词都得在这里（有测试钉住）
PORTION_WORDS = (*COUNTERS, "斤", "两")


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}  # fmt: skip


_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


_ARABIC = r"\d+(?:\.\d+)?"


_CHINESE = r"[零〇一二两三四五六七八九十百千]+(?:点[零〇一二三四五六七八九]+)?"


_NUMBER = rf"(?:{_ARABIC}|{_CHINESE})"


_FILLERS = "多来余整大小满"  # "一大碗""200多克"里夹在数字和单位之间的字


_NOT_ONE = "几数第每"  # "几个""每个"不是"1 个"


_KILO_UNITS = ("卡", "克", "焦")


_UNIT_SYNONYMS = {form: unit for unit, forms in UNIT_FORMS.items() for form in forms}


_STATE_SYNONYMS = {"熟重": "熟", "熟的": "熟", "煮熟": "熟", "生重": "生", "生的": "生"}


_NET_SYNONYMS = {
    "带壳": "带皮", "带骨": "带皮",
    "去壳": "去皮", "剥皮": "去皮", "剥壳": "去皮", "去骨": "去皮", "净肉": "去皮",
}  # fmt: skip


CLAUSE_END = "，。；！？,;!?\n"  # 半句到这些为止（R13 找估计用词、R2 带前后文都用它）
