"""做法比例及辅料配置的加载、结构校验与可信读取。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from hl import schema
from hl.foods import concept_parse as foods_concept_parse
from hl.foods import table_types as foods_table_types
from hl.result import Abort, problem, rejected
from hl.storage import io as storage_io

FILE = "cooking.yaml"  # 引擎自带的在 src/hl/data 下；数据目录里同名的一份盖掉油盐比例


SRC = "做法估算"


OIL_NAME = "烹调油（估算）"


SALT_NAME = "盐和调味料（估算）"


OIL_WORD = "油"  # 拆菜辅料表里的“油”：概念“食用油”的默认品种


PLAIN_OIL, MEAT_OIL, SALT = "素菜油", "肉蛋水产油", "盐"


RATIO_KEYS = (PLAIN_OIL, MEAT_OIL, SALT)


NONE, SALT_ONLY, OIL_AND_SALT, OTHER_FOOD = foods_concept_parse.TIERS  # 做法词的四档


ROAST = "烤"  # 对主食、薯类、水果只认出来，不加盐


FIX_CHECK = "运行 hl check 查看详情"


FIX_FILE = (
    "cooking.yaml 是用户自己的配置，不受保护：照上面说的直接改这个文件；"
    "不想自己定油盐比例，把它删掉就用引擎自带的"
)


NEXT_FILE = (
    "cooking.yaml 是用户的配置文件，管做菜按做法加的油盐估多少：把 errors 原样告诉用户，"
    "按 fix 改好或删掉这个文件，再调用一次；别的数据文件不要直接改"
)


@dataclass(frozen=True)
class Aux:
    """拆菜辅料表里的一个词指向什么（见 cooking.yaml 开头的说明）。"""

    word: str
    concept: str | None = None
    food: str | None = None
    water: bool = False
    note: str | None = None


@cache
def _data() -> dict[str, Any]:
    text = resources.files("hl").joinpath("data", FILE).read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def aux(word: str) -> Aux | None:
    """拆菜辅料表里这个词；不在表里是 None。只在估算通道的 parts 里用。"""
    raw = _data().get("aux", {}).get(word)
    if not isinstance(raw, dict):
        return None
    return Aux(word, raw.get("concept"), raw.get("food"), bool(raw.get("water")), raw.get("note"))


# ---------- 油盐比例（第 10 节） ----------
@dataclass(frozen=True)
class Ratios:
    """每 100 克可食部生重加多少克油、盐，和按成分表编码前两位分的几类（cooking.yaml 的
    seasoning 一节）。

    changed 是数据目录里的 cooking.yaml 盖掉了的键，tell_user 里说是按用户定的比例算的。
    """

    plain_oil: float
    meat_oil: float
    salt: float
    meat: tuple[str, ...] = ()
    roast_plain: tuple[str, ...] = ()
    salty: tuple[str, ...] = ()
    oils: tuple[str, ...] = ()
    salts: tuple[str, ...] = ()
    oil_words: tuple[str, ...] = ()
    salt_words: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def oil(self, code: str) -> float:
        """这一条每 100 克加多少克油：肉蛋水产按荤的，其余按素的。"""
        return self.meat_oil if _group(code) in self.meat else self.plain_oil

    def oily(self, code: str) -> bool:
        """油类（成分表油脂类）。"""
        return _group(code) in self.oils

    def salt_like(self, code: str) -> bool:
        """盐类：内置食盐，或成分表调味品类。"""
        return foods_table_types.ref(code) == foods_table_types.SALT or _group(code) in self.salts


def _group(code: str) -> str:
    """成分表条目编码的前两位（大类）；不是成分表的是空的。"""
    kind, raw = foods_table_types.split(foods_table_types.ref(code))
    return raw[:2] if kind == foods_table_types.CN6 else ""


@cache
def builtin() -> Ratios:
    """引擎自带的比例。"""
    raw = _data()["seasoning"]
    codes = {key: tuple(str(code) for code in raw[key]) for key in raw if key not in RATIO_KEYS}
    return Ratios(
        float(raw[PLAIN_OIL]["g"]),
        float(raw[MEAT_OIL]["g"]),
        float(raw[SALT]["g"]),
        meat=codes["肉蛋水产"],
        roast_plain=codes["烤不加盐"],
        salty=codes["咸的菜"],
        oils=codes["油类"],
        salts=codes["盐类"],
        oil_words=codes["油的说法"],
        salt_words=codes["盐的说法"],
    )


def read_file(data_dir: Path) -> tuple[Ratios, list[dict[str, str]]]:
    """数据目录里的 cooking.yaml 按键盖在引擎自带的比例上（第 10 节：做菜少油的人可以调低）。

    返回（比例，{where, problem, fix} 列表）；有问题时比例是引擎自带的。这个文件由用户自己写，
    没有签名；写错了是数据问题，不是引擎出错。
    """
    ratios = builtin()
    try:
        override = storage_io.read_yaml(data_dir / FILE)
    except (yaml.YAMLError, UnicodeDecodeError):
        return ratios, [
            problem(FILE, "不是合法的 YAML", f"先把它改成一个合法的 YAML 文件。{FIX_FILE}")
        ]
    except OSError:
        return ratios, [problem(FILE, storage_io.UNREADABLE, storage_io.FIX_OS)]
    if override is None:
        return ratios, []
    found = schema.errors("cooking", override)
    if found:
        return ratios, [
            problem(FILE, f"{err['where']}：{err['problem']}", f"{err['fix']}。{FIX_FILE}")
            for err in found
        ]
    given = {key: float(override[key]) for key in RATIO_KEYS if key in override}
    return (
        Ratios(
            given.get(PLAIN_OIL, ratios.plain_oil),
            given.get(MEAT_OIL, ratios.meat_oil),
            given.get(SALT, ratios.salt),
            **{
                name: getattr(ratios, name)
                for name in ("meat", "roast_plain", "salty", "oils", "salts")
                + ("oil_words", "salt_words")
            },
            changed=tuple(given),
        ),
        [],
    )


def require(data_dir: Path) -> Ratios:
    """hl add、hl food add 用：数据目录里的 cooking.yaml 有问题就拒绝，不按引擎自带的比例悄悄记。"""
    ratios, errors = read_file(data_dir)
    if errors:
        raise Abort(rejected(errors, NEXT_FILE))
    return ratios
