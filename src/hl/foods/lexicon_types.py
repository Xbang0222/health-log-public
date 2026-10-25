"""词典身份、词片、食物提及和文字位置的值类型。"""

from __future__ import annotations

from dataclasses import dataclass

from hl.language import phrases as language_phrases
from hl.language import quantities as language_quantities
from hl.language import quantity_tokens as language_quantity_tokens
from hl.language import units as language_units
from hl.language.food_boundaries import name_boundaries

# —— 词典（增补第 2.1 节）：每个词的身份 ——

FOOD = "食物名"  # 概念别名、净重叫法、菜谱别名、独立品种词：原话里出现就要有对应项

MODIFIER = "修饰词"  # 品种的其余叫法：只在认品种时用，几个概念可以共用；取词时按中性词占位

NOT_SAME = "不是同一种东西"  # 包含某个别名、却是另一种食物的词

COOKING = "做法词"

NEUTRAL = "中性词"  # 只占位置：依据词、约数词、餐名和时间词……

SAVED_FILE = "foods/custom.yaml"  # 用户库（增补第 8.5 节）

MAX_READINGS = 8  # 并列的取法最多看几种（第 2.2 节）

NUMBER_CHARS = "零〇一二两三四五六七八九十百千万半几俩仨"  # 数字也是尾巴的边界（第 2.3 节）

# 引擎和别的规则共用的中性词表（R13 的约数词、第 6 节认餐次和哪天的词），不在 lookalikes.yaml 里重写
SHARED_NEUTRAL = {
    "约数词": language_units.HEDGES,
    "推断餐次用的餐名、时间词": language_phrases.MEAL_WORDS,
    "说是哪天的词": tuple(language_phrases.DAYS),
}


@dataclass(frozen=True)
class Entry:
    """词典里一个词的一种身份和出处：label 说给人听（“牛肉的别名”“约数词”），where 是出自哪个
    文件哪个条目；concept、variant 是它属于哪个概念、哪个品种，tier 是做法词的档（第 10 节）。"""

    kind: str
    label: str
    where: str = ""
    concept: str = ""
    variant: str = ""
    tier: str = ""


@dataclass(frozen=True)
class Word:
    """取词时一个词的身份：FOOD、NOT_SAME、COOKING、NEUTRAL 之一（修饰词按中性词占位）。
    食物名带概念和品种（概念别名的品种为空）；做法词的 label 是档，中性词的 label 是类。"""

    kind: str
    concept: str | None = None
    variant: str | None = None
    label: str = ""


@dataclass(frozen=True, eq=False)
class Lexicon:
    """取词用的词典：词 → 身份；尾巴规则用的停用字、各概念的切法字；认数量用的量词。"""

    words: dict[str, Word]
    stop: str
    cuts: dict[str, tuple[str, ...]]
    units: tuple[str, ...]
    longest: int


# —— 取词（增补第 2.2 节） ——


@dataclass(frozen=True)
class Token:
    """原话里取到的一个词：起止位置、原词、身份（见 Word）。"""

    start: int
    end: int
    word: str
    kind: str
    concept: str | None = None
    variant: str | None = None
    label: str = ""


# —— 尾巴、一道菜的名字、只连着一边的做法词（增补第 2.3、2.4、10 节） ——


@dataclass(frozen=True)
class Mention:
    """原话里的一样食物（增补第 2.5 节）。

    concept 不为空：概念或菜谱，name 是原词，variant 是这个词带出的品种（概念别名为空）。
    concept 为空：另一种食物，name 是原话里的这一段：不是同一种东西的词、尾巴扩出来的名字、
    一道菜的名字、“另一种食物”那一档的做法词＋食物。
    cooking 是只连着它的做法词（炒鸡蛋的“炒”，第 10 节），words 是它里面的词。
    """

    start: int
    end: int
    name: str
    concept: str | None = None
    variant: str | None = None
    cooking: tuple[Token, ...] = ()
    words: tuple[Token, ...] = ()


class Grid:
    """一段话里每个字是什么：被哪个词占了、是不是数量（第 2.3 节的边界）。"""

    def __init__(self, lex: Lexicon, text: str, found: list[Token]) -> None:
        self.lex = lex
        self.text = text
        self.owner: list[Token | None] = [None] * len(text)
        for token in found:
            self.owner[token.start : token.end] = [token] * (token.end - token.start)
        self.boundaries = name_boundaries(text)
        self.amounts = language_quantities.quantities(text, lex.units)
        # 带数的数量（“两个”“200克”）是边界；不带数的量词（“片”）可能是名字的一部分（香蕉片）
        self.counted = {at for q in self.amounts if not q.bare for at in range(q.start, q.end)}
        self.bare = {at for q in self.amounts if q.bare for at in range(q.start, q.end)}

    def free(self, at: int) -> bool:
        """这个字没被占位、也不是边界：可以是尾巴或另一种食物名字里的字。"""
        if not 0 <= at < len(self.text):
            return False
        char = self.text[at]
        return (
            self.owner[at] is None
            and "一" <= char <= "鿿"
            and char not in self.lex.stop
            and char not in NUMBER_CHARS
            and at not in self.counted
            and at not in self.boundaries
        )

    def run(self, at: int) -> int:
        """从 at 起连着的可用字到哪里为止。"""
        while self.free(at):
            at += 1
        return at

    def amount_at(self, at: int, after: bool) -> language_quantity_tokens.Quantity | None:
        """紧挨着 at 的一处数量：after 为真找从 at 开始的，否则找到 at 结束的。"""
        for quantity in self.amounts:
            if (quantity.start if after else quantity.end) == at:
                return quantity
        return None


@dataclass(frozen=True)
class Span:
    """原话里的一处食物：位置、原词、对应的概念。"""

    start: int
    end: int
    word: str
    concept: str
