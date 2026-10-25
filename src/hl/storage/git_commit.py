"""写入后的自动提交服务：先调用账本审计，再提交本次合格写集。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hl.ledgercheck import operations as ledgercheck_operations
from hl.result import Note
from hl.storage.git_messages import (
    COMMITTED_ANYWAY,
    FAILED,
    STILL_LOCKED,
    THEN_CHECK,
    THEN_COMMITTED,
    THEN_DOCTOR,
    THEN_RULE,
    UNFINISHED_RACE,
    UNSOUND,
)
from hl.storage.git_runner import _brief, _git
from hl.storage.git_state import _committed, _head, is_repo, lock_left, unfinished
from hl.storage.git_tracking import _ledger, _tracked, _uncommittable, _unstage
from hl.storage.io import _written


def autocommit(data_dir: Path, enabled: bool, message: str) -> list[str]:
    """写入成功后，把这次写过的文件在本地提交一次。失败只返回提醒，不影响命令结果。

    只提交这次写过、自己又过得了校验的文件（第 9 节第 4 层）：最近一次提交就是引擎最后一次
    写对的样子，fix 里的 git checkout HEAD -- <文件> 取回的就是它。用户手改坏了别的文件
    （比如 suggest.yaml），既不跟着进提交，也拦不住这一次：提交加 --no-verify，
    不跑 .githooks/pre-commit（它跑的 hl check 看的是整个数据目录），用户自己提交时照样跑。
    这次写过的文件自己还有 hl check 会报的问题（hl default 写回 defaults.yaml 时，
    别的条目早被改坏了），先不提交：提交进去，git 里就没有好的那一份了。

    调用的地方都还攥着 locked() 那把锁。hl check（和 pre-commit 里调用的任何命令）也不能去拿
    这把锁：用户自己提交时 pre-commit 另起进程跑它，正好碰上一次写入，就要等到 GIT_TIMEOUT
    （设计说明第 9 节）。
    """
    if not enabled or not is_repo(data_dir):
        return []
    written = sorted({where for path in _written if (where := _tracked(data_dir, path))})
    if not written:
        return []

    unsound = ledgercheck_operations.unsound(data_dir, written)
    warnings: list[str] = []
    if unsound:
        warnings.append(Note(UNSOUND.format(files="、".join(unsound)), THEN_CHECK))
    paths = [where for where in written if where not in unsound]
    if not paths:
        return warnings
    added = False
    head: str | None = None  # 提交前的 HEAD：走到提交这一步才有（还没有提交过的仓库是空串）
    try:
        # 合并、变基做到一半：写命令一开始就拒绝了（cli）；这是写的时候用户才开始的。提交会搅
        # 进去（部分提交还会被拒绝），git add 了，用户放弃时这次写的还会被一起抹掉。不往暂存区
        # 里放东西，照实说这次写的还没进 git
        doing = unfinished(data_dir)
        if doing is not None:
            return [*warnings, Note(UNFINISHED_RACE.format(what=doing[0]), THEN_DOCTOR)]
        # 仓库自己的设置让 git 提交不上的（忽略规则挡住了、在符号链接里面）：先挑出来说清楚是
        # 哪个文件、为什么，其余的照常提交。不然 git add 整个失败，报错只剩一句截空了的话
        stuck, reasons = _uncommittable(data_dir, paths)
        if reasons:
            then = THEN_DOCTOR if any(_ledger(where) for where in stuck) else THEN_RULE
            warnings.append(Note(FAILED.format(brief="，".join(reasons)), then))
        paths = [where for where in paths if where not in stuck]
        if not paths:
            return warnings
        added = True
        _git(data_dir, "add", "--", *paths)
        if _git(data_dir, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
            return warnings
        identity: list[str] = []
        if _git(data_dir, "config", "user.email", check=False).returncode != 0:
            identity = ["-c", "user.name=health-log", "-c", "user.email=health-log@localhost"]
        # 不签名：签名程序在没人看着的时候签不了（等人输密码就卡到超时），每次都提交不上
        commit = ["commit", "--no-verify", "-q", "-m", message, "--only", "--", *paths]
        head = _head(data_dir)
        _git(data_dir, *identity, "-c", "commit.gpgsign=false", *commit)
    except (OSError, subprocess.SubprocessError) as exc:
        if head is not None and _committed(data_dir, head, message):
            return [*warnings, Note(COMMITTED_ANYWAY.format(brief=_brief(exc)), THEN_COMMITTED)]
        if added:
            _unstage(data_dir, paths)
        brief = _brief(exc)
        lock = lock_left(data_dir) if isinstance(exc, subprocess.TimeoutExpired) else ""
        if lock:
            brief += STILL_LOCKED.format(lock=lock)
        return [*warnings, Note(FAILED.format(brief=brief), THEN_DOCTOR)]
    return warnings
