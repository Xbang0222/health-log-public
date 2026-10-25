"""Git 状态、私有文件保护和修复建议的固定文案。"""

from __future__ import annotations

from hl.storage.io import HIDDEN

# ---------- git ----------
# 提交不上的提醒：说给用户的只是“没能提交到 git”和原因；给模型的话（运行哪条命令）只在 warnings 里
UNSOUND = "没能提交到 git：{files} 里还有 hl check 查出的问题（这次的数据已经写入，不受影响）"

THEN_CHECK = "运行 hl check，照各条的 fix 修好"

FAILED = "没能提交到 git（数据已经写入，不受影响）：{brief}"

THEN_DOCTOR = "要查原因，运行 hl doctor 看“git 自动提交”那一项"

# 提交做完了（HEAD 已经是这次的提交），git 却没有正常结束：多半是提交之后的钩子卡住、到时间被停掉
# 了。不说“没能提交”（规则 3：提交失败才说失败）
COMMITTED_ANYWAY = (
    "这次写的已经提交到 git，可 git 没有正常结束（{brief}）：多半是提交之后的钩子（post-commit 等）"
    "没跑完，它要做的事（比如推送）可能没做完"
)

THEN_COMMITTED = "提交已经做完，不用再提交，也不用查 hl doctor；把这件事告诉用户"

NO_GIT_COMMAND = "找不到 git 命令（PATH 里没有它）"

# 锁的位置不一定在 .git/ 下（.git 是个文件时在别处）：这里不说路径，hl doctor 说
LOCKED = "仓库被别的 git 命令锁着（index.lock 在）"

HINTS = ("hint:", "提示：", "提示:")  # git 报错里的建议行

STUCK_IGNORED = "{files} 被 git 的忽略规则挡住了（{rules}）"

STUCK_LINK = "{files} 在符号链接 {link} 里面，git 不提交符号链接里面的文件"

# 提交不上的只有模板（.claude/、.codex/ 下的）这类不是账本的文件：hl doctor 不查它们，不叫模型去看
THEN_RULE = (
    "这几个不是账本文件，不碍记账：把这件事告诉用户，要它们进 git，请用户照上面说的改好，"
    "再自己提交它们；你不用再查原因"
)

IGNORED_LEDGER = (
    "这些文件被 git 的忽略规则挡住了，自动提交提交不上：{files}（{rules}）；请用户改一下那条规则"
)

# 以前提交不上（被忽略规则挡住过）的账本文件：规则改好之后引擎也不补交（只提交每次写的文件）
UNTRACKED_LEDGER = (
    "这些账本文件不在 git 里（以前没提交上，引擎只提交每次写的文件，不会补交）：{files}，"
    "它们坏了 git 取不回来；请用户在数据目录里运行 {command}，再提交（手工提交前会先跑 hl check）"
)

# 进了 git、却有没提交的改动的（那次自动提交没做成：合并做到一半、超时……）：坏了 git 只取得回
# 旧的那份，这些改动就没了（第十轮 I-7）
UNCOMMITTED_LEDGER = (
    "这些账本文件有没提交的改动（以前那次自动提交没做成，引擎只提交每次写的文件，不会补交）：{files}，"
    "它们坏了 git 只取得回旧的那份，这些改动就没了；请用户在数据目录里运行 {command}，再提交"
    "（手工提交前会先跑 hl check）"
)

STILL_LOCKED = "，停掉它之后 {lock} 还在：没有别的 git 命令在跑的话，删掉它就恢复"

# 仓库里做到一半的 git 操作（.git 里的记号）：这时写账本，写的会搅进用户的操作，用户放弃它
# （--abort）时还会被一起抹掉。引擎的写命令一律拒绝（规则 19）
UNFINISHED = {
    "MERGE_HEAD": (
        "合并（git merge、git pull）做到一半",
        "解决冲突后 git commit 做完，或者 git merge --abort 放弃",
    ),
    "rebase-merge": (
        "变基（git rebase）做到一半",
        "git rebase --continue 做完，或者 git rebase --abort 放弃",
    ),
    "rebase-apply": (
        "变基（git rebase）做到一半",
        "git rebase --continue 做完，或者 git rebase --abort 放弃",
    ),
    "CHERRY_PICK_HEAD": (
        "拣选（git cherry-pick）做到一半",
        "git cherry-pick --continue 做完，或者 git cherry-pick --abort 放弃",
    ),
    "REVERT_HEAD": (
        "撤销提交（git revert）做到一半",
        "git revert --continue 做完，或者 git revert --abort 放弃",
    ),
    # git bisect 把旧的提交取了出来：照它写，写的是旧账本，结束时还会被换回去
    "BISECT_START": ("二分查找（git bisect）做到一半", "找没找到都用 git bisect reset 结束"),
}

APPLYING = "rebase-apply/applying"  # rebase-apply 里有它是 git am

AM = ("打补丁（git am）做到一半", "git am --continue 做完，或者 git am --abort 放弃")

# 拣选、撤销几个提交时，用户手工提交了当前这一个（没用 --continue）：CHERRY_PICK_HEAD 没了，
# 后面几个还在这里等着
SEQUENCER = "sequencer/todo"

SEQUENCE = (
    "拣选或撤销提交（git cherry-pick、git revert）做到一半",
    "git cherry-pick --continue（或 git revert --continue）做完，或者用对应的 --abort 放弃",
)

UNFINISHED_PROBLEM = (
    "数据目录所在的 git 仓库里{what}：这时写账本，写的会搅进这次 git 操作，"
    "放弃它的时候还会被一起抹掉，所以这次什么都没有写"
)

FIX_UNFINISHED = (
    "把问题原样告诉用户，请用户自己做完或者放弃（{how}）；你不要自己运行这些 git 命令，"
    "也不要改文件。用户说办好之前不要再调用；用户说办好了，再原样调用一次这条命令"
)

NEXT_UNFINISHED = (
    "这不是输入写错了：数据目录所在的 git 仓库里有做到一半的操作，引擎这次什么都没有写。"
    "把 problem 原样告诉用户，照 fix 请用户先做完或者放弃；用户说办好之前不要再调用，"
    "说办好了再原样调用一次同一条命令"
)

# 写之前查过没有，写的时候用户才开始的：自动提交不往里搅；这次写的还没进 git
UNFINISHED_RACE = (
    "没能提交到 git：仓库里{what}（这次写入时才开始），引擎不提交，免得搅进去；"
    "这次写的已经在文件里、还没进 git，用户放弃那个操作时可能被一起抹掉"
)

UNFINISHED_DOCTOR = (
    "仓库里{what}：这时引擎的写命令一律拒绝（写的会搅进去，放弃时还会被一起抹掉）；"
    "请用户自己做完或者放弃（{how}），之后照常记"
)

SIGNING = "commit.gpgsign 开着：引擎自己的提交不签名（签名程序在没人看着时签不了），手工提交照常签"

LINKED_LOG = "log/ 下有符号链接，git 不提交它里面的文件：{links}（运行 hl check，照它的 fix 办）"

HOOKS = ".githooks"

HOOKS_KEPT = (
    "数据目录原来就是 git 仓库，提交前的钩子设在了 {path}（core.hooksPath），引擎没有改它："
    "手工提交前不会先跑 hl check，改坏的文件可能被提交进去"
)

HOOKS_REPLACED = (
    "数据目录原来就是 git 仓库：引擎把 core.hooksPath 设成了 .githooks（提交前跑 hl check），"
    "{folder} 里原来的钩子（{names}）在数据目录里提交时不再运行"
)

HOOKS_OVER_GLOBAL = (
    "git 的全局、系统或共用的设置里 core.hooksPath 是 {path}：引擎在这个仓库里把它设成了 .githooks"
    "（提交前跑 hl check），在这个仓库里手工提交时，{path} 里的钩子不再运行"
)

# 数据目录是另一个项目的 worktree：git 设置两边共用，设 core.hooksPath 会连那个项目的钩子一起换掉。
# 开了 extensions.worktreeConfig 才能只设这个 worktree（git config --worktree）；开不开由用户定
WORKTREE_FIX = (
    "要只设这个 worktree，请用户在数据目录里运行 git config extensions.worktreeConfig true，"
    "再运行 hl init"
)

# 共用的设置里有 core.bare = true（裸仓库加几个 worktree 的布局）或 core.worktree 时，开了
# extensions.worktreeConfig 它们就套到每个 worktree 上（git 文档说要先挪进 config.worktree），
# 所有 worktree 都用不了 git：这时不给开它这条路，说清楚为什么
WORKTREE_NO_FIX = (
    "{main} 的共用设置里有 {names}：这时开 extensions.worktreeConfig，它会套到每个 worktree 上，"
    "所有 worktree 都用不了 git，所以不要开。请用户在数据目录里手工提交前，先运行 hl check"
)

WORKTREE_SHARED = (
    "数据目录是 {main} 的一个 worktree，两边共用一份 git 设置：在这里设 core.hooksPath 会连 {main} "
    "的钩子一起换掉，引擎没有设，手工提交前不会先跑 hl check。{fix}"
)

WORKTREE_DOCTOR = (
    "数据目录是 {main} 的一个 worktree，git 设置两边共用，设在共用的设置里会连 {main} 的钩子"
    "一起换掉；{fix}"
)

# 已经开了：git 只说“必须在一个工作区中运行”，doctor 说出原因和撤回的命令
WORKTREE_BROKEN = (
    "开了 extensions.worktreeConfig，{main} 的共用设置里又有 {names}：它套到了每个 worktree 上，"
    "所有 worktree 都用不了 git。请用户在数据目录里运行 git config --unset "
    "extensions.worktreeConfig 撤回，再运行 hl doctor"
)

HOOKS_COMMAND = "git config core.hooksPath .githooks"

OUTER_REPO = (
    "数据目录在 git 仓库 {outer} 里面，引擎在数据目录里另建了一个仓库（自动提交要用）：{outer} "
    "以后只记下一个指向它的记号，不提交数据目录里的文件，靠提交、推送 {outer} 备份的话，健康记录"
    "不在那份备份里。{outer} 的设置引擎没有动；要备份，请用户给数据目录自己的仓库另设一个远端推送"
)

HOOKS_WORKTREE_COMMAND = "git config --worktree core.hooksPath .githooks"

# 不进 git 的：引擎内部文件（签名密钥、用户原话……）和写到一半的临时文件。
# 每条规则配几个拿来试的路径（git check-ignore 看的是路径，不是规则），各试各的：一条报错
# （比如 log 是符号链接，问它里面的路径就报错）不连累另一条。.hl/ 试引擎会在那里写的每一种
# 文件（白名单式的 .gitignore 可能只放出 *.json）；临时文件写在目标文件旁边，试数据目录里
# 那个（.plan.yaml.<随机>.tmp），不往子文件夹里试
KEEP_OUT = {
    f"{HIDDEN}/": tuple(
        f"{HIDDEN}/{name}"
        for name in ("secret", "lock", "manifest.json", "cn6.json", "boohee.json", "pending.json")
        + ("inbox.jsonl", "hook-errors.log")
    ),
    "*.tmp": (".plan.yaml.x1.tmp",),
}

KEPT_OUT = {f"{HIDDEN}/": "签名密钥、用户原话（.hl/ 下）", "*.tmp": "写到一半的临时文件（*.tmp）"}

EXCLUDE_NOTE = "# health-log：引擎内部文件（.hl/）和写到一半的临时文件不进 git\n"

EXCLUDED = (
    "数据目录原来的 .gitignore 里没有 {rules}：引擎把它们写进了 .git/info/exclude，"
    "git 不会再把{what}提交进去。这只管这台机器上的这个仓库，.gitignore 没有改"
)

# .gitignore 里的 ! 规则把它们放了出来：.gitignore 比 .git/info/exclude 优先，引擎写什么都盖不过
# （.hl/ 只看 .hl 这个文件夹本身被放出来没有，见 _beaten）。
# hl init、hl doctor 和提交前的钩子说的都是这一句（钩子模板里的 {not_excluded} 生成时填进去）
NOT_EXCLUDED = (
    "数据目录的 .gitignore 里有 ! 规则让 git 不忽略{what}，写进 .git/info/exclude 也盖不过它："
    "手工 git add -A 时它们会被提交进去。引擎改不了，请用户改一下 .gitignore"
)

NEGATED_RULES = "（是这几条：{rules}）"

NOT_IGNORED = (
    "git 没有忽略 {rules}：手工 git add -A 时，{what}会被提交进去；"
    "运行 hl init，它把这几条写进 .git/info/exclude"
)

IN_GIT = (
    ".hl/ 下有文件进了 git（{files}）：签名密钥、用户原话在提交历史里。"
    "运行 git rm -r --cached -f -q -- .hl，再提交：以后的提交里就没有它们了"
    "（文件本身不动；已有的提交里还留着）"
)

# 数据目录在外层仓库里、外层仓库又会提交数据目录下的文件（跟踪着那里的文件，或者数据目录不是
# 自己的仓库）：外层不看数据目录仓库的 .git/info/exclude，.hl/ 要外层自己忽略（规则 20）
OUTER_NOTE = "# health-log：数据目录里的引擎内部文件（签名密钥、用户原话）不进 git\n"

OUTER_TAKES = "数据目录在 git 仓库 {outer} 里面，那个仓库会把数据目录下的文件提交进去"

OUTER_EXCLUDED = (
    OUTER_TAKES + "，原来却没有忽略 .hl/：引擎把 {rule} 写进了那个仓库的 .git/info/exclude，"
    "在那里 git add -A 不会再把签名密钥、用户原话（.hl/ 下）提交进去。"
    "这只管这台机器上的那个仓库，它的 .gitignore 没有改"
)

OUTER_NOT_IGNORED = (
    OUTER_TAKES + "，却没有忽略 .hl/：在那里手工 git add -A 时，签名密钥、用户原话（.hl/ 下）"
    "会被提交进去；运行 hl init，它把 {rule} 写进那个仓库的 .git/info/exclude"
)

OUTER_NOT_EXCLUDED = (
    OUTER_TAKES + "，它的 .gitignore 里有 ! 规则让 git 不忽略签名密钥、用户原话（.hl/ 下），"
    "写进那个仓库的 .git/info/exclude 也盖不过：在那里手工 git add -A 时它们会被提交进去。"
    "引擎改不了，请用户改一下那条规则（{rules}）"
)

OUTER_STILL_OPEN = (
    OUTER_TAKES + "，{rule} 已经写在那个仓库的 .git/info/exclude 里，git 还是没有忽略 {files}："
    "在那里手工 git add -A 时它们会被提交进去。引擎查不出是哪条规则放出了它们，"
    "请用户看一下那个仓库的忽略规则"
)

OUTER_IN_GIT = (
    "数据目录所在的 git 仓库 {outer} 里有 .hl/ 下的文件进了 git（{files}）：签名密钥、用户原话在"
    "它的暂存区或提交历史里。请用户运行 {command}，再在那个仓库里提交：以后的提交里就没有它们了"
    "（文件本身不动；已有的提交里、推送过的远端上还留着）"
)

LISTED = 5  # 提醒里最多列出几个文件

WORKTREE_TMP = (
    "当前工作树尚未忽略 *.tmp；共用 exclude 没有改动，"
    "请用户在当前工作树的 .gitignore 中加入 *.tmp，避免提交写到一半的临时文件"
)

WORKTREE_PRIVATE = (
    "当前工作树尚未保护全部 .hl/ 私有文件；运行 hl init，"
    "引擎会在 .hl/.gitignore 追加保护规则，共用 exclude 不会改动"
)
