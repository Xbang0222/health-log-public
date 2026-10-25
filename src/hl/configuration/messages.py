"""配置丢失、回退与恢复建议的固定文案。"""

from __future__ import annotations

from hl.configuration.values import CONFIG_NAME

FIX_TOML = f"用 git 恢复它（git checkout HEAD -- {CONFIG_NAME}），再调用一次"


FIX_TOML_STOP = (
    "git 恢复不了（数据目录不是 git 仓库、这个文件从没提交过，或者提交里的那一份也不对）："
    f"把 error 原样告诉用户，请用户从备份恢复 {CONFIG_NAME}，或者自己照 error 说的改好它；"
    "你就此停下，不要自己改文件"
)


FIX_TOML_OLD = (
    "最近一次提交里的 {name} 比现在的旧（{lag}），照它取回不对。把 error 原样告诉用户，"
    "请用户从备份恢复 {name}；没有备份的话，请用户自己取回最近一次提交里的那一份{edit}。{then}"
)


THEN_STOP = "你就此停下，不要自己改文件"


# 重建成分表是安全的 hl 命令，模型来跑，不留给用户：用户只取回了 hl.toml 就说办好了，
# 模型先跑 hl check 的话，副本又被当成改过（R15）。命令后面先空一格再接标点，照抄时不会把
# 全角标点一起带进目录
THEN_BUILD = (
    "用户说办好之前你就此停下，不要自己改文件；用户说办好了（取回的、从备份恢复的都一样），"
    "你先运行 hl foods build {raw} ，再运行 hl check。这条命令用的是现在这份 hl.toml "
    "里记的原始数据目录（现在的成分表副本就是用它构建的），会把成分表的哈希写回 hl.toml"
)


NO_MARK = (
    "里面没有“清单已经建过”的记号 [manifest] built = true：取回之后清单再不见，"
    "引擎会当它从没建过，删掉的记录就查不出来了"
)


ADD_MARK = "在末尾加上 [manifest] 和 built = true 两行"


OLD_TABLE = (
    "里面成分表的哈希（[foods] sha256）{how}：取回它，引擎会把现在的成分表副本当成被改过，"
    "照它的改法重建，正常的记录又会对不上"
)


OLD_SHA = "是旧的，和现在这份里记的不一样（多半是上一次 hl foods build 之后没提交上）"


OLD_COPY = (
    "和现在的成分表副本 .hl/cn6.json 算出来的对不上，多半是上一次 hl foods build 之后没提交上、"
    "它是旧的（也可能是副本被改过）"
)


REBUILD_ASK = "请装 hl 的人用构建现在这份成分表副本的原始数据目录运行 hl foods build"


REBUILD_OLD_DIR = "（最近一次提交里记的是 {raw}，不一定是那个目录）"
