"""外层 Git 仓库的私有文件保护与隔离诊断。"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from hl.storage.git_hooks import _worktree_of
from hl.storage.git_ignore import _private_ignore
from hl.storage.git_messages import (
    KEEP_OUT,
    OUTER_EXCLUDED,
    OUTER_IN_GIT,
    OUTER_NOT_EXCLUDED,
    OUTER_NOT_IGNORED,
    OUTER_NOTE,
    OUTER_STILL_OPEN,
)
from hl.storage.git_probes import _check_ignore, _exclude_lines, _listed, _rules
from hl.storage.git_runner import _brief, _git
from hl.storage.git_state import git_paths, is_repo
from hl.storage.io import HIDDEN


def _outer(data_dir: Path) -> tuple[Path, str] | None:
    """数据目录所在的外层 git 仓库（它的工作目录）和数据目录在里面的路径（"notes/health"）；
    不在别的仓库里、查不了（没有 git）是 None。"""
    try:
        top = _git(data_dir.parent, "rev-parse", "--show-toplevel", check=False)
    except FileNotFoundError:
        return None  # 没有 git：git_init、doctor 那一项另外说
    if top.returncode != 0 or not top.stdout.strip():
        return None
    outer = Path(top.stdout.rstrip("\n")).resolve()
    try:
        return outer, data_dir.resolve().relative_to(outer).as_posix()
    except ValueError:
        return None


def _outer_rule(where: str) -> str:
    """外层仓库里只挡这个数据目录的 .hl/ 的那条规则：从仓库根算起（开头的 /），通配符照原样转义。"""
    return "/" + re.sub(r"([\\*?\[])", r"\\\1", where) + f"/{HIDDEN}/"


def _outer_leaks(data_dir: Path, outer: Path, where: str) -> tuple[list[str], dict[str, str]]:
    """外层仓库 git add -A 会放进去的 .hl/ 下的路径（相对外层），和放出它们的 .gitignore 的 !
    规则。外层只把数据目录当作一个嵌套的仓库、不进去（数据目录是自己的仓库，外层又没跟踪它
    下面的文件）时没有。"""
    literal = "--literal-pathspecs"
    if is_repo(data_dir):
        tracked = _git(outer, literal, "ls-files", "-z", "--", where).stdout.split("\0")
        if not any(path.startswith(f"{where}/") for path in tracked):
            return [], {}
    hidden = f"{where}/{HIDDEN}"
    probes = [f"{where}/{probe}" for probe in KEEP_OUT[f"{HIDDEN}/"]]
    found = _check_ignore(outer, "--no-index", paths=probes)
    ignored = {path for _, _, pattern, path in found if not pattern.startswith("!")}
    leaks = [path for path in probes if path not in ignored]
    listed = _git(outer, literal, "ls-files", "-z", "-o", "--exclude-standard", "--", hidden)
    leaks += [path for path in listed.stdout.split("\0") if path and path not in leaks]
    if not leaks:
        return [], {}
    negated = {
        path: f"{outer / source} 第 {line} 行的 {pattern}"
        for source, line, pattern, path in _check_ignore(
            outer, "-n", "--no-index", paths=[hidden, *leaks]
        )
        if pattern.startswith("!")
        and not os.path.isabs(source)
        and Path(source).name == ".gitignore"
    }
    return leaks, negated


def _outer_said(outer: Path, rule: str, leaks: list[str], negated: dict[str, str]) -> str:
    """写进外层的 exclude 之后还挡不住：有 ! 规则说出是哪几条，查不出的照实说查不出。"""
    if negated:
        return OUTER_NOT_EXCLUDED.format(outer=outer, rules=_rules(negated))
    return OUTER_STILL_OPEN.format(outer=outer, rule=rule, files=_listed(leaks))


def _outer_tracked(outer: Path, where: str) -> str:
    """外层仓库里已经进了 git 的 .hl/ 下的文件；没有是空串。"""
    hidden = f"{where}/{HIDDEN}"
    listed = _git(outer, "--literal-pathspecs", "ls-files", "-z", "--", hidden).stdout.split("\0")
    tracked = [path for path in listed if path]
    if not tracked:
        return ""
    command = shlex.join(
        ["git", "-C", str(outer), "rm", "-r", "--cached", "-f", "-q", "--", hidden]
    )
    return OUTER_IN_GIT.format(outer=outer, files=_listed(tracked), command=command)


def keep_out_outer(data_dir: Path) -> tuple[list[str], bool]:
    """hl init 用：数据目录在外层仓库里、外层会把 .hl/ 提交进去时，照规则 11 把只挡这个数据目录
    的 .hl/ 的规则写进外层的 .git/info/exclude（外层的 .gitignore 不改），再查一遍：挡住了说一句，
    还挡不住的说清楚（规则 20）。返回（提醒，写没写）。"""
    found = _outer(data_dir)
    if found is None:
        return [], False
    outer, where = found
    rule = _outer_rule(where)
    warnings: list[str] = []
    wrote = False
    try:
        leaks, negated = _outer_leaks(data_dir, outer, where)
        if leaks and _worktree_of(outer) is not None:
            wrote = _private_ignore(data_dir)
            leaks, negated = _outer_leaks(data_dir, outer, where)
            if leaks:
                warnings.append(_outer_said(outer, rule, leaks, negated))
            elif wrote:
                warnings.append(
                    f"已在 {data_dir / HIDDEN / '.gitignore'} 追加私有文件保护规则，"
                    "外层仓库共用的 exclude 没有改动"
                )
            tracked = _outer_tracked(outer, where)
            return warnings + ([tracked] if tracked else []), wrote
        if leaks:
            (exclude,) = git_paths(outer, "info/exclude")
            if rule not in _exclude_lines(exclude):
                exclude.parent.mkdir(parents=True, exist_ok=True)
                old = exclude.read_bytes() if exclude.exists() else b""
                lead = "\n" if old and not old.endswith(b"\n") else ""
                with open(exclude, "ab") as handle:
                    handle.write(f"{lead}{OUTER_NOTE}{rule}\n".encode())
                wrote = True
                leaks, negated = _outer_leaks(data_dir, outer, where)
                if not leaks:
                    warnings.append(OUTER_EXCLUDED.format(outer=outer, rule=rule))
            if leaks:
                warnings.append(_outer_said(outer, rule, leaks, negated))
        tracked = _outer_tracked(outer, where)
        if tracked:
            warnings.append(tracked)
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.append(f"没能查数据目录所在的 git 仓库 {outer} 有没有忽略 .hl/：{_brief(exc)}")
    return warnings, wrote


def outer_problem(data_dir: Path) -> str:
    """hl doctor 用：外层仓库会不会、是不是已经把 .hl/ 提交进去；没问题返回空串。说法和 hl init
    的一样：还没写进外层 exclude 的叫运行 hl init，写了还挡不住的说清楚。"""
    found = _outer(data_dir)
    if found is None:
        return ""
    outer, where = found
    rule = _outer_rule(where)
    try:
        leaks, negated = _outer_leaks(data_dir, outer, where)
        problems = []
        if leaks:
            (exclude,) = git_paths(outer, "info/exclude")
            if _worktree_of(outer) is not None:
                problems.append(
                    f"外层工作树 {outer} 尚未保护数据目录的私有文件；运行 hl init，"
                    f"在 {data_dir / HIDDEN / '.gitignore'} 追加保护规则，共用 exclude 不会改动"
                )
            elif rule in _exclude_lines(exclude):
                problems.append(_outer_said(outer, rule, leaks, negated))
            else:
                problems.append(OUTER_NOT_IGNORED.format(outer=outer, rule=rule))
        tracked = _outer_tracked(outer, where)
        if tracked:
            problems.append(tracked)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"查不了数据目录所在的 git 仓库 {outer} 有没有忽略 .hl/：{_brief(exc)}"
    return "；".join(problems)
