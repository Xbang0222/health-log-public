"""Git 钩子安装与主仓库、关联工作树的配置边界。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hl.storage.git_messages import (
    HOOKS,
    HOOKS_COMMAND,
    HOOKS_KEPT,
    HOOKS_OVER_GLOBAL,
    HOOKS_REPLACED,
    HOOKS_WORKTREE_COMMAND,
    OUTER_REPO,
    WORKTREE_BROKEN,
    WORKTREE_DOCTOR,
    WORKTREE_FIX,
    WORKTREE_NO_FIX,
    WORKTREE_SHARED,
)
from hl.storage.git_runner import _brief, _git
from hl.storage.git_state import _shown, git_paths, is_repo


def _own_hooks(data_dir: Path) -> tuple[str, list[str]]:
    """已有的仓库自己的钩子：（钩子文件夹，说给用户听的；里面的钩子）。git 自带的 .sample 示例
    不算。文件夹照 git 说的找（git rev-parse --git-path hooks）：.git 是个文件时不在 .git/hooks。"""
    try:
        (folder,) = git_paths(data_dir, "hooks")
        names = sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix != ".sample")
    except (OSError, subprocess.SubprocessError):
        return "", []
    return _shown(data_dir, folder), names


def _worktree_of(data_dir: Path) -> Path | None:
    """数据目录是另一个项目的 worktree（git worktree add 出来的）时，那个项目的 git 目录；不是时
    （普通仓库、--separate-git-dir、子模块）是 None。"""
    lines = _git(data_dir, "rev-parse", "--git-dir", "--git-common-dir").stdout.splitlines()
    own, common = (Path(line) if os.path.isabs(line) else data_dir / line for line in lines)
    return None if own.resolve() == common.resolve() else common.resolve()


def _worktree_config(data_dir: Path) -> bool:
    """开了 extensions.worktreeConfig：每个 worktree 有自己的设置（git config --worktree）。"""
    done = _git(data_dir, "config", "--bool", "extensions.worktreeConfig", check=False)
    return done.stdout.strip() == "true"


def _shared_traps(data_dir: Path, common: Path) -> list[str]:
    """worktree 共用的设置（common/config）里开了 extensions.worktreeConfig 就会套到每个 worktree
    上的：core.bare = true、设了 core.worktree。返回说给用户听的这几样。"""
    config = str(common / "config")
    bare = _git(data_dir, "config", "--file", config, "--bool", "core.bare", check=False)
    tree = _git(data_dir, "config", "--file", config, "core.worktree", check=False)
    found = ["core.bare = true"] if bare.stdout.strip() == "true" else []
    return found + (["core.worktree"] if tree.returncode == 0 and tree.stdout.strip() else [])


def _worktree_advice(data_dir: Path, common: Path) -> str:
    """worktree 下要只设这个 worktree 怎么办：开 extensions.worktreeConfig 再 hl init；共用设置里
    有开了会把所有 worktree 弄坏的，不给这条路（第十轮 I-4）。"""
    traps = _shared_traps(data_dir, common)
    if traps:
        return WORKTREE_NO_FIX.format(main=_main_of(common), names="、".join(traps))
    return WORKTREE_FIX


def worktree_trap(data_dir: Path) -> str:
    """hl doctor 用（git 读不了仓库时）：数据目录是 worktree，开了 extensions.worktreeConfig，共用
    设置里又有 core.bare = true 或 core.worktree，所有 worktree 都用不了 git。说出原因和撤回的
    命令；不是这种情况返回空串。"""
    try:
        common = _worktree_of(data_dir)
        if common is None or not _worktree_config(data_dir):
            return ""
        traps = _shared_traps(data_dir, common)
    except (OSError, subprocess.SubprocessError):
        return ""
    if not traps:
        return ""
    return WORKTREE_BROKEN.format(main=_main_of(common), names="、".join(traps))


def _main_of(common: Path) -> str:
    """worktree 所属的那个项目，说给用户听的：git 目录是 项目/.git 时说项目，不然说 git 目录。"""
    return str(common.parent if common.name == ".git" else common)


def hooks_fix(data_dir: Path) -> str:
    """hl doctor 用：core.hooksPath 没指向 .githooks 时怎么改。worktree 下不叫用户改共用的设置。"""
    try:
        common = _worktree_of(data_dir)
        if common is None:
            return f"运行 {HOOKS_COMMAND}"
        if _worktree_config(data_dir):
            return f"运行 {HOOKS_WORKTREE_COMMAND}"
        fix = _worktree_advice(data_dir, common)
    except (OSError, subprocess.SubprocessError):
        return f"运行 {HOOKS_COMMAND}"
    return WORKTREE_DOCTOR.format(main=_main_of(common), fix=fix)


def _outer_repo(data_dir: Path) -> str:
    """数据目录还不是仓库，却在别的 git 仓库里面，那个仓库又没有跟踪它下面的任何文件时，那个仓库
    （它的工作目录）；不然是空串。跟踪着的，在数据目录里另建了仓库，外层照样提交得到新文件。"""
    top = _git(data_dir, "rev-parse", "--show-toplevel", check=False)
    outer = top.stdout.strip()
    if top.returncode != 0 or not outer or Path(outer).resolve() == data_dir.resolve():
        return ""
    tracked = _git(data_dir, "ls-files", "-z", "--", ".", check=False)
    return "" if tracked.returncode != 0 or tracked.stdout else outer


def git_init(data_dir: Path) -> tuple[list[str], bool]:
    """数据目录还不是 git 仓库时初始化一个；新建的、原来就有的，都让提交前跑 .githooks/pre-commit
    （第 9 节第 4 层）。返回（提醒，建没建仓库、设没设 core.hooksPath）。
    数据目录在别的仓库里面时照建（自动提交要它），提醒用户那个仓库从此不提交这里的文件。"""
    fresh = not is_repo(data_dir)
    try:
        outer = _outer_repo(data_dir) if fresh else ""
        if fresh:
            _git(data_dir, "init", "-q")
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"git 初始化失败：{_brief(exc)}"], False
    warnings, changed = _hooks_path(data_dir, fresh)
    return ([OUTER_REPO.format(outer=outer)] if outer else []) + warnings, changed or fresh


def _hooks_path(data_dir: Path, fresh: bool) -> tuple[list[str], bool]:
    """让提交前跑 .githooks/pre-commit。原来的仓库自己设了 core.hooksPath 的不改它，只提醒用户；
    全局或系统设置里设了的，照设本地的（不然手工提交前不跑 hl check），提醒用户那边的钩子在这里
    不再运行。数据目录是另一个项目的 worktree 时，git 设置两边共用：开了 extensions.worktreeConfig
    的只设这个 worktree（git config --worktree），没开的不设，提醒用户；开了却因为共用设置里的
    core.bare 把所有 worktree 都弄坏了的，也不设，提醒用户撤回（第十轮 I-4）。
    返回（提醒，设没设 core.hooksPath）。"""
    try:
        common = _worktree_of(data_dir)
        scope = "--local"
        if common is not None:
            if not _worktree_config(data_dir):
                shared = _git(data_dir, "config", "--local", "core.hooksPath", check=False)
                if shared.stdout.strip() == HOOKS:  # 以前的引擎已经设在共用的设置里了
                    return [], False
                if shared.stdout.strip():
                    return [HOOKS_KEPT.format(path=shared.stdout.strip())], False
                fix = _worktree_advice(data_dir, common)
                return [WORKTREE_SHARED.format(main=_main_of(common), fix=fix)], False
            broken = worktree_trap(data_dir)
            if broken:  # 开了却把所有 worktree 弄坏了：什么也不设，先请用户撤回
                return [broken], False
            scope = "--worktree"
        given = _git(data_dir, "config", scope, "core.hooksPath", check=False).stdout.strip()
        if given == HOOKS:
            return [], False
        if given:
            return [HOOKS_KEPT.format(path=given)], False
        # 这里没设，全局、系统（worktree 下还有共用的）设置里设了：这里的值会盖过它，那边的钩子
        # 在这里就不跑了。这时 git 默认的钩子文件夹里的钩子本来也不跑，不算被换掉的
        wider = _git(data_dir, "config", "core.hooksPath", check=False).stdout.strip()
        wider = "" if wider == HOOKS else wider
        folder, replaced = ("", []) if fresh or wider else _own_hooks(data_dir)
        _git(data_dir, "config", scope, "core.hooksPath", HOOKS)
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"git 初始化失败：{_brief(exc)}"], False
    if wider:
        return [HOOKS_OVER_GLOBAL.format(path=wider)], True
    if replaced:
        return [HOOKS_REPLACED.format(folder=folder, names="、".join(replaced))], True
    return [], True


def hooks_path(data_dir: Path) -> str:
    """当前仓库的 core.hooksPath；没设或取不到时返回空串。"""
    try:
        return _git(data_dir, "config", "core.hooksPath", check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
