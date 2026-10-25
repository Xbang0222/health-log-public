"""自动提交前检查本次写过的账本文件。"""

from __future__ import annotations

from pathlib import Path

from hl.configuration import read as configuration_read
from hl.configuration import values as configuration_values
from hl.foods import custom
from hl.ledgercheck.days import read_day_file
from hl.ledgercheck.defaults import read_defaults_file
from hl.ledgercheck.messages import DEFAULTS_FILE, PLAN_FILE
from hl.ledgercheck.plans import read_plan_file
from hl.result import Abort
from hl.storage import keys as storage_keys


def unsound(data_dir: Path, paths: list[str]) -> list[str]:
    """自动提交前用：这次写过的文件里，自己还有 hl check 会报的问题的那几个（第 9 节第 4 层）。

    每日文件、计划、默认品种、用户库照读时校验看（不重算营养：写的时候刚算过），hl.toml 看读不
    读得出来；别的（hl init 生成的模板）不看。
    """
    found = []
    for where in paths:
        path = data_dir / where
        if where == configuration_values.CONFIG_NAME:
            try:
                configuration_read.read_settings(data_dir)
            except Abort:
                found.append(where)
            continue
        if where == custom.FILE:  # 用户库（增补第 8.5 节）：整个文件和每一条的结构、签名
            if custom.problems(data_dir, storage_keys.secret(data_dir)):
                found.append(where)
            continue
        if where not in (PLAN_FILE, DEFAULTS_FILE) and not where.startswith("log/"):
            continue
        key = storage_keys.secret(data_dir)
        if where == PLAN_FILE:
            errors = read_plan_file(data_dir, key)[1]
        elif where == DEFAULTS_FILE:
            errors = read_defaults_file(data_dir, key)[1]
        else:
            errors = read_day_file(data_dir, key, None, path)[1]
        if errors:
            found.append(where)
    return found
