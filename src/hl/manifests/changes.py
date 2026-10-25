"""清单重建预览中的缺失、改动和接纳内容。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl.manifests.io import read
from hl.manifests.model import LAST_WINS, PARTS, Changes, _blank, _defaults, _was
from hl.manifests.scan import _quiet, _scan, defaults_path


def _day_changes(
    day: str, was: Mapping[str, Any], now: Mapping[str, Any], looks: Mapping[tuple[str, ...], str]
) -> Changes:
    lost, changed, added = [], [], []
    for entry_id, sig in was["entries"].items():
        if entry_id not in now["entries"]:
            lost.append(f"{day} 的记录 {entry_id}")
        elif sig and now["entries"][entry_id] != sig:
            shown = looks.get((day, str(entry_id)), "")
            changed.append(f"{day} 的记录 {entry_id} 会换成文件里的那一条（{shown}）")
    for entry_id in now["entries"]:
        if entry_id not in was["entries"]:
            added.append(f"{day} 的记录 {entry_id}（{looks.get((day, str(entry_id)), '')}）")
    for name, label in PARTS:
        shown = looks.get((day, name), "")
        if was[name] and not now[name]:
            lost.append(f"{day} 的{label}")
        elif now[name] and not was[name]:
            added.append(f"{day} 的{label}（{shown}）")
        elif isinstance(was[name], str) and now[name] != was[name]:
            changed.append(f"{day} 的{label}会换成文件里的那一个（{shown}）")
    return lost, changed, added


def _defaults_changes(old: Mapping[str, Any], new: Mapping[str, Any]) -> Changes:
    lost, changed, added = [], [], []
    for name, was in old.items():
        now = new.get(name)
        if now is None:
            lost.append(f"默认品种“{name}”" + (f"（{_was(was)}）" if _was(was) else ""))
        elif now["sig"] != was.get("sig"):
            if _was(was) and _was(was) != now["variant"]:
                changed.append(f"默认品种“{name}”会从“{_was(was)}”变成“{now['variant']}”")
            else:
                what = f"默认品种“{name}”会换成文件里的那一条（{now['variant']}）"
                changed.append(f"{what}，和清单里记着的不是同一次设的")
    for name, now in new.items():
        if name not in old:
            added.append(f"默认品种“{name}”（{now['variant']}）")
    return lost, changed, added


def _plan_changes(was: Any, now: list[str], looks: Mapping[tuple[str, ...], str]) -> Changes:
    """计划：会少几版、会认下几版；先后变了、排在最后的换了一版，也说出来（排在后面的生效）。"""
    if isinstance(was, int):  # 早先的清单只记了版数
        count = len(set(now))
        if was > count:
            return [f"计划 {was - count} 版"], [], []
        if count > was:
            return [], [], [f"计划 {count - was} 版（文件里一共 {len(now)} 版）"]
        return [], [], []
    gone = sum((Counter(was) - Counter(now)).values())
    more = sum((Counter(now) - Counter(was)).values())
    lost = [f"计划 {gone} 版"] if gone else []
    added = [f"计划 {more} 版（文件里一共 {len(now)} 版）"] if more else []
    changed = []
    if not gone and not more and now != was:
        order = "、".join(looks.get(("plan", sig), "") for sig in now)
        changed.append(f"计划各版的先后会换成文件里的顺序：{order}（{LAST_WINS}）")
    elif was and now and now[-1] != was[-1] and now[-1] in was:
        changed.append(f"排在最后的一版计划会变成 {looks.get(('plan', now[-1]), '')}")
    return lost, changed, added


def _merge(into: Changes, more: Changes) -> None:
    for mine, theirs in zip(into, more, strict=True):
        mine += theirs


def changes(
    old: Mapping[str, Any], new: Mapping[str, Any], looks: Mapping[tuple[str, ...], str]
) -> Changes:
    """按新清单重建，比原来的清单：（会少的，会改的，清单里没有、会认下的）。两个方向都说，
    用户才知道答“对”认下的是什么——被 git 带回来的、撤销过的记录和去掉过的默认品种都在里面。"""
    lost: list[str] = []
    changed: list[str] = []
    added: list[str] = []
    for day in sorted({*old["days"], *new["days"]}):
        was = old["days"].get(day) or _blank()
        now = new["days"].get(day) or _blank()
        _merge((lost, changed, added), _day_changes(day, was, now, looks))
    _merge((lost, changed, added), _plan_changes(old.get("plans", []), new["plans"], looks))
    _merge((lost, changed, added), _defaults_changes(old.get("defaults", {}), new["defaults"]))
    return lost, changed, added


def preview(data_dir: Path, key: bytes) -> tuple[dict[str, Any], Changes, bool]:
    """按现有的、签名有效的记录生成新清单，先不写；返回（新清单，和原来的清单比有什么不同，
    有没有原来的清单可比）。

    新清单里没有时间之类每次都不一样的东西：确认时拿它的摘要核对，问过之后文件又变了要重新问。
    原来的清单不见了或读不出来时，比不出会少什么、会改什么；会认下的照样列得出——
    就是新清单里的全部（撤掉过、又被 git 带回来的记录也在里面，用户才认得出）。
    """
    old, _ = read(data_dir, key)
    body, looks = _scan(data_dir, key)
    body["defaults"] = _defaults(key, _quiet(defaults_path(data_dir)))
    base = old if old is not None else {"days": {}, "plans": [], "defaults": {}}
    return body, changes(base, body, looks), old is not None
