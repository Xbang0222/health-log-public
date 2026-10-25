"""对照 HEAD 与当前食品副本生成配置恢复建议。"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl.configuration.messages import (
    ADD_MARK,
    FIX_TOML,
    FIX_TOML_OLD,
    FIX_TOML_STOP,
    NO_MARK,
    OLD_COPY,
    OLD_SHA,
    OLD_TABLE,
    REBUILD_ASK,
    REBUILD_OLD_DIR,
    THEN_BUILD,
    THEN_STOP,
)
from hl.configuration.values import (
    AUTOCOMMIT,
    CONFIG_NAME,
    MARKED,
    SHA_LINE,
    _parsed,
    _raw_dir_in,
    _shown,
    _toml_string,
)
from hl.foods import table, table_io
from hl.storage import git_state as storage_git_state
from hl.storage import io as storage_io


def toml_fix(data_dir: Path) -> str:
    """hl.toml 坏了、不见了的改法（R15）：最近一次提交里的那一份用得上、又和现在的状态对得上，
    才说 git 恢复。

    对得上：数据目录里有清单（或者现在这份写着 [manifest]）时，它也有“清单已经建过”的记号——
    关了自动提交时引擎加的记号没提交，取回旧的那份，清单再不见就当它从没建过了；现在这份里
    读得出 autocommit 时，两份一样——不然取回就悄悄改了用户设的自动提交。现在这份读不出
    autocommit（不见了、写坏了）时比不了，说清取回的那一份里是什么，请用户之后改过的再改。

    成分表的哈希也要对得上：拿成分表副本 .hl/cn6.json 实际算出来的哈希、现在这份里读得出的
    sha256 比，读得到的都和那一份不一样，那一份就是旧的（hl foods build 那次没提交上）——取回它，
    现在的副本被当成改过，照改法用旧目录重建，正常的记录又对不上。现在这份和那一份一样、只是
    副本对不上时，是副本坏了，取回没错，之后成分表的检查自己会说。现在这份里读得出原始数据
    目录、和那一份里记的不一样时也说出来：取回就悄悄退回旧目录，副本坏了会照它重建。
    """
    head = storage_git_state.head_text(data_dir, CONFIG_NAME)
    settings = _parsed(head) if head is not None else None
    if settings is None:
        return FIX_TOML_STOP
    try:
        text: str | None = (data_dir / CONFIG_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    was = settings.get("git", {}).get("autocommit", True)
    lag, edit = [], []
    marked = (data_dir / storage_io.HIDDEN / "manifest.json").exists()
    if settings.get("manifest", {}).get("built") is not True and (
        marked or (text is not None and MARKED.search(text))
    ):
        lag.append(NO_MARK)
        edit.append(ADD_MARK)
    now = AUTOCOMMIT.search(text) if text is not None else None
    if now is not None and now[1] != _shown(was):
        lag.append(f"里面 autocommit = {_shown(was)}，现在是 {now[1]}")
        edit.append(f"把 autocommit 改回 {now[1]}")
    elif now is None:
        edit.append(f"把 autocommit 照用户要的改好（那一份里是 autocommit = {_shown(was)}）")
    build = _foods_lag(data_dir, settings["foods"], text, lag, edit)
    if lag:
        then = THEN_BUILD.format(raw=shlex.quote(build)) if build else THEN_STOP
        edits = f"，再{'，'.join(edit)}" if edit else ""
        return FIX_TOML_OLD.format(name=CONFIG_NAME, lag="；".join(lag), edit=edits, then=then)
    if now is None:  # 比不了：说清取回的是什么
        return (
            f"{FIX_TOML.removesuffix('，再调用一次')}：取回的是最近一次提交时的设定，"
            f"里面 autocommit = {_shown(was)}，把这一点告诉用户，用户之后改过的话请他自己再改；"
            "再调用一次"
        )
    return FIX_TOML


def _foods_lag(
    data_dir: Path, head: Mapping[str, Any], text: str | None, lag: list[str], edit: list[str]
) -> str:
    """最近一次提交里那份的 [foods] 和现在对不对得上（toml_fix）：成分表的哈希旧了、原始数据目录
    不一样时，说哪里旧了、取回之后用户怎么改。

    哈希旧了、现在这份里记的原始数据目录重建出来的正是现在的副本（或者现在这份里记的哈希）时，
    返回这个目录：取回之后由模型运行 hl foods build 它，把哈希写回去。别的时候是空串。"""
    copy = _copy_sha(data_dir)
    said = SHA_LINE.search(text) if text is not None else None
    known = {sha for sha in (copy, said[1] if said else None) if sha is not None}
    raw = _raw_dir_in(text) if text is not None else ""
    was = head.get("raw_dir") if isinstance(head.get("raw_dir"), str) else ""
    if known and head["sha256"] not in known:
        lag.append(OLD_TABLE.format(how=OLD_SHA if said else OLD_COPY))
        if raw and Path(raw).is_dir() and table.built_from(data_dir, Path(raw), known):
            return raw
        edit.append(REBUILD_ASK + (REBUILD_OLD_DIR.format(raw=was) if was else ""))
    elif raw and was and raw != was:
        lag.append(f"里面记的原始数据目录（[foods] raw_dir）是 {was}，现在是 {raw}")
        edit.append(f"把 [foods] 的 raw_dir 改回 {_toml_string(raw)}")
    return ""


def _copy_sha(data_dir: Path) -> str | None:
    """成分表副本实际的哈希；读不了是 None。"""
    try:
        return table_io.sha256_of(table_io.path(data_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
