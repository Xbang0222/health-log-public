#!/usr/bin/env python3
"""Export the public source selection into a new/empty directory, without Git or network."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath


def _relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or any(part in (".", "..") for part in path.parts)
        or path.as_posix() != value
        or any(mark in value for mark in ("\\", "*", "?", "[", "~"))
    ):
        raise ValueError(f"清单必须使用明确的项目内相对路径：{value!r}")
    return Path(*path.parts)


def _source(root: Path, relative: Path) -> Path:
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"公开源文件不能包含符号链接：{relative}")
    if not path.exists():
        raise ValueError(f"公开清单中的源文件不存在：{relative}")
    return path


def _excluded(relative: str, patterns: list[str]) -> bool:
    # The project's exclusion list uses ordinary globs; **/ may match zero folders.
    for pattern in patterns:
        if pattern.startswith("!"):
            raise ValueError("导出不支持反向 exclude 规则，请使用明确的允许清单")
        variants = (pattern, pattern.removeprefix("**/"))
        if any(fnmatch.fnmatchcase(relative, item) for item in variants):
            return True
    return False


def selection(root: Path) -> dict[Path, Path]:
    """Use the same file list and forced path mapping as the source distribution."""
    import tomllib

    with _source(root, Path("pyproject.toml")).open("rb") as handle:
        config = tomllib.load(handle)["tool"]["hatch"]["build"]["targets"]["sdist"]
    if config.get("ignore-vcs") is not True:
        raise ValueError("公开 sdist 必须设置 ignore-vcs = true，只由明确清单决定内容")
    includes = config["only-include"]
    excludes = config.get("exclude", [])
    forced = config.get("force-include", {})
    if not isinstance(includes, list) or not includes or not all(
        isinstance(item, str) for item in includes
    ):
        raise ValueError("sdist.only-include 必须是非空路径列表")
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise ValueError("sdist.exclude 必须是字符串列表")
    if not isinstance(forced, dict) or not all(
        isinstance(source, str) and isinstance(target, str) for source, target in forced.items()
    ):
        raise ValueError("sdist.force-include 必须是相对文件路径映射")
    selected: dict[Path, Path] = {}

    def visit(relative: Path) -> None:
        path = _source(root, relative)
        is_dir = path.is_dir()
        name = relative.as_posix() + ("/" if is_dir else "")
        if _excluded(name, excludes):
            return
        if is_dir:
            for child in sorted(path.iterdir()):
                visit(child.relative_to(root))
        elif stat.S_ISREG(path.stat().st_mode):
            selected[relative] = path
        else:
            raise ValueError(f"公开源文件不是普通文件：{relative}")

    for relative in includes:
        visit(_relative(relative))
    for source, target in forced.items():
        path = _source(root, _relative(source))
        target_path = _relative(target)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError(f"force-include 必须映射普通文件：{source}")
        if target_path in selected:
            raise ValueError(f"force-include 与已有公开路径冲突：{target}")
        selected[target_path] = path
    if any(parent in selected for path in selected for parent in path.parents):
        raise ValueError("公开清单中的文件路径与目录路径冲突")
    return dict(sorted(selected.items()))


def export(source: Path, destination: Path) -> int:
    if source.is_symlink():
        raise ValueError("源项目不能是符号链接")
    source = source.resolve()
    requested = destination.expanduser().absolute()
    if any(path.is_symlink() for path in (requested, *requested.parents)):
        raise ValueError("导出目标不能包含符号链接")
    target = requested.resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("导出目标不能是源项目、其子目录或祖先目录")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("导出目标必须是新目录或空目录；不会删除或覆盖已有内容")
    files = selection(source)  # Validate every source before creating any output.
    target.mkdir(parents=True, exist_ok=True)
    for relative, original in files.items():
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        _source(source, original.relative_to(source))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(original, flags)
        with os.fdopen(descriptor, "rb") as reader, output.open("xb") as writer:
            mode = os.fstat(reader.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"公开源文件已变成非普通文件：{original}")
            shutil.copyfileobj(reader, writer)
            os.fchmod(writer.fileno(), stat.S_IMODE(mode) & 0o777)
    return len(files)


def get_build_hook():
    """Keep Hatch's automatically included VCS file from exposing private rules."""
    import tempfile

    from hatchling.builders.hooks.plugin.interface import BuildHookInterface

    class PublicSourceHook(BuildHookInterface):
        def initialize(self, version, build_data):
            root = Path(self.root)
            files = selection(root)
            # Sdist normally force-includes the private root .gitignore even when
            # it is excluded. Retain only defaults matching the public selection.
            forced = build_data["force_include"]
            for source, target in list(forced.items()):
                if files.get(Path(target)) != Path(source):
                    del forced[source]
            self.replacements = tempfile.TemporaryDirectory(prefix="health-log-public-")
            for target, source in files.items():
                original = source.relative_to(root)
                if target == original or original not in files:
                    continue
                # Hatch reserves a forced source, removing its original path.
                # Preserve that resource for rebuilding/exporting from the sdist,
                # and force a temporary copy to the requested public destination.
                forced[str(source)] = original.as_posix()
                copied = Path(self.replacements.name) / str(len(forced))
                copied.write_bytes(source.read_bytes())
                shutil.copymode(source, copied, follow_symlinks=False)
                forced[str(copied)] = target.as_posix()

        def finalize(self, version, build_data, artifact_path):
            self.replacements.cleanup()

    return PublicSourceHook


def main(argv: list[str] | None = None) -> int:
    sys.dont_write_bytecode = True
    import runtime

    runtime.utf8()
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description="按 pyproject 允许清单导出公共源码，不含私有历史")
    parser.add_argument("destination", type=Path, help="源项目之外的新目录或空目录")
    args = parser.parse_args(argv)
    problem = runtime.use_local_venv(Path(__file__).resolve(), argv)
    if problem or sys.version_info < (3, 11):
        print(problem or "导出需要 Python 3.11+；可先准备本项目运行环境", file=sys.stderr)
        return 1
    try:
        count = export(runtime.ROOT, args.destination)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"未完成公开导出：{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"destination": str(args.destination.resolve()), "files": count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
