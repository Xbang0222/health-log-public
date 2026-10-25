"""Git 仓库状态、未完成操作、HEAD 内容和提交结果探测。"""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path

from hl.result import Result, problem, rejected
from hl.storage import git_runner
from hl.storage.git_messages import (
    AM,
    APPLYING,
    FIX_UNFINISHED,
    NEXT_UNFINISHED,
    SEQUENCE,
    SEQUENCER,
    UNFINISHED,
    UNFINISHED_DOCTOR,
    UNFINISHED_PROBLEM,
)
from hl.storage.git_runner import _brief, _git


def git_paths(data_dir: Path, *names: str) -> list[Path]:
    """git 仓库里这些文件的位置（git rev-parse --git-path）：.git 是个文件（--separate-git-dir、
    worktree、子模块）时不在“数据目录/.git/”下。"""
    args = [part for name in names for part in ("--git-path", name)]
    lines = _git(data_dir, "rev-parse", *args).stdout.splitlines()
    return [Path(line) if os.path.isabs(line) else data_dir / line for line in lines]


def unfinished(data_dir: Path) -> tuple[str, str] | None:
    """仓库里做到一半的合并、变基、拣选、二分查找……：（是什么，怎么做完或放弃）；没有是 None。"""
    marks = [*UNFINISHED, APPLYING, SEQUENCER]
    paths = dict(zip(marks, git_paths(data_dir, *marks), strict=True))
    found = {mark: path.exists() for mark, path in paths.items()}
    if found[APPLYING]:
        return AM
    named = next((UNFINISHED[mark] for mark in UNFINISHED if found[mark]), None)
    if named is None and found[SEQUENCER]:
        return _sequence(paths[SEQUENCER])
    return named


def _sequence(todo: Path) -> tuple[str, str]:
    """sequencer 里还等着的是拣选还是撤销：看第一行的第一个词；看不出来两样都说。"""
    try:
        lines = todo.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return SEQUENCE
    words = [line.split()[0] for line in lines if line.strip() and not line.startswith("#")]
    if words[:1] in (["pick"], ["p"]):
        return UNFINISHED["CHERRY_PICK_HEAD"]
    if words[:1] == ["revert"]:
        return UNFINISHED["REVERT_HEAD"]
    return SEQUENCE


def refuse_unfinished(data_dir: Path) -> Result | None:
    """规则 19：数据目录所在的 git 仓库里有做到一半的合并、变基……时，写命令一律拒绝，什么都
    不写（返回 rejected）；没有、查不了（不在 git 仓库里、没有 git）返回 None。只读的命令不查。"""
    try:
        doing = unfinished(data_dir)
    except (OSError, subprocess.SubprocessError):
        return None
    if doing is None:
        return None
    what, how = doing
    found = problem("git", UNFINISHED_PROBLEM.format(what=what), FIX_UNFINISHED.format(how=how))
    return rejected([found], NEXT_UNFINISHED)


def _shown(data_dir: Path, path: Path) -> str:
    """提醒里说的路径：在数据目录里的说相对路径，不在的说完整路径。"""
    try:
        return path.relative_to(data_dir).as_posix()
    except ValueError:
        return str(path)


def lock_left(data_dir: Path) -> str:
    """index.lock 还在的话，它的路径（说给用户听的）；不在、查不了是空串。"""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        (lock,) = git_paths(data_dir, "index.lock")
        if lock.exists():
            return _shown(data_dir, lock)
    return ""


def is_repo(data_dir: Path) -> bool:
    return (data_dir / ".git").exists()


def repo_problem(data_dir: Path) -> str:
    """hl doctor 用：git 读这个仓库出不出错（仓库坏了、没有权限）；不出错返回空串。"""
    try:
        _git(data_dir, "status", "--porcelain")
    except (OSError, subprocess.SubprocessError) as exc:
        return _brief(exc)
    return ""


def head_text(data_dir: Path, where: str) -> str | None:
    """最近一次提交里这个文件的内容。数据目录不是 git 仓库、文件没提交过、HL_NO_GIT=1 时
    返回 None。"""
    if os.environ.get("HL_NO_GIT") == "1" or not is_repo(data_dir):
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(data_dir), "show", f"HEAD:{where}"],
            capture_output=True,
            timeout=git_runner.GIT_TIMEOUT,
        )
        return done.stdout.decode("utf-8") if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None


def _head(data_dir: Path) -> str:
    """HEAD 指着的提交；还没有提交过时是空串。"""
    return _git(data_dir, "rev-parse", "-q", "--verify", "HEAD", check=False).stdout.strip()


def _committed(data_dir: Path, before: str, message: str) -> bool:
    """git commit 没有正常结束（超时被停掉、报了错），这次的提交却已经做完了：HEAD 换了，新的
    提交就是这次的说明（第十轮 I-6）。查不了当作没提交。"""
    try:
        now = _head(data_dir)
        said = _git(data_dir, "log", "-1", "--format=%B", check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(now) and now != before and said == message.strip()


def unfinished_problem(data_dir: Path) -> str:
    """hl doctor 用：仓库里有做到一半的合并、变基……（这时写命令一律拒绝）；没有返回空串。"""
    try:
        doing = unfinished(data_dir)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"查不了仓库里有没有做到一半的合并、变基：{_brief(exc)}"
    return UNFINISHED_DOCTOR.format(what=doing[0], how=doing[1]) if doing else ""


def signing(data_dir: Path) -> bool:
    """用户开了提交签名（commit.gpgsign）。"""
    try:
        done = _git(data_dir, "config", "--bool", "commit.gpgsign", check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.stdout.strip() == "true"
