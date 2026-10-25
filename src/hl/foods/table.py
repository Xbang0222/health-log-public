"""食品副本的修复诊断与公共导出。

编码和营养运算唯一位于 table_types，副本读取唯一位于 table_io。"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

import yaml

from hl.configuration import values as configuration_values
from hl.foods import cn6
from hl.foods.table_io import BOOHEE_ABSENT as BOOHEE_ABSENT
from hl.foods.table_io import BOOHEE_FILE as BOOHEE_FILE
from hl.foods.table_io import BOOHEE_SKIPPED as BOOHEE_SKIPPED
from hl.foods.table_io import BOOHEE_WHERE as BOOHEE_WHERE
from hl.foods.table_io import FILE as FILE
from hl.foods.table_io import FIX_BOOHEE_FETCH as FIX_BOOHEE_FETCH
from hl.foods.table_io import WHERE as WHERE
from hl.foods.table_io import BooheeLayer as BooheeLayer
from hl.foods.table_io import TableError as TableError
from hl.foods.table_io import _foods as _foods
from hl.foods.table_io import boohee_note as boohee_note
from hl.foods.table_io import boohee_path as boohee_path
from hl.foods.table_io import boohee_problem as boohee_problem
from hl.foods.table_io import boohee_text as boohee_text
from hl.foods.table_io import load as load
from hl.foods.table_io import load_boohee as load_boohee
from hl.foods.table_io import path as path
from hl.foods.table_io import serialize as serialize
from hl.foods.table_io import sha256_of as sha256_of
from hl.foods.table_types import AMOUNT as AMOUNT
from hl.foods.table_types import BOOHEE as BOOHEE
from hl.foods.table_types import BUILTIN as BUILTIN
from hl.foods.table_types import BUILTINS as BUILTINS
from hl.foods.table_types import CN6 as CN6
from hl.foods.table_types import CONTENT as CONTENT
from hl.foods.table_types import CUSTOM as CUSTOM
from hl.foods.table_types import DIGITS as DIGITS
from hl.foods.table_types import EST as EST
from hl.foods.table_types import MARKS as MARKS
from hl.foods.table_types import NUTRIENTS as NUTRIENTS
from hl.foods.table_types import OLD_AMOUNT_SRC as OLD_AMOUNT_SRC
from hl.foods.table_types import OLD_CONTENT_SRC as OLD_CONTENT_SRC
from hl.foods.table_types import PREFIXES as PREFIXES
from hl.foods.table_types import RECOMPUTED as RECOMPUTED
from hl.foods.table_types import SALT as SALT
from hl.foods.table_types import SOURCES as SOURCES
from hl.foods.table_types import TOLERANCE as TOLERANCE
from hl.foods.table_types import Boohee as Boohee
from hl.foods.table_types import Food as Food
from hl.foods.table_types import Table as Table
from hl.foods.table_types import View as View
from hl.foods.table_types import agrees as agrees
from hl.foods.table_types import join as join
from hl.foods.table_types import make_row as make_row
from hl.foods.table_types import marks as marks
from hl.foods.table_types import nutrients as nutrients
from hl.foods.table_types import ref as ref
from hl.foods.table_types import round_half_up as round_half_up
from hl.foods.table_types import split as split
from hl.manifests import model as manifests_model
from hl.result import Abort, error, problem, rejected
from hl.storage import days as storage_days
from hl.storage import io as storage_io
from hl.storage import keys as storage_keys

# 引擎不知道原始数据目录时：模型没法替用户找，也不能拿别的目录凑（成分表和原始数据不在引擎里）
FIX_INSTALLER = (
    "引擎不知道当初构建用的原始数据目录：把问题原样告诉用户，请装 hl 的人用那个原始数据目录"
    "运行 hl foods build {verb}成分表副本；你就此停下，不要自己找目录，也不要拿别的目录构建"
)

# hl.toml 比成分表副本旧（取回了上一次 hl foods build 之前的那一份）：照它记的目录重建，
# 正常的记录反倒对不上。引擎不知道构建现在这份副本的目录，只能请装 hl 的人来
FIX_TOML_BEHIND = (
    "hl.toml 比成分表副本旧：{entry}是照现在这份副本算的，拿 hl.toml 里记的原始数据目录 {raw} "
    "重建，副本就变了，这条正常的记录反倒对不上（多半是 hl.toml 取回了上一次 hl foods build "
    "之前的那一份）。不要拿 {raw} 构建：把问题原样告诉用户，请装 hl 的人用构建现在这份副本的"
    "原始数据目录运行 hl foods build，把哈希写回 hl.toml；你就此停下，不要自己找目录"
)


def require(data_dir: Path, expected_sha: str) -> Table:
    """给需要成分表的命令用：用不了就结束这条命令。"""
    try:
        return load(data_dir, expected_sha)
    except TableError as exc:
        if exc.kind == "missing":
            raise Abort(error(str(exc), fix(exc, data_dir))) from exc
        # 和 hl check 说的一样：是数据文件的问题，不是输入写错了
        what = problem(WHERE, str(exc), fix(exc, data_dir))
        raise Abort(rejected([what], manifests_model.NEXT_DATA)) from exc


def fix(exc: TableError, data_dir: Path) -> str:
    """成分表副本用不了的改法：不存在就构建，被改过就重新构建，读不了只能请用户看一下。

    构建要用当初的原始数据目录：hl foods build 记在 hl.toml 里，还在就给出照抄能跑的命令；
    没记下、或者已经不在了，就请装 hl 的人来，模型停下。不留“<原始数据目录>”这种填不了的
    占位符：照抄进 shell 是语法错误，照抄进 hl 是“不是一个目录”（R15）。
    """
    if exc.kind == "unreadable":
        return storage_io.FIX_OS
    verb = "构建" if exc.kind == "missing" else "重新构建"
    raw = configuration_values.foods_raw_dir(data_dir)
    if raw and Path(raw).is_dir():
        entry = _behind(data_dir, Path(raw)) if exc.kind == "broken" else None
        if entry is not None:
            return FIX_TOML_BEHIND.format(entry=entry, raw=raw)
        return f"用上次构建时的原始数据目录{verb}成分表副本：运行 hl foods build {shlex.quote(raw)}"
    gone = f"上次构建用的原始数据目录 {raw} 已经不在了。" if raw else ""
    return gone + FIX_INSTALLER.format(verb=verb)


def _copy(data_dir: Path) -> tuple[str, Table, dict[str, Any]] | None:
    """现在的副本，不核对哈希：（全文，成分表，meta）；读不出来是 None。"""
    try:
        text = path(data_dir).read_text(encoding="utf-8")
        doc = json.loads(text)
        meta = doc["meta"]
        return text, _foods(doc), meta if isinstance(meta, dict) else {}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _rebuilt(raw: Path, meta: dict[str, Any]) -> tuple[str, Table] | None:
    """拿 raw 照副本里记的来源和版本重建一份（不写）：（全文，成分表）；建不出来是 None。"""
    try:
        doc, problems = cn6.build(raw, str(meta.get("source", "")), str(meta.get("commit", "")))
        return None if problems else (serialize(doc), _foods(doc))
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None


def built_from(data_dir: Path, raw: Path, shas: set[str]) -> bool:
    """拿 raw 重建出来的副本，哈希是不是 shas 里的一个（R15）：是的话照 raw 重建不改副本。"""
    copy = _copy(data_dir)
    rebuilt = _rebuilt(raw, copy[2]) if copy is not None else None
    return rebuilt is not None and sha256_of(rebuilt[0]) in shas


def _behind(data_dir: Path, raw: Path) -> str | None:
    """副本的哈希和 hl.toml 里记的不一致，又是 hl.toml 旧了时：照现在的副本算的一条记录
    （“log/…yaml 里的 e2”）；看不出来是 None（R15）。

    哈希不一致可能是副本被改过，也可能是 hl.toml 旧了（取回了上一次 hl foods build 之前的
    那一份）。拿 hl.toml 里记的原始数据目录重建一份（不写）：和现在的副本一样，只是哈希旧了，
    照它重建不改副本。不一样时看签名有效的记录：有一条和现在的副本对得上、和重建的对不上，
    它是引擎照现在的副本算的——记它那时 hl.toml 里是现在这份副本的哈希，现在的 hl.toml 比那时旧，
    照它重建，这条正常的记录反倒被当成改过。一条都没有（副本被改过；记录都和两份对得上），
    照 hl.toml 重建不碍记录。
    """
    copy = _copy(data_dir)
    rebuilt = _rebuilt(raw, copy[2]) if copy is not None else None
    if copy is None or rebuilt is None or rebuilt[0] == copy[0]:
        return None
    key, _, _ = storage_keys.read_secret(data_dir)
    if key is None:
        return None
    for file, day in storage_days.day_like_files(data_dir):
        try:
            entries = storage_io.read_yaml(file)["entries"]
            for entry in entries:
                if storage_keys.signed(key, "entry", day, entry) and any(
                    agrees(row, copy[1]) and not agrees(row, rebuilt[1]) for row in entry["items"]
                ):
                    return f"{file.relative_to(data_dir).as_posix()} 里的 {entry['id']} "
        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError, AttributeError):
            continue  # 读不出来、形状不对的不算：hl check 另外会报
    return None
