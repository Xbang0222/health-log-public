"""清单快照模型、签名投影、显示文本与修复建议。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl.language import normalize as language_normalize
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys

FILE = "manifest.json"


WHERE = f"{storage_io.HIDDEN}/{FILE}"


REBUILD = "hl manifest rebuild --said '<用户的原话>'"


ASK_FIRST = "引擎会列出重建后会少什么、会改什么、会认下什么，先请用户确认"


FIX_LOST = (
    "清单由引擎维护，不能直接读写，也不能手工补，git 里也没有它。把这个问题原样告诉用户，"
    f"再运行 {REBUILD}：引擎会先请用户确认，再按现有的、签名有效的记录重建"
)


# 同时还有读不了的、整份读不进来的、名字不规范的：它们没处理好之前重建会漏掉它们，引擎也会拒绝
# （hl check 用）。那几条有的叫模型用 git 取回，有的请用户处理：清单这一条只叫先别重建
FIX_LOST_LATER = (
    "清单由引擎维护，不能直接读写，也不能手工补，git 里也没有它。这次还有读不了的、整份读不进来的"
    "文件或文件夹、名字不规范的文件（看其他几条）：重建清单只数读得出来、名字认得出是哪一天的，"
    "现在重建会漏掉它们，引擎也会拒绝。把这个问题原样告诉用户；清单这一条先停下，现在不要运行 "
    "hl manifest rebuild：先照其他几条的 fix 办（要用户处理的，等用户处理好），再运行 hl check，"
    "只剩清单这一条时，照它的 fix 重建"
)


NEXT_DATA = (
    "这是数据文件的问题，不是输入写错了：把每条 problem 原样告诉用户，再照各条的 fix 办"
    "（fix 里的 git 命令照抄执行；要看用户意思的，先问用户）。做完运行 hl check，"
    "通过了再做原来的事"
)


WHY_EXTRA = "可能是用 git 恢复了旧版本，把删过的带回来了；也可能是上一次写入在写清单之前中断了"


WHY_GONE = "清单里记着的东西不见了，或换成了别的：文件被直接删改过，或被退回了旧版本。"


WHY_PLANS = (
    "计划和清单里记着的对不上，生效的可能已经不是用户定的那一版：文件被直接删改过、"
    "被退回了旧版本，或者上一次写入在写清单之前中断了。"
)


LAST_WINS = "同一天起的几版，排在后面的那一版生效"


PARTS = (("weight", "体重"), ("day_type", "当天类型"))


REDO_PART = {"weight": "hl weight", "day_type": "hl day set"}


Changes = tuple[list[str], list[str], list[str]]  # 重建会少的、会改的、会认下的


def fix_gone(where: str, git: bool, why: str = WHY_GONE) -> str:
    """清单里记着、文件里没有了（或换成了别的）的改法：先用 git 取回，取不回再问用户要不要重建。

    git 为假：最近一次提交里的那一份也缺东西（或者根本没有），不给 git 这条路（audit._restorable）。
    """
    why += "运行 hl check 查看全部问题。"
    if git:
        return (
            f"{why}用 git 恢复这个文件（git checkout HEAD -- {where}），"
            "做完再运行 hl check；恢复之后还是这样，或者确实是用户自己删的、改的："
            f"把问题告诉用户，运行 {REBUILD}，{ASK_FIRST}"
        )
    return (
        f"{why}git 里没有能取回的完整版本。把问题告诉用户，问是不是他自己删的、改的："
        f"是，运行 {REBUILD}，{ASK_FIRST}；不是，就此停下，不要自己改文件"
    )


def word(text: str) -> str:
    """命令行上的一个参数：只有字母、数字、汉字和 .:+- 的原样写，别的加引号。"""
    plain = text and all(ch.isalnum() or ch in "._:+-" for ch in text)
    return text if plain else "'" + text.replace("'", "'\\''") + "'"


def fix_extra_entry(day: str, entry_id: str) -> str:
    """文件里有、清单里没有的一条记录：问用户要不要，不要就撤掉，要就重建清单。"""
    option = f"--id={word(entry_id)}" if entry_id.startswith("-") else f"--id {word(entry_id)}"
    return (
        "把这个问题告诉用户，问他这条记录还要不要。"
        f"用户不要了：运行 hl undo {option} --date {day} --said '<用户的原话>'；"
        f"用户要留着：运行 {REBUILD}。两样引擎都会先请用户确认"
    )


def _fix_extra_part(name: str, label: str) -> str:
    return (
        f"把这个问题告诉用户。这个{label}要先认下来才能再改：运行 {REBUILD}，{ASK_FIRST}；"
        f"用户要改，重建之后再用 {REDO_PART[name]} 重新记"
    )


def _signed_plans(key: bytes, plans: Any) -> list[dict[str, Any]]:
    """plan.yaml 里签名有效的各版计划，按文件里的先后；别的由读时校验去报。"""
    if not isinstance(plans, list):
        return []
    return [p for p in plans if isinstance(p, dict) and storage_keys.signed(key, "plan", "", p)]


def versions(key: bytes, plans: Any) -> list[str]:
    """plan.yaml 里签名有效的各版计划的签名，按文件里的先后（清单就这样记）。"""
    return [plan["sig"] for plan in _signed_plans(key, plans)]


def _plan_shown(plan: Mapping[str, Any]) -> str:
    """一版计划说给用户听：从哪天起、默认哪种日子、多少千卡。"""
    days, default = plan.get("days"), plan.get("default")
    goals = days.get(default) if isinstance(days, dict) else None
    kcal = goals.get("kcal") if isinstance(goals, dict) else None
    shown = f"{language_normalize.fmt(kcal)} 千卡" if isinstance(kcal, (int, float)) else ""
    return f"{plan.get('from')} 起的“{default}”{shown}"


def _defaults(key: bytes, defaults: Any) -> dict[str, dict[str, Any]]:
    """defaults.yaml 里签名有效的默认品种：食物名 → {品种，签名}。"""
    if not isinstance(defaults, dict):
        return {}
    return {
        name: {"variant": entry.get("variant"), "sig": entry["sig"]}
        for name, entry in defaults.items()
        if isinstance(entry, dict) and storage_keys.signed(key, "default", name, entry)
    }


def _was(listed: Mapping[str, Any]) -> str:
    """清单里记着的那个品种；早先的清单没记品种，是空串。"""
    variant = listed.get("variant")
    return variant if isinstance(variant, str) else ""


def _entries(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """文件里的记录；形状不对的不算（由读时校验去报）。"""
    entries = doc.get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _blank() -> dict[str, Any]:
    """清单里没有列出的一天：什么都没有。"""
    return {"entries": {}, **{name: False for name, _ in PARTS}}


def _signed_part(key: bytes, day: str, doc: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    part = doc.get(name)
    return part if isinstance(part, dict) and storage_keys.signed(key, name, day, part) else None


def _snapshot(key: bytes, day: str, doc: Mapping[str, Any]) -> dict[str, Any]:
    """这一天的文件里签名有效的东西：每条记录的 id 和签名，体重、当天类型的签名（没有是 False）。"""
    signed = [entry for entry in _entries(doc) if storage_keys.signed(key, "entry", day, entry)]
    snapshot: dict[str, Any] = {"entries": {entry.get("id"): entry["sig"] for entry in signed}}
    for name, _ in PARTS:
        part = _signed_part(key, day, doc, name)
        snapshot[name] = part["sig"] if part else False
    return snapshot


def _note(days: dict[str, Any], day: str, listed: dict[str, Any]) -> None:
    """把一天记进清单；这一天什么都没有时不列。"""
    if listed["entries"] or any(listed[name] for name, _ in PARTS):
        days[day] = listed
    else:
        days.pop(day, None)


def _shown(listed: Mapping[str, Any]) -> str:
    parts = [f"记录 {len(listed['entries'])} 条"] if listed["entries"] else []
    return "、".join(parts + [label for name, label in PARTS if listed[name]])


def _part_shown(name: str, part: Mapping[str, Any]) -> str:
    return f"{part.get('kg')} 公斤" if name == "weight" else f"“{part.get('name')}”"


# —— 给 git 恢复之前核对 HEAD 那份（audit._head_sound） ——
Items = list[tuple[Any, Any]]  # （键，签名）
