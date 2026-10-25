"""用户库 foods/custom.yaml（增补第 8.5、8.6、13.1 节）：读、验签、写、按出处删，存的名字的规矩。

每条以名字为键、带签名（种类 food，所属是名字），三种：
- 包装标签：per 和 nutrition，src 是“包装标签”，算准确；
- 存下来的估算：per 和 parts（配方型，按量词或每 100 克）或 nutrition（营养值型），带 est、basis、
  url、date、from（出自哪条记录）、serving_g；
- 量词补充：units（某样认得出的食物“这个量词 = 多少克”），可以单独一条，也可以跟在上面两种里。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from hl import schema
from hl.foods.concept_types import Index
from hl.foods.custom_entry import DISH_UNITS as DISH_UNITS
from hl.foods.custom_entry import LABEL as LABEL
from hl.foods.custom_entry import Entry as Entry
from hl.language import normalize as language_normalize
from hl.language import phrases as language_phrases
from hl.language import quantities as language_quantities
from hl.language import units as language_units
from hl.result import problem
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys

FILE = "foods/custom.yaml"

KIND = "food"  # 签名的种类；所属是条目的名字

SCHEMA = "custom"

# 名字两头不能是这几个字（“吃了螺蛳粉”“螺蛳粉的”）。不用 lookalikes.yaml 的整张停用字表：
# 那张表是取词时切名字用的，有“全、有、不”，拿来查整个名字会把“全家桶”“有机豆浆”也拒掉
EDGE = "的了吃喝"

ANY_UNIT = language_quantities.with_generic_units(["g", "ml", *language_units.COUNTERS])

FIX_BROKEN = (
    "用户库 foods/custom.yaml 只能由 hl 写入。告诉用户这一条被直接改过、不能用；"
    "数据目录是 git 仓库的，可以用 git 恢复这个文件；不然请用户重新说一下它的营养或做法，"
    "用 hl food add 重新登记（会覆盖这一条）"
)

FIX_RESTORE = (
    "用户库只能由 hl 写入。数据目录是 git 仓库的，用 git checkout HEAD -- foods/custom.yaml 取回"
    "上次写对的样子；不然把这一条告诉用户，请用户重新说一下它的营养或做法，用 hl food add 重新登记"
)

FIX_TAKEN = "名字前面加上品牌或口味（例如“全家{name}”“香辣{name}”），和常用食物表里的叫法区分开"


@dataclass(frozen=True)
class Library:
    """用户库。broken 不为空是整个文件读不出来、不是一张表：按名字查到的都不能用。"""

    entries: Mapping[str, Entry] = field(default_factory=dict)
    broken: str | None = None

    def get(self, name: str) -> Entry | None:
        if self.broken is not None:
            return Entry(name, {}, self.broken)
        return self.entries.get(name)

    def foods(self) -> list[Entry]:
        """能用的食物条目（near 列它们）。"""
        if self.broken is not None:
            return []
        return [entry for entry in self.entries.values() if entry.food and not entry.problem]


def path(data_dir: Path) -> Path:
    return data_dir / FILE


def _read(data_dir: Path) -> tuple[dict[str, Any], str | None]:
    """（内容，整个文件的问题）。文件不存在是空的。"""
    try:
        raw = storage_io.read_yaml(path(data_dir))
    except (yaml.YAMLError, UnicodeDecodeError):
        return {}, f"{FILE} 不是合法的 YAML"
    except OSError:
        return {}, f"{FILE} {storage_io.UNREADABLE}"
    if raw is None:
        return {}, None
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        return {}, f"{FILE} 不是一张以名字为键的表"
    return raw, None


def load(data_dir: Path, key: bytes) -> Library:
    """读用户库、逐条查结构和签名。"""
    raw, broken = _read(data_dir)
    if broken is not None:
        return Library(broken=f"{broken}，用户库用不了")
    entries = {}
    for name, body in raw.items():
        wrong = schema.errors(SCHEMA, {name: body})
        problem = None
        if wrong:
            problem = f"用户库里“{name}”的结构不对（{wrong[0]['where']}：{wrong[0]['problem']}）"
        elif not storage_keys.signed(key, KIND, name, body):
            problem = f"用户库里“{name}”的签名不对：它不是 hl 写入的，或被直接改过"
        entries[name] = Entry(name, body if isinstance(body, dict) else {}, problem)
    return Library(entries)


def problems(data_dir: Path, key: bytes) -> list[dict[str, str]]:
    """hl check 用：用户库整个文件和每一条的问题（结构、签名）。"""
    library = load(data_dir, key)
    if library.broken is not None:
        return [problem(FILE, library.broken, FIX_RESTORE)]
    return [
        problem(FILE, entry.problem, FIX_RESTORE)
        for entry in library.entries.values()
        if entry.problem
    ]


def save(data_dir: Path, key: bytes, name: str, body: dict[str, Any]) -> Entry | None:
    """存一条（同名的整个覆盖），返回被覆盖的旧条目。调用方攥着 store.locked。

    整个文件坏了不写：写回去会把别的条目一起抹掉。调用方先用 load 查过。
    """
    raw, broken = _read(data_dir)
    if broken is not None:
        return None
    old = raw.get(name)
    body = {k: v for k, v in body.items() if k != "sig"}
    body["sig"] = storage_keys.sign(key, KIND, name, body)
    raw[name] = body
    storage_io.write_yaml(path(data_dir), raw)
    return Entry(name, old) if isinstance(old, dict) else None


def add_unit(
    data_dir: Path, key: bytes, name: str, unit: str, grams: float, origin: dict[str, str]
) -> None:
    """量词补充（增补第 2.5 节）：name 的 unit 合 grams 克，跟在同名条目里（没有就单独一条）。"""
    raw, broken = _read(data_dir)
    if broken is not None:
        return
    old = raw.get(name)
    if old is not None and not (
        isinstance(old, dict) and storage_keys.signed(key, KIND, name, old)
    ):
        return  # 被直接改过的不重新签上：照样用不了，hl check 照样报
    body = dict(old or {})
    units = dict(body.get("units") or {})
    units[unit] = {"g": grams, "date": origin["date"], "from": origin}
    body["units"] = units
    save(data_dir, key, name, body)


def drop_from(data_dir: Path, key: bytes, day: str, entry_id: str) -> list[str]:
    """hl undo 撤掉 day 的 entry_id 时，把那条记录当时存下的估算和量词补充一并删掉（第 8.5 节）。

    只删 from 正好是它的；后来用 hl food add 覆盖过的不带 from，不删。签名不对的不碰。
    返回删掉的名字。调用方攥着 store.locked。
    """
    raw, broken = _read(data_dir)
    if broken is not None or not raw:
        return []
    origin = {"date": day, "id": entry_id}
    dropped = []
    for name, body in list(raw.items()):
        if not isinstance(body, dict) or not storage_keys.signed(key, KIND, name, body):
            continue
        units = body.get("units") or {}
        left = {unit: spec for unit, spec in units.items() if spec.get("from") != origin}
        mine = body.get("from") == origin
        if not mine and left == units:
            continue
        kept = {} if mine else {k: v for k, v in body.items() if k not in ("units", "sig")}
        if left:
            kept["units"] = left
        if kept:
            kept["sig"] = storage_keys.sign(key, KIND, name, kept)
            raw[name] = kept
        else:
            del raw[name]
        dropped.append(name)
    if dropped:
        storage_io.write_yaml(path(data_dir), raw)
    return dropped


# ---------- 存的名字（第 8.5 节） ----------
def skip_reason(
    index: Index, name: str, said: Iterable[str], n: float | None, unit: str | None
) -> str | None:
    """估算照常记、但不存的情形：单字、餐名和时间词、泛称（lookalikes.yaml 的 generic）、
    原话的量词前带“大、小”。"""
    if len(name) < 2:
        return "名字只有一个字"
    if name in language_phrases.MEAL_WORDS:
        return "名字是餐名或时间词"
    if name in index.tables.generic:
        return "名字是泛称"
    if n is not None and unit is not None and sized(said, n, unit):
        return "份量说的是大份、小份"
    return None


def sized(said: Iterable[str], n: float, unit: str) -> bool:
    """原话里这个份量的量词前带“大、小”（一大碗、一小份）：估的是这一回的，不存（第 8.5 节）。"""
    for text in said:
        visible = language_normalize.visible(text)
        for quantity in language_quantities.said_amounts(visible, n, unit):
            if any(ch in visible[quantity.start : quantity.end] for ch in "大小"):
                return True
    return False


def bad_name(name: str) -> str | None:
    """名字里有数字、量词（带数的，“一碗”“2个”；“碗仔翅”的“碗”不算），或两头是“的、了”这类字：
    返回去掉之后的写法（去掉后不剩两个字的是空串）；名字没问题是 None。"""
    spans = [(q.start, q.end) for q in language_quantities.quantities(name, ANY_UNIT) if not q.bare]
    kept = "".join(ch for pos, ch in enumerate(name) if not any(a <= pos < b for a, b in spans))
    kept = "".join(ch for ch in kept if not ch.isdigit()).strip(EDGE + " ")
    if kept == name:
        return None
    return kept if len(kept) >= 2 else ""


def taken(index: Index, name: str) -> bool:
    """名字和概念别名、菜谱别名、独立品种词、做法词、中性词相同（第 8.5 节）：存估算和
    hl food add 都拒绝。中性词、做法词是 lookalikes.yaml 的 neutral、cooking.yaml 的 methods。"""
    groups = [*index.tables.neutral.values(), *index.tables.methods.values()]
    others = {word for words in groups for word in words}
    return name in index.words or name in index.variant_words or name in others


def with_names(index: Index, library: Library) -> Index:
    """把用户库里存的名字接进词典（增补第 2.1、8.5 节）：取词时整个名字算另一种食物，
    认出来、覆盖检查都按它（“牛肉酸辣粉”不再认成牛肉加多抄的字）。和概念表的叫法相同的
    （给概念存的量词补充）不用接。"""
    names = tuple(
        name
        for name in library.entries
        if name not in index.words and name not in index.variant_words
    )
    if not names:
        return index
    return replace(index, tables=replace(index.tables, saved=names))


def fmt_date(day: str) -> str:
    """2026-10-08 → “10 月 8 日”。"""
    _, month, date = day.split("-")
    return f"{int(month)} 月 {int(date)} 日"
