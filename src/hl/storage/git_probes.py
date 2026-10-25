"""Git 忽略规则和已跟踪私有文件的只读探测。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hl.storage.git_messages import KEEP_OUT, KEPT_OUT, LISTED, NEGATED_RULES, NOT_EXCLUDED
from hl.storage.git_runner import _git
from hl.storage.io import HIDDEN


def _listed(paths: list[str]) -> str:
    shown = "、".join(paths[:LISTED])
    return shown if len(paths) <= LISTED else f"{shown} 等 {len(paths)} 个"


def _check_ignore(data_dir: Path, *args: str, paths: list[str]) -> list[tuple[str, str, str, str]]:
    """git check-ignore -v -z --stdin：每个是（规则所在的文件，行号，规则，路径）。"""
    feed = "".join(f"{where}\0" for where in paths)
    done = _git(data_dir, "check-ignore", "-v", "-z", "--stdin", *args, check=False, input=feed)
    if done.returncode > 1:  # 0：有被忽略的；1：一个也没有；别的是 git 自己出错
        raise subprocess.CalledProcessError(done.returncode, done.args, done.stdout, done.stderr)
    fields = done.stdout.split("\0")
    return list(zip(*[iter(fields)] * 4, strict=False))


def _leaks(data_dir: Path, rule: str) -> tuple[list[str], dict[str, str]]:
    """这条规则该挡住、git 却没挡住的路径，和其中被 .gitignore 的 ! 规则放出来的（连同规则，
    “.gitignore 第 2 行的 !*/”）。只看忽略规则，不管文件进没进 git（进了的 IN_GIT 另外说）。

    .hl/ 不光试密钥：白名单式的 .gitignore（* 再 !*/、!*.json）照样忽略密钥，却放出了成分表副本、
    清单——引擎会写的每一种文件都试，再加上 git ls-files -o --exclude-standard 列出的（git add -A
    会放进去的）。"""
    probes = KEEP_OUT[rule]
    found = _check_ignore(data_dir, "--no-index", paths=list(probes))
    ignored = {where for _, _, pattern, where in found if not pattern.startswith("!")}
    leaks = [where for where in probes if where not in ignored]
    if rule == f"{HIDDEN}/":
        listed = _git(data_dir, "ls-files", "-z", "-o", "--exclude-standard", "--", HIDDEN)
        leaks += [where for where in listed.stdout.split("\0") if where and where not in leaks]
    if not leaks:
        return [], {}
    asked = [HIDDEN, *leaks] if rule == f"{HIDDEN}/" else leaks  # .hl 这个文件夹本身也可能被放出来
    negated = {
        where: f"{source} 第 {line} 行的 {pattern}"
        for source, line, pattern, where in _check_ignore(data_dir, "-n", "--no-index", paths=asked)
        if pattern.startswith("!")
        and not os.path.isabs(source)
        and Path(source).name == ".gitignore"
    }
    return leaks, negated


def _beaten(rule: str, negated: dict[str, str]) -> bool:
    """这条规则写进 .git/info/exclude 也盖不过：.gitignore 的 ! 规则放出了要挡的东西本身。.hl/
    看的是 .hl 这个文件夹：只放出里面某类文件的（!*.json、!.hl/secret）盖得过，文件夹被 exclude
    忽略之后，里面的文件就放不出来了（第十轮 I-5）。"""
    return HIDDEN in negated if rule == f"{HIDDEN}/" else bool(negated)


def _not_excluded(rule: str, negated: dict[str, str]) -> str:
    said = NOT_EXCLUDED.format(what=KEPT_OUT[rule])
    return said + (NEGATED_RULES.format(rules=_rules(negated)) if negated else "")


def _exclude_lines(exclude: Path) -> set[str]:
    try:
        return {line.strip() for line in exclude.read_text(encoding="utf-8").splitlines()}
    except (OSError, UnicodeDecodeError):
        return set()


def _hidden_tracked(data_dir: Path) -> list[str]:
    """已经进了 git（在暂存区或提交里）的 .hl/ 下的文件。"""
    listed = _git(data_dir, "ls-files", "-z", "--", HIDDEN).stdout.split("\0")
    return [path for path in listed if path]


def _rules(found: dict[str, str]) -> str:
    return "、".join(list(dict.fromkeys(found.values()))[:LISTED])
