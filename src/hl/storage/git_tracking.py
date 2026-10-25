"""本次写集的 Git 跟踪、暂存和提交阻塞诊断。"""

from __future__ import annotations

import contextlib
import shlex
import subprocess
from pathlib import Path

from hl.storage.days import day_path, scan_log
from hl.storage.git_messages import (
    IGNORED_LEDGER,
    LINKED_LOG,
    STUCK_IGNORED,
    STUCK_LINK,
    UNCOMMITTED_LEDGER,
    UNTRACKED_LEDGER,
)
from hl.storage.git_probes import _check_ignore, _listed, _rules
from hl.storage.git_runner import _brief, _git
from hl.storage.git_state import _head, unfinished
from hl.storage.io import DEFAULTS_FILE, HIDDEN, PLAN_FILE


def _tracked(data_dir: Path, path: Path) -> str | None:
    """进 git 的文件相对数据目录的路径；.hl/ 下的（密钥、收件箱、清单……）和目录外的返回 None。"""
    try:
        where = path.relative_to(data_dir).as_posix()
    except ValueError:
        return None
    return None if where.split("/")[0] == HIDDEN else where


def _ledger(where: str) -> bool:
    """账本文件（hl doctor 查得到它们提交不提交得上）：hl.toml、计划、默认品种、log/ 下的。"""
    return where in ("hl.toml", PLAN_FILE, DEFAULTS_FILE) or where.startswith("log/")


def _unstage(data_dir: Path, paths: list[str]) -> None:
    """提交没成：把这次 git add 进暂存区的撤出来（回到最近一次提交的样子；还没有提交时就是
    拿出暂存区），不留给用户下一次手工提交捎带进去。撤不了也不再报：提醒里已经说了没提交上。"""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        _git(data_dir, "reset", "-q", "--", *paths, check=False)


def _beyond_link(data_dir: Path, where: str) -> str | None:
    """where 所在的文件夹里（从数据目录往下）第一个是符号链接的；没有返回 None。
    git 不提交符号链接里面的文件，问到它们还会直接报错。"""
    folder = data_dir
    for part in Path(where).parent.parts:
        folder = folder / part
        if folder.is_symlink():
            return folder.relative_to(data_dir).as_posix()
    return None


def _ignoring(data_dir: Path, paths: list[str]) -> dict[str, str]:
    """paths 里 git 照忽略规则不让 git add 的，和挡住它的那条规则（“.gitignore 第 3 行的
    *.yaml”，全局的规则带着文件的完整路径），按 paths 的顺序。已经进了 git 的不算：它们照常
    提交得上。paths 里不能有在符号链接里面的。"""
    if not paths:
        return {}
    rules = {}
    for source, line, pattern, where in _check_ignore(data_dir, paths=paths):
        if not pattern.startswith("!"):  # 带 -v 时，最后对上的是 ! 规则（不忽略）的也列出来
            rules[where] = f"{source} 第 {line} 行的 {pattern}"
    return {where: rules[where] for where in paths if where in rules}


def _uncommittable(data_dir: Path, paths: list[str]) -> tuple[set[str], list[str]]:
    """这次要提交的文件里 git 提交不上的，和每种原因一句话。"""
    linked: dict[str, list[str]] = {}
    for where in paths:
        link = _beyond_link(data_dir, where)
        if link is not None:
            linked.setdefault(link, []).append(where)
    stuck = {where for files in linked.values() for where in files}
    reasons = [STUCK_LINK.format(files="、".join(f), link=link) for link, f in linked.items()]
    ignored = _ignoring(data_dir, [where for where in paths if where not in stuck])
    if ignored:
        reasons.append(STUCK_IGNORED.format(files=_listed(list(ignored)), rules=_rules(ignored)))
    return stuck | set(ignored), reasons


def commit_blockers(data_dir: Path, today: str) -> list[str]:
    """hl doctor、hl init 用：仓库自己的设置让自动提交提交不上的——账本文件（hl.toml、计划、
    默认品种、每日文件，连同今天的，还没写也算）被 .gitignore 忽略了，log/ 下有符号链接。
    自动提交失败的提醒叫模型看 hl doctor，这里要看得出来。"""
    scan = scan_log(data_dir)
    problems = []
    if scan.links:
        links = [path.relative_to(data_dir).as_posix() for path in scan.links]
        problems.append(LINKED_LOG.format(links=_listed(links)))
    days = [path.relative_to(data_dir).as_posix() for path in scan.days]
    today_path = day_path(data_dir, today).relative_to(data_dir).as_posix()
    ledger = ["hl.toml", PLAN_FILE, DEFAULTS_FILE, *sorted({*days, today_path})]
    try:
        ignored = _ignoring(data_dir, [w for w in ledger if _beyond_link(data_dir, w) is None])
    except (OSError, subprocess.SubprocessError) as exc:
        return [*problems, f"查不了 git 忽略了哪些文件：{_brief(exc)}"]
    if ignored:
        problems.append(IGNORED_LEDGER.format(files=_listed(list(ignored)), rules=_rules(ignored)))
    return problems


def untracked_ledger(data_dir: Path) -> str:
    """hl doctor 用：没被忽略、也没进 git 的账本文件（hl.toml、计划、默认品种、每日文件），和进了
    git、却有没提交的改动的（比最近一次提交多了、改了，暂存了没提交的也算）；没有返回空串。
    在符号链接里面的不算（LINKED_LOG 另外说）。"""
    days = [path.relative_to(data_dir).as_posix() for path in scan_log(data_dir).days]
    ledger = [w for w in ("hl.toml", PLAN_FILE, DEFAULTS_FILE, *days) if (data_dir / w).is_file()]
    ledger = [where for where in ledger if _beyond_link(data_dir, where) is None]
    if not ledger:
        return ""
    try:
        done = _git(data_dir, "ls-files", "-z", "-o", "--exclude-standard", "--", *ledger)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"查不了账本文件进没进 git：{_brief(exc)}"
    left = [where for where in ledger if where in set(done.stdout.split("\0"))]
    problems = []
    if left:
        command = shlex.join(["git", "add", "--", *left])
        problems.append(UNTRACKED_LEDGER.format(files=_listed(left), command=command))
    try:
        changed = _uncommitted(data_dir, [where for where in ledger if where not in left])
    except (OSError, subprocess.SubprocessError) as exc:
        return "；".join([*problems, f"查不了账本文件的改动提交了没有：{_brief(exc)}"])
    if changed:
        command = shlex.join(["git", "add", "--", *changed])
        problems.append(UNCOMMITTED_LEDGER.format(files=_listed(changed), command=command))
    return "；".join(problems)


def _uncommitted(data_dir: Path, ledger: list[str]) -> list[str]:
    """ledger 里比最近一次提交多了改动的（工作区、暂存区都算），按 ledger 的顺序。还没有提交过
    的仓库没有可比的：不在 git 里的另外说。合并、变基做到一半时工作区本来就和 HEAD 不一样，
    先请用户做完或放弃（UNFINISHED_DOCTOR），这里不说。"""
    if not ledger or not _head(data_dir) or unfinished(data_dir) is not None:
        return []
    done = _git(data_dir, "diff", "--name-only", "-z", "HEAD", "--", *ledger)
    changed = set(done.stdout.split("\0"))
    return [where for where in ledger if where in changed]
