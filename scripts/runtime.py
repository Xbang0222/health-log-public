"""Source checkout runtime selection; standard library only, never touches ledger data."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 11)
MODULES = {"pyyaml": "yaml"}


def utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def platform_problem() -> str | None:
    if sys.version_info < MIN_PYTHON:
        return "需要 Python 3.11 或更新版本；当前是 " + sys.version.split()[0]
    if sys.platform not in ("darwin", "linux"):
        return "当前引擎支持 macOS 和 Linux；Windows 请在 WSL 的 Linux 环境运行"
    return None


def venv_python(root: Path = ROOT) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements(root: Path = ROOT, *, dev: bool = False) -> list[str]:
    # pyproject is the only dependency declaration; no separate list to keep in sync.
    import tomllib

    with (root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    wanted = project["project"]["dependencies"]
    if dev:
        wanted += project.get("dependency-groups", {}).get("dev", [])
    return list(dict.fromkeys(wanted))


def pip_environment() -> dict[str, str]:
    """Pip must not inherit install targets or remote links from any config layer.

    --isolated alone still reads the venv/site pip.conf. PIP_CONFIG_FILE set to
    the null device disables every config file; explicit CLI options remain valid.
    """
    environ = {name: value for name, value in os.environ.items() if not name.startswith("PIP_")}
    environ["PIP_CONFIG_FILE"] = os.devnull
    return environ


def venv_usable(root: Path = ROOT) -> tuple[bool, str]:
    """Check isolation before pip is allowed to install anything."""
    python = venv_python(root)
    source = (
        "import os,sys; "
        "assert sys.version_info >= (3,11), '需要 Python 3.11 或更新版本'; "
        "assert sys.prefix != sys.base_prefix and "
        "os.path.realpath(sys.prefix) == os.path.realpath(sys.argv[1]), "
        "'解释器没有使用本项目的 .venv'"
    )
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", source, str(root / ".venv")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode:
        return False, result.stderr.strip().splitlines()[-1] if result.stderr else "解释器不可用"
    return True, ""


def probe(python: Path, root: Path = ROOT, *, dev: bool = False) -> tuple[bool, str]:
    """Import dependencies in the chosen interpreter, including transitive imports.

    Do not trust a copied .venv merely because its executable exists. Version minima
    are read from pyproject and checked without requiring packaging to be installed.
    """
    local_venv = python.absolute() == venv_python(root).absolute()
    if local_venv and (root / ".venv").is_symlink():
        return False, "源码目录的 .venv 是符号链接；请使用该项目独立的本地虚拟环境"
    if local_venv and not (root / ".venv/pyvenv.cfg").is_file():
        return False, "本地 .venv 缺少 pyvenv.cfg；请移走残缺环境后重新运行 bootstrap.py"
    expected = []
    for requirement in requirements(root, dev=dev):
        match = re.fullmatch(r"([A-Za-z0-9_-]+)>=([0-9.]+)", requirement)
        if match is None:
            return False, f"无法验证依赖声明 {requirement}；请更新 scripts/runtime.py"
        module = MODULES.get(match[1].lower(), match[1].lower().replace("-", "_"))
        expected.append((match[1], module, match[2]))
    source = """
import importlib
import importlib.metadata
import json
import os
import re
import sys
if sys.version_info < (3, 11):
    raise RuntimeError('需要 Python 3.11 或更新版本')
if sys.argv[2] and (sys.prefix == sys.base_prefix
                   or os.path.realpath(sys.prefix) != os.path.realpath(sys.argv[2])):
    raise RuntimeError('解释器没有使用本项目的 .venv；请重新创建本地虚拟环境')
for package, module, minimum in json.loads(sys.argv[1]):
    importlib.import_module(module)
    found = importlib.metadata.version(package)
    # Non-release version strings require pip to resolve the declared constraint.
    if not re.fullmatch(r'[0-9.]+', found):
        raise RuntimeError(package + ' 版本需要重新验证: ' + found)
    have = tuple(int(n) for n in found.split('.'))
    need = tuple(int(n) for n in minimum.split('.'))
    size = max(len(have), len(need))
    if have + (0,) * (size-len(have)) < need + (0,) * (size-len(need)):
        raise RuntimeError(package + '>=' + minimum + '，当前是 ' + found)
"""
    try:
        result = subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                source,
                json.dumps(expected),
                str(root / ".venv") if local_venv else "",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    lines = (result.stderr or result.stdout).strip().splitlines()
    return False, lines[-1] if lines else f"解释器退出码 {result.returncode}"


def selected_python(root: Path = ROOT) -> Path:
    """Prefer the checkout's venv; do not silently fall back from a broken venv."""
    candidate = venv_python(root)
    present = (root / ".venv").exists() or (root / ".venv").is_symlink()
    return candidate if present else Path(sys.executable)


def launch(script: Path, argv: list[str], python: Path) -> None:
    # Resolve both sides only to compare; execute the venv path itself so Python
    # keeps its pyvenv.cfg. Resolving that symlink would escape the venv.
    if Path(sys.executable).absolute() != python.absolute():
        os.execv(str(python), [str(python), str(script), *argv])
