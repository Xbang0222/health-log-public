"""默认品种损坏和清单不一致时的修复命令建议。"""

from __future__ import annotations

from typing import Any

from hl import schema
from hl.foods import concepts
from hl.ledgercheck.messages import DEFAULTS_FILE, TAMPERED, WHOLE
from hl.ledgercheck.repairs import _fix_defaults, restore
from hl.manifests import model as manifests_model


def clear_command(name: Any) -> str:
    """去掉某一条默认品种的命令，键照 hl check 显示它的写法写。以 - 开头的键（-Infinity）
    会被当成选项，得放在 -- 后面；带确认再调用时，--confirm --answer 也要写在 -- 前面。"""
    shown = schema.shown_key(name)
    word = manifests_model.word(shown)
    if word.startswith("-"):
        return (
            f"hl default --clear --said '<用户的原话>' -- {word}"
            "（这个键以 - 开头，前面要有 --；用户确认后再调用时，--confirm --answer "
            "'<用户回答的原话>' 也写在 -- 前面）"
        )
    return f"hl default {word} --clear --said '<用户的原话>'"


def _clear_with(name: Any) -> str:
    """“用 <命令> 去掉”。键是哪种食物时，原话里要有它（R5）：用户只答“去掉吧”会被拒，
    后面说清问用户时请他带上；不是哪种食物的键（-Infinity、true）不核对字面，不用说。"""
    clear = f"用 {clear_command(name)} 去掉"
    if not isinstance(name, str) or concepts.lookup(concepts.load(), name) is None:
        return clear
    shown = schema.shown_key(name)
    return f"{clear}（--said 的原话里要有“{shown}”：问用户时请他带上，例如“{shown}的默认品种去掉”）"


def _settable(name: Any) -> bool:
    """hl default <键> <品种> 设得回这一条：键是概念表里分品种的那种食物的正式名字。
    别名（纯牛奶）、键不是文字的、以 - 开头的，设定的不是这一条，只能去掉。"""
    if not isinstance(name, str) or name.startswith("-"):
        return False
    concept = concepts.load().concepts.get(name)
    return concept is not None and bool(concept.variants)


def _redo(name: Any) -> str:
    """问用户，重新设定或去掉这一条。"""
    shown = schema.shown_key(name)
    if not _settable(name):
        return f"把问题告诉用户，用户同意去掉这一条的话，{_clear_with(name)}"
    return (
        f"请用户再说一遍“{shown}”以后按哪个品种记，用 hl default "
        f"{manifests_model.word(shown)} <品种> "
        f"--said '<用户的原话>' 重新设定；用户不要这条默认了，{_clear_with(name)}"
    )


def _default_fix(name: Any, git: bool) -> str:
    """defaults.yaml 里某一条坏了（结构、签名）的改法；name 是 WHOLE 是整个文件坏了。"""
    if name is WHOLE:
        return _fix_defaults(git)
    restored = f"{restore(DEFAULTS_FILE)}；或者" if git else ""
    return f"{TAMPERED}{restored}{_redo(name)}。hl default 都会先请用户确认"


def _settle_fix(name: Any, kind: str, git: bool) -> str:
    """默认品种和清单对不上（R15）：文件是 hl 写的，只是不是清单记着的那样。几条路各说一次。

    文件里多出来的（extra）多半就是 git 恢复带回来的，再恢复一遍也没用，不给 git 这条路。
    """
    why = {
        "gone": (
            f"清单里记着这一条，{DEFAULTS_FILE} 里却没有了："
            "文件被直接删改过，或者上一次去掉它时中途断了。"
        ),
        "changed": "这一条是 hl 签过名的，但不是清单里记着的那一条。",
        "extra": "",
    }[kind]
    restored = ""
    if git and kind != "extra":
        restored = f"{restore(DEFAULTS_FILE)}，还是报这一条就换别的路；"
    return (
        f"{why}把问题告诉用户，再选一条路：{restored}"
        f"{_redo(name).removeprefix('把问题告诉用户，')}；"
        f"或者按现在的文件重建清单：运行 {manifests_model.REBUILD}。后面这几样引擎都会先请用户确认"
    )
