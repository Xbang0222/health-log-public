"""hl food search <词>… [--limit N]：在四层库里找条目（增补第 9 节，R24）。只读，不写任何文件。

四层：用户库、常用食物和菜谱、成分表、薄荷库。matches 里每条的 ref 可以直接填进
estimate.parts[].food；排序和字段见 foods/search.py。
"""

from __future__ import annotations

import argparse
from typing import Any

from hl import store, textnum
from hl.config import Context
from hl.foods import concepts, custom, search, table
from hl.intents.catalog import load_table
from hl.result import Result, ok, problem, rejected

# tell_user 里怎么说每一层（“概念”是给模型的说法）
SPOKEN = {"用户库": "你存过的", "概念": "常用食物"}
LIMIT = search.SEARCH_LIMIT
FIX_WORDS = "照抄要找的食物名，几个词用空格隔开，例如 hl food search 番茄 蛋"
FIX_LIMIT = f"--limit 填 1 或更大的整数，或者不填（默认最多列 {LIMIT} 条）"
SKIPPED = "这次搜索没有列它"


def run(ctx: Context, args: argparse.Namespace) -> Result:
    words = [word for arg in args.words for word in textnum.clean(arg).split()]
    errors = []
    if not words:
        errors.append(problem("词", "要找的词是空的", FIX_WORDS))
    if args.limit < 1:
        errors.append(problem("--limit", f"最多列几条要至少是 1，现在是 {args.limit}", FIX_LIMIT))
    if errors:
        return rejected(errors)
    boohee = table.BooheeLayer(ctx.data_dir, ctx.boohee_sha)
    foods = table.View(load_table(ctx), boohee=boohee)
    index = concepts.load()
    library = custom.load(ctx.data_dir, store.secret(ctx.data_dir))
    saved = search.from_library(library, foods)
    matches, total = search.search(index, foods, words, saved, args.limit)
    result = ok(_told(words, matches, total), matches=matches, total=total)
    return result.warn([*boohee.warnings(), *_library_notes(library)], tell=False)


def _library_notes(library: custom.Library) -> list[str]:
    """用户库用不了的那几条：照常搜，提醒放进 warnings（给模型的）。"""
    if library.broken is not None:
        return [f"{library.broken}，这次搜索没有列用户库里的条目"]
    return [f"{entry.problem}，{SKIPPED}" for entry in library.entries.values() if entry.problem]


def _told(words: list[str], matches: list[dict[str, Any]], total: int) -> str:
    said = "“" + " ".join(words) + "”"
    if not matches:
        return f"库里没有找到和{said}相关的条目。"
    head = f"库里和{said}相关的有 {total} 条"
    if total > len(matches):
        head += f"，这里列出前 {len(matches)} 条"
    return f"{head}：{'；'.join(_one(match) for match in matches)}。"


def _one(match: dict[str, Any]) -> str:
    """一条怎么说：“番茄炒蛋（菜谱，一份 184 千卡）”
    “稻米（代表值）（成分表，每 100 克 346 千卡，水分不到 20%）”。"""
    about = [SPOKEN.get(match["kind"], match["kind"])]
    if "variant" in match:
        about.append(match["variant"])
    if "per" in match and "kcal" in match:
        about.append(f"{match['per']} {textnum.fmt(match['kcal'])} 千卡")
    elif "kcal_100g" in match:
        per = "毫升" if match.get("per_ml") else "克"
        about.append(f"每 100 {per} {textnum.fmt(match['kcal_100g'])} 千卡")
    elif match["kind"] == "菜谱":
        each = [(unit, spec["kcal"]) for unit, spec in match["units"].items() if "kcal" in spec]
        if each:
            about.append(f"一{each[0][0]} {textnum.fmt(each[0][1])} 千卡")
    if match.get("dry"):
        about.append("冲调前的粉或干品" if match["kind"] == "薄荷库" else "水分不到 20%")
    return f"{match.get('name', match['ref'])}（{'，'.join(about)}）"
