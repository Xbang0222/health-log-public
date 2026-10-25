"""账本审计的结果类型、共享标识和固定文案。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from hl.manifests import model as manifests_model
from hl.storage import io as storage_io

PLAN_FILE = storage_io.PLAN_FILE


DEFAULTS_FILE = storage_io.DEFAULTS_FILE


Found = list[tuple[str, str]]  # 每个是（问题，改法）


Checked = tuple[Any, Found, Found]  # 内容、内容本身的问题、对照清单的缺口


Restorable = Callable[[], bool]  # git 恢复这条路走不走得通：要给改法时才去看


NEXT_DATA = manifests_model.NEXT_DATA


TAMPERED = "这个文件不是经 hl 写入的，或被直接改过。运行 hl check 查看全部问题。"


NO_GIT = (
    "git 恢复不了（数据目录不是 git 仓库、这个文件从没提交过，"
    "或者提交里的那一份也有问题、缺了东西）"
)


HALT = "就此停下，不要自己改文件"


FIX_SUGGEST = (
    "suggest.yaml 是用户自己的配置，不受保护：照上面说的直接改这个文件；"
    "不想自己定候选食物，把它删掉就用引擎自带的"
)


FIX_CANDIDATE = (
    "concept 和 variant 要照抄概念表里的概念名和品种名（例如 concept: 鸡胸肉, variant: 鸡胸）"
)


NEXT_SUGGEST = (
    "suggest.yaml 是用户的配置文件，只影响“接下来可以吃什么”：把 errors 原样告诉用户，"
    "按 fix 改好或删掉这个文件，再调用一次；别的数据文件不要直接改"
)


_IN_ENTRY = re.compile(r"entries\[(\d+)\]")


WHOLE = object()  # 默认品种文件整个的问题，不是哪一条的（键可以是 null，不能拿 None 当记号）


FIX_STRAY = (
    "log/ 下只放引擎写的每日文件，名字是 log/YYYY/MM/DD.yaml（扩展名小写），这个文件不是："
    "把问题告诉用户，请用户把它移出 log/（是写错了名字的每日文件，就改成规范的名字），"
    f"改完再运行 hl check；你{HALT}"
)


FIX_LINK = (
    "log/ 下要放真的文件夹和文件，不能是符号链接：git 只记下链接本身，里面的记录不会提交，"
    "清单重建也读不到它。把问题原样告诉用户，请用户把它换成链接指向的那个文件夹或文件本身"
    "（把那边的东西挪到这个位置，替换掉链接；指向的东西已经不在了，就请用户找回来），"
    f"换好再运行 hl check；你{HALT}"
)
