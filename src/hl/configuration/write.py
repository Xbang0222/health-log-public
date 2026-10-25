"""食品构建信息的配置写回。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from hl.configuration.restore import toml_fix
from hl.configuration.values import CONFIG_NAME, _foods_end, _toml_string, _with_raw_dir
from hl.result import Abort, error
from hl.storage import io as storage_io


def set_foods_build(data_dir: Path, sha: str, raw_dir: str) -> None:
    """把成分表副本的哈希和构建用的原始数据目录写进 hl.toml 的 [foods]，其余内容和注释原样保留。
    记下原始数据目录，副本坏了的改法才能给出照抄就能跑的命令（R15）。"""
    path = data_dir / CONFIG_NAME
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^(sha256\s*=\s*)"[^"]*"', rf'\g<1>"{sha}"', text, count=1, flags=re.MULTILINE
    )
    if count == 0:
        what = 'hl.toml 的 [foods] 里找不到 sha256 = "…" 这一行，引擎写不进新的哈希'
        raise Abort(error(what, toml_fix(data_dir)))
    storage_io.write_text(path, _with_raw_dir(updated, raw_dir))


def set_foods_values(data_dir: Path, values: dict[str, str]) -> None:
    """把几项文字写进 hl.toml 的 [foods]：有这一行就换掉值，没有（以前的 hl.toml）就加在这一节
    最后一项后面，其余内容和注释原样保留。写完读回来核对，对不上就不写、报错。"""
    path = data_dir / CONFIG_NAME
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        line = re.compile(
            rf"""^({re.escape(key)}\s*=\s*)(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*')""", re.MULTILINE
        )
        written = _toml_string(value)
        text, count = line.subn(lambda hit, new=written: hit[1] + new, text, count=1)
        end = _foods_end(text) if count == 0 else None
        if end is not None:
            text = f"{text[:end]}\n{key} = {written}{text[end:]}"
    try:
        foods = tomllib.loads(text).get("foods", {})
    except tomllib.TOMLDecodeError:
        foods = None
    if not isinstance(foods, dict) or any(foods.get(k) != v for k, v in values.items()):
        what = f"hl.toml 的 [foods] 写不进 {'、'.join(values)}"
        raise Abort(error(what, toml_fix(data_dir)))
    storage_io.write_text(path, text)
