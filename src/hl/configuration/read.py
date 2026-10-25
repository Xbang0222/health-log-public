"""配置目录发现、可信配置读取和清单初始化标记。"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl.configuration.restore import toml_fix
from hl.configuration.values import (
    CONFIG_NAME,
    FORMAT,
    HINT_INIT,
    MANIFEST_MARK,
    Context,
    _settings_wrong,
    now,
    today,
)
from hl.result import Abort, Result, error
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys


def find_data_dir(environ: Mapping[str, str], *starts: Path) -> Path | None:
    """HL_DATA 优先；没有就依次从各个起点向上找 hl.toml。"""
    explicit = environ.get("HL_DATA")
    if explicit:
        root = Path(explicit).expanduser()
        return root if (root / CONFIG_NAME).is_file() else None
    for start in starts:
        for folder in (start, *start.parents):
            if (folder / CONFIG_NAME).is_file():
                return folder
    return None


def _orphan(environ: Mapping[str, str], cwd: Path) -> Path | None:
    """找不到 hl.toml 时，看是不是数据目录还在、只是 hl.toml 没了：HL_DATA 指的目录里有 .hl/ 或
    log/，或者从当前目录向上有一层有 .hl/。"""
    explicit = environ.get("HL_DATA")
    if explicit:
        root = Path(explicit).expanduser()
        found = (root / storage_io.HIDDEN).is_dir() or (root / "log").is_dir()
        return root if found else None
    return next((f for f in (cwd, *cwd.parents) if (f / storage_io.HIDDEN).is_dir()), None)


def read_settings(data_dir: Path) -> dict[str, Any]:
    """读 hl.toml，并核对引擎要用的几项；读不出来、写法不对都在这里报，不等用到时才报。"""
    try:
        settings = tomllib.loads((data_dir / CONFIG_NAME).read_text(encoding="utf-8"))
    except (IsADirectoryError, PermissionError) as exc:  # git 取回的文件也放不进去
        raise Abort(error(f"{CONFIG_NAME} {storage_io.UNREADABLE}", storage_io.FIX_OS)) from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise Abort(error(f"hl.toml 读不出来：{exc}", toml_fix(data_dir))) from exc
    if settings.get("format") not in (1, FORMAT):
        found = settings.get("format")
        raise Abort(error(f"数据格式版本是 {found}，这个引擎支持 format = 1（只读）或 {FORMAT}"))
    wrong = _settings_wrong(settings)
    if wrong:
        raise Abort(error(f"hl.toml 写法不对：{wrong}", toml_fix(data_dir)))
    return settings


def missing_toml(data_dir: Path) -> Result:
    """数据目录里已经有签过名的数据，hl.toml 却不见了：只能取回原来那一份。hl init 生成的模板
    哈希是空的、没有清单建过的记号，照它走下去成分表、清单都对不上（R22）。"""
    what = f"数据目录 {data_dir} 里没有 {CONFIG_NAME}：它被删掉或者移走了"
    return error(what, toml_fix(data_dir))


def load(environ: Mapping[str, str], cwd: Path) -> Context:
    data_dir = find_data_dir(environ, cwd)
    if data_dir is None:
        orphan = _orphan(environ, cwd)
        if orphan is not None and (orphan / CONFIG_NAME).exists():  # 在，只是不是个文件
            raise Abort(error(f"{CONFIG_NAME} {storage_io.UNREADABLE}", storage_io.FIX_OS))
        if orphan is not None and storage_keys.signed_data(orphan):
            raise Abort(missing_toml(orphan))
        raise Abort(error("找不到数据目录（没有 hl.toml）", HINT_INIT))
    return Context(
        data_dir=data_dir,
        today=today(environ),
        now=now(environ),
        no_git=environ.get("HL_NO_GIT") == "1",
        settings=read_settings(data_dir),
    )


def manifest_built(data_dir: Path) -> bool:
    """hl.toml 里有没有“清单已经建过”的记号（R15）。"""
    return read_settings(data_dir).get("manifest", {}).get("built") is True


def manifest_mark(data_dir: Path) -> str | None:
    """加上“清单已经建过”的记号之后 hl.toml 的全文；已经有记号时返回 None。只算不写。"""
    if manifest_built(data_dir):
        return None
    text = (data_dir / CONFIG_NAME).read_text(encoding="utf-8")
    marked = text.rstrip("\n") + "\n" + MANIFEST_MARK
    try:
        built = tomllib.loads(marked)["manifest"]["built"] is True
    except (tomllib.TOMLDecodeError, KeyError, TypeError):
        built = False
    if not built:  # 读的时候已经核对过 [manifest]：到这里是别处的写法让记号加不上去
        what = "hl.toml 的写法让引擎加不上“清单已经建过”的记号"
        raise Abort(error(what, toml_fix(data_dir)))
    return marked
