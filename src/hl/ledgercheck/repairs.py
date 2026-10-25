"""账本签名损坏时的恢复、重说和撤销建议。"""

from __future__ import annotations

from typing import Any

from hl.ledgercheck.messages import DEFAULTS_FILE, HALT, NO_GIT, PLAN_FILE, TAMPERED
from hl.manifests import model as manifests_model


def restore(where: str) -> str:
    """用 git 取回最近一次提交里的那一份（R15）。只在 _restorable 看过、走得通时给。"""
    return f"用 git 恢复它（git checkout HEAD -- {where}），做完再运行 hl check"


def _restore_only(where: str, git: bool) -> str:
    """只有 git 恢复这一条路：体重、当天类型、日期、重复的 id、整份文件读不出来。走不通就停下。"""
    if git:
        return f"{TAMPERED}{restore(where)}"
    return f"{TAMPERED}{NO_GIT}：把问题原样告诉用户，{HALT}"


def _undo_entry(where: str, day: str, entry_id: Any, git: bool) -> str:
    """坏的是一条记录：git 恢复，或者问过用户撤掉它再重记。"""
    word = manifests_model.word(str(entry_id))
    option = f"--id={word}" if word.startswith("-") else f"--id {word}"
    undo = (
        "把问题告诉用户，用户同意删掉这条记录的话，"
        f"运行 hl undo {option} --date {day} --said '<用户的原话>'（引擎会先请用户确认），"
        "删掉之后请用户把那一餐再说一遍，用 hl add 重新记"
    )
    if git:
        return f"{TAMPERED}{restore(where)}；或者{undo}"
    return f"{TAMPERED}{undo}；用户不同意删，{HALT}"


def _fix_plan(git: bool) -> str:
    """计划坏了、签名有效的版数没少：hl plan set 能修（R17）。"""
    plan_set = "请用户把计划再说一遍，用 hl plan set 重新设定：它会去掉过不了校验的计划，把文件写好"
    if git:
        return f"{TAMPERED}{restore(PLAN_FILE)}；或者{plan_set}"
    return f"{TAMPERED}{plan_set}"


def _fix_plan_short(git: bool) -> str:
    """plan set 修好坏文件之后（去掉过不了校验的、按日期排好）和清单还是对不上：过不了校验的
    那几版清单里记着，去掉它们就是删了几版，照旧拒绝（R17）。只剩 git 和重建两条路。"""
    why = (
        f"{TAMPERED}去掉过不了校验的那几版、按生效日期排好之后，计划和清单里记着的还是对不上"
        "（过不了校验的那几版也是清单里记着的），hl plan set 修不了它。"
    )
    if git:
        return f"{why}{restore(PLAN_FILE)}"
    return (
        f"{why}{NO_GIT}：把问题告诉用户；用户不要那几版了，运行 {manifests_model.REBUILD}，"
        f"{manifests_model.ASK_FIRST}，重建之后再请用户把计划说一遍，用 hl plan set 重新设定；"
        f"用户不同意，{HALT}"
    )


def _fix_defaults(git: bool) -> str:
    """整个 defaults.yaml 坏了（读不出来、不是一张表）：引擎没法只改其中一条，hl default 也不写
    （写回去会把别的默认品种一起抹掉，R5）。只剩 git 恢复，或者由用户决定删掉这个文件。"""
    if git:
        return f"{TAMPERED}{restore(DEFAULTS_FILE)}"
    return (
        f"{TAMPERED}{NO_GIT}；引擎也没法只改其中一条：写回去会把别的默认品种一起抹掉。"
        "把问题告诉用户，由用户决定要不要自己删掉这个文件（删了就没有默认品种了，"
        f"之后记那些食物会再问品种）；用户删了再运行 hl check，用户不删，{HALT}"
    )
