"""食品值类型、编码前缀、合并视图和营养行计算的唯一实现。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

NUTRIENTS = ("kcal", "protein", "fat", "carb", "fiber", "sodium")

DIGITS = {"kcal": 0, "protein": 1, "fat": 1, "carb": 1, "fiber": 1, "sodium": 0}

TOLERANCE = {"kcal": 1.0, "protein": 0.15, "fat": 0.15, "carb": 0.15, "fiber": 0.15, "sodium": 1.0}

# 明细 food 的写法（增补第 13.1 节）：前缀:编码，或者 est
CN6 = "cn6"  # 成分表：cn6:<编码>

BOOHEE = "bh"  # 薄荷库：bh:<薄荷的条目编号>

CUSTOM = "my"  # 用户库：my:<用户库条目的名字>

BUILTIN = "x"  # 随引擎发布的内置食物：x:salt

EST = "est"  # 估算通道记的整份营养：一行，没有编码，也没有克数

PREFIXES = (CN6, BOOHEE, CUSTOM, BUILTIN)

SALT = f"{BUILTIN}:salt"

# 读时重算（R15、增补第 8.4 节）只对这两种；别的只验结构和签名，以写入时的数为准
RECOMPUTED = (CN6, BUILTIN)

SOURCES = {CN6: "成分表", BOOHEE: "薄荷库", CUSTOM: "用户库", BUILTIN: "内置食物"}

# 估算标记（增补第 12 节）：明细的 est 是这两样里的几样，空的是准确；写的时候按这个顺序
AMOUNT = "amount"  # 份量是大概的，成分数据是准的

CONTENT = "content"  # 成分是估的

MARKS = (AMOUNT, CONTENT)

# 第 1 步写下的旧记录 est 是是或否：菜谱展开的算成分是估的；熟重折算的不论是否都算份量是大概的
# （第 1 步只有带约数词时才标是）；别的标了是的只会是约数词，算份量是大概的
OLD_CONTENT_SRC = "菜谱估算"

OLD_AMOUNT_SRC = "熟重折算"


@dataclass(frozen=True)
class Food:
    """成分表里的一条：每 100 克可食部的含量；None 表示未知，不是 0。"""

    name: str
    edible: float | None
    kcal: float | None
    protein: float | None
    fat: float | None
    carb: float | None
    fiber: float | None
    sodium: float | None
    trace: tuple[str, ...]
    # 每 100 克的水分（克）：两层兜底挑条目用（增补第 2.5 节）；第 2 步之前建的副本没有，是未知
    water: float | None = None


Table = dict[str, Food]


@dataclass(frozen=True)
class Boohee(Food):
    """薄荷库的一条（增补第 13.1 节）：每 100 克（per 是 ml 时每 100 毫升）的含量，可食部按 100 算。

    group 是薄荷的分类，origin 是来源（薄荷、用户上传）；
    units 是薄荷自带的量词（{"盘": {"g": 300}}，带可食部分的另有 gross_g，毫升的是 ml）；
    liquid 是克和毫升按 1:1 通用；salted 是配方里提到了盐或酱油；dry 是冲调前的粉。
    """

    group: str = ""
    origin: str = ""
    per: str = "g"
    liquid: bool = False
    units: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    salted: bool = False
    dry: bool = False


# 内置食物（增补第 11 节）：只有食盐。钠占氯化钠质量的 39.34%，每 100 克钠 39340 毫克，其余为 0
BUILTINS: Table = {"salt": Food("食盐", 100, 0, 0, 0, 0, 0, 39340, ())}


def split(food: str) -> tuple[str, str]:
    """明细的 food →（前缀，编码）：est 是 (EST, "")；不认识的写法前缀为空，编码原样带回。"""
    if food == EST:
        return EST, ""
    kind, colon, code = food.partition(":")
    if colon and code and kind in PREFIXES:
        return kind, code
    return "", food


def join(kind: str, code: str) -> str:
    """（前缀，编码）→ 明细的 food：split 反过来。"""
    return f"{kind}:{code}"


def ref(code: str) -> str:
    """条目编码 → 明细的 food。概念表、菜谱里不带前缀的编码是成分表的；带了前缀的、est 照原样。"""
    return code if split(code)[0] else join(CN6, code)


@dataclass(frozen=True)
class View:
    """按前缀取条目的合并视图：成分表、内置食物，加上用户库、薄荷库（没有的层当空的）。

    概念和菜谱不在这里：它们引用这里的条目（增补第 1 节，四层里排在用户库之后、成分表之前）。
    """

    cn6: Table
    custom: Mapping[str, Food] = field(default_factory=dict)
    boohee: Mapping[str, Food] = field(default_factory=dict)

    def layers(self) -> list[tuple[str, Mapping[str, Food]]]:
        """有条目的各层，按增补第 1 节的先后：用户库、成分表（连同内置食物）、薄荷库。"""
        return [(CUSTOM, self.custom), (CN6, self.cn6), (BUILTIN, BUILTINS), (BOOHEE, self.boohee)]

    def get(self, food: str) -> Food | None:
        """按 food（或概念表里不带前缀的成分表编码）取条目；没有、est 是 None。"""
        kind, code = split(ref(food))
        layer = dict(self.layers()).get(kind)
        return None if layer is None else layer.get(code)


# ---------- 计算 ----------
def round_half_up(value: Decimal | float, digits: int) -> float | int:
    """四舍五入，恰好一半时进位。"""
    quantum = Decimal(1).scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)


def nutrients(food: Food, grams: float) -> dict[str, float | int | None]:
    """grams 克可食部的六项营养；成分表里未知的项保持未知。"""
    result: dict[str, float | int | None] = {}
    for key in NUTRIENTS:
        per_100g = getattr(food, key)
        if per_100g is None:
            result[key] = None
        else:
            amount = Decimal(str(per_100g)) * Decimal(str(grams)) / 100
            result[key] = round_half_up(amount, DIGITS[key])
    return result


def agrees(row: Any, foods: Table) -> bool | None:
    """一条明细行的营养数值和条目算出来的对不对得上（R15 读时重算）。

    只重算 cn6:（按成分表 foods）和 x:（内置食物）行；bh:、my:、est 行以写入时的数为准，
    是 True（增补第 8.4 节）。编码不在 foods 里、写法不认识是 None。
    """
    kind, _ = split(row["food"])
    if kind not in RECOMPUTED:
        return True if kind else None
    food = View(foods).get(row["food"])
    if food is None:
        return None
    expected = nutrients(food, row["g"])
    for key in NUTRIENTS:
        want, got = expected[key], row[key]
        differs = want is not None and got is not None and abs(want - got) > TOLERANCE[key] + 1e-9
        if differs or (want is None) != (got is None):
            return False
    return True


def marks(row: Mapping[str, Any]) -> list[str]:
    """一条明细行的估算标记（增补第 12 节），按 MARKS 的顺序；空的是准确。

    第 1 步写下的旧记录 est 是是或否，照 OLD_CONTENT_SRC、OLD_AMOUNT_SRC 那里写的归类。
    """
    est = row["est"]
    if not isinstance(est, bool):
        return [mark for mark in MARKS if mark in est]
    if row.get("src") == OLD_AMOUNT_SRC:
        return [AMOUNT]
    if not est:
        return []
    return [CONTENT] if row.get("src") == OLD_CONTENT_SRC else [AMOUNT]


def make_row(
    code: str,
    food: Food,
    grams: Decimal | float,
    src: str,
    est: Iterable[str],
    amount: str | None = None,
    part_of: str | None = None,
) -> dict[str, Any]:
    """一条明细行。code 是条目编码（不带前缀的是成分表的，见 ref）；grams 是折算后的
    可食部克数，生熟、干湿口径与 food 条目一致，先取整到一位小数再算营养。

    est 是估算标记（AMOUNT、CONTENT 里的几样），写成按 MARKS 排好、不重复的列表。
    amount 是用户说的份量（照原样记下）；菜谱拆出的行记的是那道菜的份量，
    part_of 是这一行所属的菜名（只有菜名，不带份量）。
    """
    row: dict[str, Any] = {"food": ref(code), "name": food.name}
    if amount:
        row["amount"] = amount
    row["g"] = round_half_up(grams, 1)
    row.update(nutrients(food, row["g"]))
    row["src"] = src
    given = set(est)
    row["est"] = [mark for mark in MARKS if mark in given]
    if part_of:
        row["part_of"] = part_of
    return row
