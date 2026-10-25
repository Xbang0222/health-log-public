"""当前签名数据与清单之间的缺失、变更和多余项比较。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from hl.manifests.model import (
    LAST_WINS,
    PARTS,
    WHY_EXTRA,
    _blank,
    _defaults,
    _entries,
    _fix_extra_part,
    _part_shown,
    _shown,
    _signed_part,
    _was,
    fix_extra_entry,
    versions,
)
from hl.storage import keys as storage_keys


def defaults_gaps(
    listed: Mapping[str, Any] | None, key: bytes, defaults: Any
) -> list[tuple[Any, str, str]]:
    """默认品种和清单对不上的每一条：（食物名，问题，哪一种）。
    哪一种：gone 清单里记着、文件里没有；changed 签名有效、但不是清单里记着的那一条；
    extra 签名有效、清单里没有记着（去掉了又被旧文件带回来）。三种的改法不同，分开给。

    签名不对的条目不在这里报，由读时校验去报。清单里还没记过默认品种的，不对照。
    """
    want = (listed or {}).get("defaults")
    if want is None:
        return []
    present = defaults if isinstance(defaults, dict) else {}
    have = _defaults(key, present)
    found: list[tuple[Any, str, str]] = []
    for name, was in want.items():
        if name not in present:
            shown = f"（记着的是“{_was(was)}”）" if _was(was) else ""
            found.append((name, f"清单里记着的默认品种“{name}”不见了{shown}", "gone"))
        elif name in have and have[name]["sig"] != was.get("sig"):
            now = have[name]["variant"]
            if _was(was) and _was(was) != now:
                what = f"默认品种“{name}”现在是“{now}”，清单里记着的是“{_was(was)}”"
            else:
                what = f"默认品种“{name}”（{now}）和清单里记着的不是同一次设的"
            found.append((name, f"{what}：defaults.yaml 被退回了旧版本，或被换过", "changed"))
    for name, now in have.items():
        if name not in want:
            what = f"默认品种“{name}”（{now['variant']}）在文件里，清单里没有记着"
            found.append((name, f"{what}：可能是去掉之后，又被退回的旧文件带回来了", "extra"))
    return found


def day_gaps(
    listed: Mapping[str, Any] | None, day: str, doc: Any, exists: bool = True
) -> list[str]:
    """清单里记着、这一天的文件里却没有（或换成了别的）的东西。exists 为假：整个文件都不在。"""
    want = (listed or {}).get("days", {}).get(day)
    if want is None:
        return []
    if not exists:
        return [f"清单里记着这一天有{_shown(want)}，文件却不见了"]
    if not isinstance(doc, dict):
        return []  # 结构不对，由读时校验去报
    found: dict[Any, set[Any]] = {}
    for entry in _entries(doc):
        found.setdefault(entry.get("id"), set()).add(entry.get("sig"))
    wanted = want["entries"]
    missing = [entry_id for entry_id in wanted if entry_id not in found]
    swapped = [i for i, sig in wanted.items() if sig and i in found and sig not in found[i]]
    gaps = [f"清单里记着的记录 {'、'.join(missing)} 不见了"] if missing else []
    if swapped:
        what = "和清单里记着的不是同一条：文件被退回了旧版本，或被换过"
        gaps.append(f"记录 {'、'.join(swapped)} {what}")
    for name, label in PARTS:
        part = doc.get(name)
        if not want[name]:
            continue
        sig = part.get("sig") if isinstance(part, dict) else want[name]  # 形状不对由读时校验去报
        if name not in doc:
            gaps.append(f"清单里记着这一天有{label}，现在不见了")
        elif isinstance(want[name], str) and sig != want[name]:
            gaps.append(f"{label}和清单里记着的不是同一次记的：文件被退回了旧版本，或被换过")
    return gaps


def day_extras(
    listed: Mapping[str, Any] | None, key: bytes, day: str, doc: Any
) -> list[tuple[str, str]]:
    """这一天的文件里有、签名有效、清单里却没有记着的东西，每个是（问题，改法）。

    多半是用 git 把文件恢复成了旧版本，把撤掉的记录带回来了；照常接受就等于悄悄撤销了用户的撤销。
    还没有清单的数据目录不对照；日期对不上、结构不对的文件由读时校验去报。
    """
    if listed is None or not isinstance(doc, dict) or doc.get("date") != day:
        return []
    want = listed.get("days", {}).get(day) or _blank()
    found = []
    for entry in _entries(doc):
        entry_id = entry.get("id")
        if entry_id in want["entries"] or not storage_keys.signed(key, "entry", day, entry):
            continue
        what = f"{day} 的记录 {entry_id}（{entry.get('meal')}：{entry.get('said')}）在文件里"
        found.append((f"{what}，清单里没有记着：{WHY_EXTRA}", fix_extra_entry(day, entry_id)))
    for name, label in PARTS:
        part = _signed_part(key, day, doc, name)
        if want[name] or part is None:
            continue
        what = f"{day} 的{label}（{_part_shown(name, part)}）在文件里，清单里没有记着"
        found.append((f"{what}：{WHY_EXTRA}", _fix_extra_part(name, label)))
    return found


def plan_gaps(listed: Mapping[str, Any] | None, key: bytes, plans: Any) -> list[str]:
    """plan.yaml 里签名有效的各版计划和清单里记着的对不上：少了、多了、先后变了。
    同一天起的几版，排在后面的生效：多一版、换个先后，生效的就可能变了。

    签名不对的不在这里报，由读时校验去报。还没有清单的数据目录不对照。
    """
    want = (listed or {}).get("plans")
    if want is None:
        return []
    found = versions(key, plans)
    if isinstance(want, int):  # 早先的清单只记了版数：只看少没少
        count = len(set(found))
        if count >= want:
            return []
        left = f"只剩 {count} 版" if count else "一版都没有了"
        return [f"清单里记着有 {want} 版计划，现在签名有效的{left}"]
    if found == want:
        return []
    gone = sum((Counter(want) - Counter(found)).values())
    more = sum((Counter(found) - Counter(want)).values())
    gaps = []
    if gone and not found:
        gaps.append(f"清单里记着有 {len(want)} 版计划，现在签名有效的一版都没有了")
    elif gone:
        gaps.append(
            f"清单里记着有 {len(want)} 版计划，其中 {gone} 版现在不在文件里了：被删了，或换成了别的"
        )
    if more:
        what = f"plan.yaml 里有 {more} 版签名有效的计划清单里没有记着（可能是原样再贴了一遍）"
        gaps.append(f"{what}：{LAST_WINS}，生效的计划可能跟着变了")
    if not gaps:
        what = "plan.yaml 里各版计划的先后和清单里记着的不一样"
        gaps.append(f"{what}：{LAST_WINS}，生效的计划可能跟着变了")
    return gaps
