"""核查 HEAD 版本是否完整可信，决定能否建议 Git 恢复。"""

from __future__ import annotations

from pathlib import Path

import yaml

from hl.foods.table_types import Table
from hl.ledgercheck.messages import DEFAULTS_FILE, PLAN_FILE, Restorable
from hl.ledgercheck.reading import _read
from hl.ledgercheck.structure import day_problems, defaults_problems, plan_problems
from hl.manifests import io as manifests_io
from hl.manifests import retention as manifests_retention
from hl.storage import days as storage_days
from hl.storage import git_state as storage_git_state


def _head_sound(data_dir: Path, key: bytes, where: str, table: Table | None) -> bool:
    """最近一次提交里的这个文件拿回来用得上（R15）。一样不缺才给 git：

    - 它自己过得了校验；
    - 工作区那一份里每一样签名有效的东西（记录、体重、当天类型、默认品种、计划的各版）它都有，
      而且是同一条——没提交的写入（关了自动提交、写清单前断了、文件还有问题这次没提交）就在这里；
      清单里记着的是另一条的除外：工作区那一条本来就不对；
    - 清单里记着的它都有；清单里没有的它不多带——没提交的撤销、去掉的默认品种不能被带回来；
      工作区里本来就多出来的除外，取回前后一样，照那一条的 fix 收场。

    清单读不出来、不见了、还没建过、没有那一节，都不算核对过：只拿工作区那一份比，
    HEAD 那份里有、工作区里根本没有的东西，也不给。
    文件名只差大小写时也不给：git 改不回名字（misnamed）。
    """
    if storage_days.misnamed(data_dir / where) is not None:
        return False
    text = storage_git_state.head_text(data_dir, where)
    if text is None:
        return False
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    listed, _ = manifests_io.read(data_dir, key)  # 清单有问题时是 None：用不上
    now, _ = _read(data_dir / where)  # 工作区那一份；不在、读不出来是 None
    if where == PLAN_FILE:
        plans = [] if data is None else data
        if plan_problems(key, plans):
            return False
        return manifests_retention.head_keeps_plans(listed, key, plans, now)
    if where == DEFAULTS_FILE:
        defaults = {} if data is None else data
        if defaults_problems(key, defaults):
            return False
        return manifests_retention.head_keeps_defaults(listed, key, defaults, now)
    day = storage_days.day_of(data_dir, data_dir / where)
    if day_problems(key, table, day, data, where, lambda: False):
        return False
    return manifests_retention.head_keeps_day(listed, key, day, data, now)


def _restorable(data_dir: Path, key: bytes, where: str, table: Table | None = None) -> Restorable:
    """git 恢复这条路走不走得通（R15）。数据目录不是 git 仓库、文件没提交过、HL_NO_GIT=1，
    或者提交里的那一份也有问题、缺了清单里记着的东西，都走不通：照 fix 恢复了，要么还是坏的，
    要么把还没提交的记录一起抹掉。要给改法时才去看，只看一次。"""
    found: list[bool] = []

    def get() -> bool:
        if not found:
            found.append(_head_sound(data_dir, key, where, table))
        return found[0]

    return get
