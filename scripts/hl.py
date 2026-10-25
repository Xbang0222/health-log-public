#!/usr/bin/env python3
"""Portable source entry point; defaults to this project's engine and ledger."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import runtime


def failed(message: str) -> int:
    result = {
        "status": "error",
        "error": message,
        "next": "运行 python3 scripts/bootstrap.py；离线安装见 docs/portable-install.md",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 1


def main() -> int:
    runtime.utf8()
    problem = runtime.use_local_venv(Path(__file__).resolve(), sys.argv[1:])
    if problem:
        return failed(f"本地环境不可用：{problem}")
    problem = runtime.platform_problem()
    if problem:
        return failed(problem)
    python = runtime.selected_python()
    ready, why = runtime.probe(python)
    if not ready:
        # This is an explicit setup instruction, not an implicit network download
        # on a read/query command. bootstrap creates/reuses .venv automatically.
        return failed(f"运行环境尚未就绪：{why}")
    sys.path.insert(0, str(runtime.ROOT / "src"))
    from hl.cli import main as cli_main

    # A source project owns its default ledger, independent of cwd or an inherited
    # HL_DATA from another project. The CLI still handles explicit --data / init DIR.
    # Keep argv and cwd unchanged: JSON text and relative input paths are user data.
    os.environ["HL_DATA"] = str(runtime.ROOT)
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
