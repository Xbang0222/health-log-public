"""清单文件路径、签名核验和原子写入。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl.configuration import read as configuration_read
from hl.configuration import values as configuration_values
from hl.manifests.model import FILE, FIX_LOST, WHERE
from hl.result import problem
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys


def _path(data_dir: Path) -> Path:
    return data_dir / storage_io.HIDDEN / FILE


def read(data_dir: Path, key: bytes) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """读清单并验签，返回（清单，问题）。还没建过清单的数据目录返回（None，[]）：不对照。"""
    try:
        body = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if configuration_read.manifest_built(data_dir):
            return None, [problem(WHERE, "清单不见了", FIX_LOST)]
        return None, []
    except ValueError:
        return None, [problem(WHERE, "清单读不出来", FIX_LOST)]
    except OSError:  # 是个目录、没有权限：重建也写不进去，只能请用户看一下
        return None, [problem(WHERE, f"清单{storage_io.UNREADABLE}", storage_io.FIX_OS)]
    if not isinstance(body, dict) or not storage_keys.signed(key, "manifest", "", body):
        return None, [problem(WHERE, "清单的签名不对：它不是引擎写的，或被直接改过", FIX_LOST)]
    protocol = body.get("protocol", 1)
    configured = configuration_read.read_settings(data_dir)["format"]
    if protocol > configured:
        return None, [
            problem(
                WHERE,
                "格式标记退回了旧版，但签名清单证明已采用新协议",
                "从完整备份恢复配置和操作历史，不能重新迁移或重签",
            )
        ]
    for listed in body["days"].values():
        if isinstance(listed["entries"], list):  # 早先的清单只记了 id：那几条只对 id
            listed["entries"] = dict.fromkeys(listed["entries"])
    for name, value in body.get("defaults", {}).items():
        if isinstance(value, str):  # 早先的清单只记了签名，没记品种
            body["defaults"][name] = {"sig": value}
    return body, []


def _write(data_dir: Path, key: bytes, body: Mapping[str, Any], mark: str | None) -> None:
    """签名后写清单；mark 是加了记号的 hl.toml 全文，清单写好之后才写它。"""
    signed = {name: value for name, value in body.items() if name != "sig"}
    signed["days"] = dict(sorted(signed["days"].items()))
    signed["sig"] = storage_keys.sign(key, "manifest", "", signed)
    storage_io.write_text(_path(data_dir), json.dumps(signed, ensure_ascii=False, indent=1) + "\n")
    if mark is not None:
        storage_io.write_text(data_dir / configuration_values.CONFIG_NAME, mark)
