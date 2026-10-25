"""概念、品种、量词与认词配置的值类型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TypeAlias

Source: TypeAlias = "Path | Traversable | Mapping[str, str] | None"


@dataclass(frozen=True)
class Variant:
    """一个品种。names 是单说也是食物名的叫法（增补第 2.1 节），aliases 是只在认品种时用的叫法。"""

    name: str
    food: str
    names: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    cooked_product: bool = False  # 做好的成品（酱牛肉）：不问生熟

    @property
    def words(self) -> tuple[str, ...]:
        """认这个品种用的全部叫法：品种名、names、aliases。"""
        return tuple(dict.fromkeys((self.name, *self.names, *self.aliases)))


@dataclass(frozen=True)
class Unit:
    """一个量词合多少：g 是可食部克数，gross_g 是称出来的整重（乘可食部），ml 按密度换算；
    菜谱的量词只写 recipe（合几份配方）。variant 是这个量词指明的品种，rough 是食堂口径的大概数。"""

    g: float | None = None
    gross_g: float | None = None
    ml: float | None = None
    recipe: float | None = None
    variant: str | None = None
    rough: bool = False


@dataclass(frozen=True)
class Cook:
    """生熟或泡发：ratio（数据里写 yield）= 做熟或泡发后的重量 ÷ 原来的重量。"""

    ratio: float
    kind: str  # 煮熟、泡发
    source: str | None


@dataclass(frozen=True)
class Part:
    """菜谱里的一种成分：成分表编码和一个单位对应的可食部生重。"""

    food: str
    g: float
    note: str | None = None


@dataclass(frozen=True)
class Concept:
    """一个日常叫法。recipe 不为空时是一道菜，按菜谱拆成若干成分表条目。"""

    name: str
    source: str
    aliases: tuple[str, ...]
    variants: dict[str, Variant]
    default: str | None
    units: dict[str, Unit]
    density: float | None
    cook: Cook | None
    recipe: tuple[Part, ...]
    unsure: str | None = None  # 用户说不清是哪个品种时用的（增补第 5 节）
    net_aliases: tuple[str, ...] = ()  # 本身就是净重的叫法（虾仁）
    cuts: tuple[str, ...] = ()  # 跟在后面不算另一种食物的切法字（牛肉片）
    lookalikes: tuple[str, ...] = ()  # 包含别名、却是另一种食物的词
    salt_g: float | None = None  # 菜谱：一份配方折合的食盐
    serving_g: float | None = None  # 菜谱：一份成品的重量
    basis: str | None = None  # 菜谱：按什么估的、漏了什么

    @property
    def cook_yield(self) -> float | None:
        return self.cook.ratio if self.cook else None


@dataclass(frozen=True)
class Tables:
    """lookalikes.yaml 和 cooking.yaml 里认词用的表（增补第 2.1、2.3、8.5、10 节）。

    not_same 只是 lookalikes.yaml 里的那一列；概念自己写的 lookalikes 在各个 Concept 上，
    取词时并在一起（lexicon.py）。neutral 和 methods 都按类写：类名 → 这一类的词。
    """

    not_same: tuple[str, ...] = ()
    neutral: dict[str, tuple[str, ...]] = field(default_factory=dict)
    stop: str = ""
    generic: tuple[str, ...] = ()
    methods: dict[str, tuple[str, ...]] = field(default_factory=dict)  # 档 → 做法词
    # 用户库里存的名字（增补第 8.5 节）：加载时为空，hl add 用 custom.with_names 接进来
    saved: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)  # 按对象比：取词时按它缓存词典（lexicon.py）
class Index:
    concepts: dict[str, Concept]
    words: dict[str, str]  # 概念级的叫法 → 概念名
    variant_words: dict[str, tuple[str, str]]  # 只属于一个品种的叫法 → (概念名, 品种名)
    tables: Tables = field(default_factory=Tables)


class DataError(Exception):
    """概念表或菜谱的格式不对，读不进来。它们随引擎发布，坏了是引擎的问题。"""

    def __init__(self, problems: list[str], what: str = "概念表和菜谱") -> None:
        super().__init__(f"{what}的格式不对：" + "；".join(problems))
        self.problems = problems
