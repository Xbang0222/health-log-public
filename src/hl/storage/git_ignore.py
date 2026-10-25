"""数据目录私有文件和临时文件的忽略保护。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hl.storage.git_hooks import _worktree_of
from hl.storage.git_messages import (
    EXCLUDE_NOTE,
    EXCLUDED,
    IN_GIT,
    KEEP_OUT,
    KEPT_OUT,
    NOT_IGNORED,
    WORKTREE_PRIVATE,
    WORKTREE_TMP,
)
from hl.storage.git_probes import (
    _beaten,
    _exclude_lines,
    _hidden_tracked,
    _leaks,
    _listed,
    _not_excluded,
)
from hl.storage.git_runner import _brief
from hl.storage.git_state import git_paths
from hl.storage.io import HIDDEN


def _private_ignore(data_dir: Path) -> bool:
    """linked worktree 的 exclude 共用；在私有目录内追加规则，仅保护当前目录。

    不覆盖已有规则，不跟随规则文件的符号链接，不把这个私有文件交给自动提交。
    调用方在写后用 git check-ignore 和 ls-files 复查，不能只凭规则写进去了就算保护好。
    """
    path = data_dir / HIDDEN / ".gitignore"
    if path.is_symlink() or path.parent.is_symlink():
        raise OSError(f"{path} 是符号链接，不能写入私有忽略规则；请用户检查")
    old = path.read_bytes() if path.exists() else b""
    lines = [line.strip() for line in old.splitlines() if line.strip()]
    if lines and lines[-1] == b"*":
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    lead = b"\n" if old and not old.endswith(b"\n") else b""
    with path.open("ab") as handle:
        handle.write(lead + b"# health-log: private engine files\n*\n")
    return True


def _keep_out_worktree(data_dir: Path) -> tuple[list[str], bool]:
    warnings = []
    wrote = False
    if _leaks(data_dir, f"{HIDDEN}/")[0]:
        wrote = _private_ignore(data_dir)
        if _leaks(data_dir, f"{HIDDEN}/")[0]:
            warnings.append(
                ".hl/.gitignore 的保护规则没有覆盖全部私有文件，请用户检查该目录下的忽略规则；"
                "未保护好前不要手工 git add -A"
            )
        elif wrote:
            warnings.append("已在 .hl/.gitignore 追加私有文件保护规则，只在当前工作树生效")
    if _leaks(data_dir, "*.tmp")[0]:
        warnings.append(WORKTREE_TMP)
    tracked = _hidden_tracked(data_dir)
    if tracked:
        warnings.append(IN_GIT.format(files=_listed(tracked)))
    return warnings, wrote


def keep_out(data_dir: Path) -> tuple[list[str], bool]:
    """hl init 用：让 git 忽略 .hl/ 和 *.tmp（R14：.hl/ 不进 git）。用户自己的 .gitignore 不改，
    缺的规则写进 .git/info/exclude，提醒一句；linked worktree 改用私有目录内的规则，
    不改共用 exclude。返回（提醒，写没写忽略规则）。

    写进去也盖不过的（.gitignore 里的 ! 规则放出了 .hl 这个文件夹、*.tmp 文件，_beaten）不写，
    请用户改 .gitignore；只放出 .hl/ 下某类文件的照写，写完复查，还漏着才这么说。已经在 exclude
    里的不再写（以前每跑一次追加一段）。已经进了 git 的，说出来怎么拿掉。"""
    warnings: list[str] = []
    wrote = False
    try:
        if _worktree_of(data_dir) is not None:
            return _keep_out_worktree(data_dir)
        (exclude,) = git_paths(data_dir, "info/exclude")
        present = _exclude_lines(exclude)
        leaks = {rule: _leaks(data_dir, rule) for rule in KEEP_OUT}
        missing = [
            rule
            for rule, (open_, negated) in leaks.items()
            if open_ and not _beaten(rule, negated) and rule not in present
        ]
        if missing:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            old = exclude.read_bytes() if exclude.exists() else b""
            lead = "\n" if old and not old.endswith(b"\n") else ""
            block = lead + EXCLUDE_NOTE + "".join(f"{rule}\n" for rule in missing)
            with open(exclude, "ab") as handle:
                handle.write(block.encode("utf-8"))
            wrote = True
            leaks.update({rule: _leaks(data_dir, rule) for rule in missing})
            fixed = [rule for rule in missing if not leaks[rule][0]]
            if fixed:
                what = "、".join(KEPT_OUT[rule] for rule in fixed)
                warnings.append(EXCLUDED.format(rules="、".join(fixed), what=what))
        warnings += [_not_excluded(rule, found) for rule, (open_, found) in leaks.items() if open_]
        tracked = _hidden_tracked(data_dir)
        if tracked:
            warnings.append(IN_GIT.format(files=_listed(tracked)))
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.append(f"没能查 git 有没有忽略 .hl/：{_brief(exc)}")
    return warnings, wrote


def hidden_problem(data_dir: Path) -> str:
    """hl doctor 用：.hl/ 会不会、是不是已经进了 git；没问题返回空串。说法和 hl init 的一样：
    写进 .git/info/exclude 管用的叫运行 hl init，盖不过的（或者写过了还是不管用）请用户改
    .gitignore。"""
    try:
        (exclude,) = git_paths(data_dir, "info/exclude")
        leaks = {rule: _leaks(data_dir, rule) for rule in KEEP_OUT}
        tracked = _hidden_tracked(data_dir)
        worktree = _worktree_of(data_dir) is not None
    except (OSError, subprocess.SubprocessError) as exc:
        return f"查不了：{_brief(exc)}"
    present = _exclude_lines(exclude)
    problems = []
    if tracked:
        problems.append(IN_GIT.format(files=_listed(tracked)))
    missing = []
    for rule, (open_, negated) in leaks.items():
        if open_ and worktree:
            problems.append(WORKTREE_PRIVATE if rule == f"{HIDDEN}/" else WORKTREE_TMP)
        elif open_ and (_beaten(rule, negated) or rule in present):
            problems.append(_not_excluded(rule, negated))
        elif open_:
            missing.append(rule)
    if missing:
        what = "、".join(KEPT_OUT[rule] for rule in missing)
        problems.append(NOT_IGNORED.format(rules="、".join(missing), what=what))
    return "；".join(problems)
