"""体重提及的不可变值类型。"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from hl.language.normalize import simplified
from hl.language.weight_patterns import PLAUSIBLE_KG


# ---------- 体重（R16） ----------
@dataclass(frozen=True)
class WeightMention:
    """原话里可能是体重的一个数：数值、引擎换算出的公斤数、按哪个单位算的。"""

    number: float  # “156 斤半”是 156.5，“155斤2两”是 155.2
    kg: float
    unit: str = "公斤"  # 按哪个单位换算的：公斤、斤、磅
    # 单位后面带着“半”“M两”时单位前面的那个数（“156 斤半”的 156）：--kg 照抄它也认
    whole: float | None = dataclasses.field(default=None, compare=False)
    # 没带体重单位的中文数字在原话里的写法（列出几个数时用）
    spoken: str = dataclasses.field(default="", compare=False)
    # 问用户时说的“原话里的……”：原话的写法，单位不是紧跟在数后面的说清按什么单位算的
    # （“156 斤半”“70（没写单位，按公斤算）”）
    shown: str = dataclasses.field(default="", compare=False)
    # 写法本身一眼清楚：阿拉伯数字（不带“点”），后面紧跟体重单位，或者没写单位、
    # 整条消息里也没说到别的体重单位（单说的“单位是斤”、没跟在数后面的“我习惯用斤”）（R16）
    plain: bool = dataclasses.field(default=False, compare=False)
    # 这个数连同它的单位（或跟着的字母、“半”“M两”）在原话里的位置
    span: tuple[int, int] = dataclasses.field(default=(0, 0), compare=False)
    # 单位是从用户单说的那句来的（“单位是斤”）：那句在整条消息（没给就是原话）里的位置
    noted: tuple[int, int] | None = dataclasses.field(default=None, compare=False)
    # 紧跟在数后面的单位在原话里的写法（“觔”“lbs”“镑”）；单位不是紧跟着的为空
    written: str = dataclasses.field(default="", compare=False)

    @property
    def unit_said(self) -> str:
        """告诉用户原话的单位：繁体字、异体字照原话写（“觔”“鎊”），别的用引擎的单位名
        （“lbs”“镑”说成“磅”：后者是同音错字，要让用户看到是按磅算的）。"""
        if self.written and simplified(self.written) != self.written:
            return self.written
        return self.unit

    @property
    def plausible(self) -> bool:
        """换算成公斤在 PLAUSIBLE_KG 之间，才可能是体重：差值（“轻了0.4”“瘦了两斤”）不在里面。"""
        return PLAUSIBLE_KG[0] <= self.kg <= PLAUSIBLE_KG[1]
