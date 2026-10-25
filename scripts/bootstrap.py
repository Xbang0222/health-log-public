#!/usr/bin/env python3
"""Create/reuse this checkout's .venv and install its runtime dependencies."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import runtime


def note(text: str) -> None:
    print(text, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    runtime.utf8()
    parser = argparse.ArgumentParser(
        description="安装 health-log 本地运行环境，不改账本或全局 Python"
    )
    parser.add_argument("--index-url", help="指定 PyPI 镜像；不自动切换第三方源")
    parser.add_argument("--offline", action="store_true", help="不联网，只使用现有依赖或本地 wheel")
    parser.add_argument("--wheelhouse", type=Path, help="离线依赖 wheel 所在目录")
    parser.add_argument("--dev", action="store_true", help="同时安装测试、lint 和构建依赖")
    args = parser.parse_args(argv)
    problem = runtime.platform_problem()
    if problem:
        note(problem)
        return 1
    if args.offline and args.index_url:
        parser.error("--offline 与 --index-url 不能同时使用")
    if args.wheelhouse and not args.wheelhouse.is_dir():
        parser.error("--wheelhouse 必须是现有目录")
    root = runtime.ROOT
    python = runtime.venv_python(root)
    if (root / ".venv").is_symlink():
        note("源码目录的 .venv 是符号链接；为避免改动其他环境，未安装任何依赖。")
        note("移走该链接后重新运行 bootstrap.py，账本目录不受影响。")
        return 1
    if not (root / ".venv").exists():
        note(f"创建本地运行环境：{root / '.venv'}")
        result = subprocess.run(
            [sys.executable, "-I", "-m", "venv", str(root / ".venv")],
            stdout=sys.stderr,
            check=False,
        )
        if result.returncode:
            note("创建失败，尚未安装。Linux 可能需要系统的 python3-venv 包。")
            note("确认 .venv 仅为本项目运行环境后，可移走它再重试；账本目录不受影响。")
            return 1
    if not python.is_file():
        note(f"本地环境不可用：{python}。从其他电脑复制来的 .venv 不能直接迁移。")
        note("移走本项目的 .venv 后重新运行 bootstrap.py；不要移走账本的 .hl。")
        return 1
    if not (root / ".venv/pyvenv.cfg").is_file():
        note("本地 .venv 缺少 pyvenv.cfg；移走残缺环境后重新运行 bootstrap.py。")
        return 1
    usable, why = runtime.venv_usable(root)
    if not usable:
        note(f"本地环境不可用，未安装任何依赖：{why}")
        note("移走本项目 .venv 后重新运行 bootstrap.py。")
        return 1
    ready, why = runtime.probe(python, dev=args.dev)
    if not ready:
        note(f"准备依赖：{why}")
        pip_environ = runtime.pip_environment()
        pip_check = [str(python), "-I", "-m", "pip", "--version"]
        has_pip = subprocess.run(
            pip_check,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=pip_environ,
            check=False,
        )
        if has_pip.returncode:
            note("本地环境缺少 pip，使用 Python 自带 ensurepip 离线补齐。")
            repaired = subprocess.run(
                [str(python), "-I", "-m", "ensurepip", "--upgrade"],
                stdout=sys.stderr,
                env=pip_environ,
                check=False,
            )
            verified = subprocess.run(
                pip_check,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=pip_environ,
                check=False,
            )
            if repaired.returncode or verified.returncode:
                note("本地环境缺少 pip，且 ensurepip 无法补齐；环境尚未就绪，没有修改账本。")
                note("使用带 ensurepip 的完整 Python 重建本项目 .venv；Linux 可安装 python3-venv。")
                return 1
        # Ignore user-level pip/env target overrides: installation belongs to this
        # venv. Explicit mirrors/wheelhouses remain available as command options.
        command = [
            str(python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
        ]
        if args.offline:
            command.append("--no-index")
        if args.index_url:
            command += ["--index-url", args.index_url]
        if args.wheelhouse:
            command += ["--find-links", str(args.wheelhouse.resolve())]
        command += runtime.requirements(dev=args.dev)
        try:
            installed = subprocess.run(command, stdout=sys.stderr, env=pip_environ, check=False)
        except OSError as exc:
            note(f"不能运行本地解释器：{exc}。移走本项目 .venv 后重试。")
            return 1
        if installed.returncode:
            note("依赖安装失败，环境尚未就绪，没有修改账本。")
            note("联网后重试，或用 --offline --wheelhouse <目录> 安装预先下载的依赖。")
            return 1
        ready, why = runtime.probe(python, dev=args.dev)
        if not ready:
            note(f"安装后验证失败，环境尚未就绪：{why}")
            return 1
    note("环境已就绪。运行 python3 scripts/hl.py --help；不需要激活环境或修改 PATH。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
