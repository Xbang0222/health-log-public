"""薄荷库原始数据的整理和质检（第 2 步增补第 13.1、13.3 节）。

只在 hl foods build、hl foods fetch 时跑：读原始数据目录里的 all.csv（GB18030）和
food_detail_backup.json，整理成薄荷库副本（.hl/boohee.json）的内容。营养数值取自 all.csv，
量词和配方取自 food_detail_backup.json（两份按条目编号对上）。副本的读取在 foods/table.py。"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from hl.foods.boohee_nutrition import COLUMNS as COLUMNS
from hl.foods.boohee_nutrition import NUTRIENTS as NUTRIENTS
from hl.foods.boohee_nutrition import UNKNOWN_MARKS as UNKNOWN_MARKS
from hl.foods.boohee_nutrition import consistent as consistent
from hl.foods.boohee_nutrition import parse_value as parse_value
from hl.foods.boohee_units import AMOUNT as AMOUNT
from hl.foods.boohee_units import GENERIC as GENERIC
from hl.foods.boohee_units import HEAD as HEAD
from hl.foods.boohee_units import SAME as SAME
from hl.foods.boohee_units import STANDARD as STANDARD
from hl.foods.boohee_units import UNITS as UNITS
from hl.foods.boohee_units import UNITS_CONFLICT as UNITS_CONFLICT
from hl.foods.boohee_units import UNITS_GENERIC as UNITS_GENERIC
from hl.foods.boohee_units import UNITS_SIZED as UNITS_SIZED
from hl.foods.boohee_units import UNITS_UNPARSED as UNITS_UNPARSED
from hl.foods.boohee_units import _number as _number
from hl.foods.boohee_units import _same as _same
from hl.foods.boohee_units import parse_units as parse_units
from hl.foods.cn6 import Built

CSV_FILE = "all.csv"

DETAIL_FILE = "food_detail_backup.json"

FILES = (CSV_FILE, DETAIL_FILE)

ENCODING = "gb18030"

NEEDED = ("id", "来源", "名称", "分类", *COLUMNS)

ID = re.compile(r"[0-9A-Za-z_-]+")  # 和每日记录的 schema 里 bh: 后面的写法一致

# 增补第 13.1 节：配方文字里提到这些的记 salted（只看有没有提到）
SALTY = ("盐", "酱油", "生抽", "老抽", "蚝油", "豆瓣酱")

# 增补第 13.1 节：分类是这两种的，克和毫升按 1:1 通用（干的冲调粉除外）
LIQUID_GROUPS = ("饮料", "奶类及制品")

# 增补第 9 节 dry：冲调前的粉和固体饮料。分类不可靠，明确的冲调粉名跨分类识别；
# 其余“粉”只在饮料、奶类里算，避免把凉拌米粉、粉蒸肉等成品当干粉。
DRY_WORDS = ("速溶", "三合一", "固体", "干重")

DRY_GROUPS = ("固体饮料类", "奶粉类")

DRY_DRINK_KCAL = 150

# 固定数据的豆浆粉归在“大豆”，蛋白粉归在“其它”。末尾允许口味括号和产品规格，
# 不允许接“饼干”“蛋糕”等成品名；这些词里的“粉”只是原料，不是食用形态。
POWDER_NAME = re.compile(
    r"(?:蛋白(?:质)?粉|豆浆粉|豆奶粉|奶粉|芝麻糊粉|核桃粉|藕粉|营养粉|代餐粉|预拌粉|复合粉)"
    r"(?:\s|\([^()]*\)|（[^（）]*）|低糖|高钙|多维型|智护[0-9]*)*$"
)

# 质检的各项条数（增补第 13.3 节），结果的 quality 里列出
RAW = "raw"  # all.csv 里的条数

INCONSISTENT = "inconsistent"  # 热量和蛋白质、脂肪、碳水对不上，不收

KCAL_UNKNOWN = "kcal_unknown"  # 没有热量，不收

SAME_NAME = "same_name"  # 和别的条目重名的条数（都留着，兜底不命中）

SAME_NAME_GROUPS = "same_name_groups"  # 重名的组数

TRIMMED = "trimmed"  # 名称首尾有空白、去掉了的

NO_DETAIL = "no_detail"  # food_detail_backup.json 里没有这一条：没有量词，salted 为否

PER_ML = "per_ml"  # 营养按每 100 毫升算的

LIQUID = "liquid"  # 克和毫升按 1:1 通用的

SALTED = "salted"

DRY = "dry"


def _text(value: Any) -> str:
    """配方的一栏（列表或一段文字）→ 一段文字。"""
    if isinstance(value, list):
        return " ".join(map(str, value))
    return str(value)


def salted(detail: dict[str, Any]) -> bool:
    """配方文字（主料、辅料、调料）里提到盐、酱油、生抽、老抽、蚝油、豆瓣酱的（增补第 13.1 节）。"""
    material = detail.get("material_info") or {}
    parts = material.values() if isinstance(material, dict) else [material]
    text = " ".join(_text(part) for part in parts)
    return any(word in text for word in SALTY)


def dry(name: str, group: str, kcal: float) -> bool:
    """冲调前的粉、固体饮料（增补第 9 节）：按干重算，多半不是用户喝下去的样子。"""
    if POWDER_NAME.search(name):
        return True
    if any(word in name for word in DRY_WORDS) or group in DRY_GROUPS:
        return True
    if "饮料" in group:
        return kcal > DRY_DRINK_KCAL or "粉" in name
    return group == "奶类及制品" and "粉" in name


def _rows(raw_dir: Path, problems: list[str]) -> list[dict[str, str]]:
    path = raw_dir / CSV_FILE
    try:
        text = path.read_bytes().decode(ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        problems.append(f"{CSV_FILE} 读不出来（应是 GB18030 编码的 CSV）：{exc}")
        return []
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = [column for column in NEEDED if column not in (reader.fieldnames or [])]
    if missing:
        problems.append(f"{CSV_FILE} 缺少这几列：{'、'.join(missing)}")
        return []
    return list(reader)


def _details(raw_dir: Path, problems: list[str]) -> dict[str, dict[str, Any]]:
    """food_detail_backup.json：条目编号（href 的最后一段）→ 详情。"""
    path = raw_dir / DETAIL_FILE
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        problems.append(f"{DETAIL_FILE} 读不出来：{exc}")
        return {}
    if not isinstance(records, list):
        problems.append(f"{DETAIL_FILE} 不是一个记录数组")
        return {}
    details = {}
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("href"), str):
            details[record["href"].rstrip("/").rsplit("/", 1)[-1]] = record
    return details


def _labels(detail: dict[str, Any]) -> list[str]:
    widgets = detail.get("widget_unit_info") or []
    return [label for item in widgets if isinstance(item, dict) for label in item]


def _detail_name(detail: dict[str, Any], name: str) -> str:
    """量词栏里拼进去的名字：照详情里的名称，没有就用 all.csv 的。"""
    info = detail.get("basic_info")
    given = info.get("food_name") if isinstance(info, dict) else None
    return given.strip() if isinstance(given, str) and given.strip() else name


def _convert(row: dict[str, str], detail: dict[str, Any] | None, counts: Counter[str]) -> Any:
    """all.csv 的一行（加上详情）→ 副本的一条；不收的返回 None。值不是数时抛 ValueError。"""
    name = row["名称"].strip()
    if not name:
        raise ValueError("名称是空的")
    counts[TRIMMED] += name != row["名称"]
    group = row["分类"].strip()
    food: dict[str, Any] = {"name": name, "group": group, "origin": row["来源"].strip()}
    for column, key in COLUMNS.items():
        food[key] = parse_value(row[column])
    if food["kcal"] is None:
        counts[KCAL_UNKNOWN] += 1
        return None
    if not consistent(food, "饮料" in group or "酒" in name):
        counts[INCONSISTENT] += 1
        return None
    if detail is None:
        counts[NO_DETAIL] += 1
        units, per_ml, has_salt = {}, False, False
    else:
        units, per_ml = parse_units(_labels(detail), _detail_name(detail, name), counts)
        has_salt = salted(detail)
    is_dry = dry(name, group, food["kcal"])
    food["per"] = "ml" if per_ml else "g"
    food["liquid"] = (per_ml or group in LIQUID_GROUPS) and not is_dry
    food["units"] = units
    food["salted"] = has_salt
    food["dry"] = is_dry
    for key, flag in (
        (PER_ML, per_ml),
        (LIQUID, food["liquid"]),
        (SALTED, has_salt),
        (DRY, is_dry),
    ):
        counts[key] += flag
    return food


QUALITY = (
    INCONSISTENT,
    KCAL_UNKNOWN,
    TRIMMED,
    NO_DETAIL,
    PER_ML,
    LIQUID,
    SALTED,
    DRY,
    UNITS,
    UNITS_SIZED,
    UNITS_GENERIC,
    UNITS_UNPARSED,
    UNITS_CONFLICT,
)


def read(raw_dir: Path, source: str, commit: str) -> Built:
    """读原始数据目录里的 all.csv 和 food_detail_backup.json，整理成副本内容，同时做质检。"""
    problems: list[str] = []
    rows = _rows(raw_dir, problems)
    details = _details(raw_dir, problems)
    counts: Counter[str] = Counter()
    foods: dict[str, Any] = {}
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):  # 第 1 行是表头
        code = (row.get("id") or "").strip()
        if not ID.fullmatch(code):
            problems.append(f"{CSV_FILE} 第 {line} 行的 id 写法不对：{code!r}")
            continue
        if code in seen:
            problems.append(f"{CSV_FILE} 里的 id {code} 重复出现")
            continue
        seen.add(code)
        try:
            food = _convert(row, details.get(code), counts)
        except (ValueError, TypeError, AttributeError) as exc:
            problems.append(f"{CSV_FILE} 第 {line} 行读不出来：{exc}")
            continue
        if food is not None:
            foods[code] = food
    names = Counter(food["name"] for food in foods.values())
    quality = {RAW: len(rows), **{key: counts[key] for key in QUALITY}}
    quality[SAME_NAME] = sum(n for n in names.values() if n > 1)
    quality[SAME_NAME_GROUPS] = sum(1 for n in names.values() if n > 1)
    doc = {
        "meta": {"source": source, "commit": commit, "count": len(foods)},
        "foods": dict(sorted(foods.items())),
    }
    return Built(doc, problems, quality)


def looks_like(raw_dir: Path) -> bool:
    """这个目录放的是不是薄荷库的原始数据（有 all.csv）。"""
    return (raw_dir / CSV_FILE).is_file()


def describe(quality: dict[str, int], count: int) -> str:
    """质检结果说给用户的话（增补第 13.3 节：列出各有多少条）。"""
    parsed = quality.get(UNITS, 0)
    unparsed = quality.get(UNITS_UNPARSED, 0)
    labels = parsed + unparsed + sum(quality.get(key, 0) for key in (UNITS_SIZED, UNITS_GENERIC))
    share = f"（约 {unparsed / labels:.1%}）" if labels else ""
    said = [
        f"原始 {quality.get(RAW, 0)} 条，收下 {count} 条",
        f"热量和蛋白质、脂肪、碳水对不上的不收 {quality.get(INCONSISTENT, 0)} 条",
    ]
    if quality.get(KCAL_UNKNOWN):
        said.append(f"没有热量的不收 {quality[KCAL_UNKNOWN]} 条")
    said.append(
        f"重名的 {quality.get(SAME_NAME_GROUPS, 0)} 组 {quality.get(SAME_NAME, 0)} 条都留着"
        "（说这个名字时不按它们记）"
    )
    said.append(
        f"量词收下 {parsed} 个，带大小的不收 {quality.get(UNITS_SIZED, 0)} 个，"
        f"解析不了的丢掉 {unparsed} 个{share}，几处克数对不上的丢掉 "
        f"{quality.get(UNITS_CONFLICT, 0)} 个"
    )
    said.append(
        f"按每 100 毫升算的 {quality.get(PER_ML, 0)} 条，配方里有盐或酱油的 "
        f"{quality.get(SALTED, 0)} 条，冲调前的粉和固体饮料 {quality.get(DRY, 0)} 条"
    )
    return "；".join(said) + "。"
