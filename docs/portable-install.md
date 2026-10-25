# 安装、换电脑与离线使用

引擎支持 Python 3.11 及更新版本的 macOS / Linux。Windows 需在 WSL 的 Linux 环境使用；
原生 Windows 尚不支持文件锁。本地运行验证覆盖 macOS 上的 Python 3.11–3.14；
Linux 和 WSL 是适用环境，当前维护记录没有实际 Linux/WSL 运行结果，不把未测系统列作通过。

## 一份项目，直接开始

从公共模板建立自己的完整私有副本，或把完整源码解压到私人持久目录，例如 `~/my-health-log`。
AI 和你都只需打开这个目录，先读根 `AGENTS.md`。不要求 Git、全局 `hl` 或第二个数据目录。
不要把 `/tmp`、下载缓存或一次性云工作区当正式项目；云电脑须先确认项目所在磁盘会长期保留。

在项目根目录运行：

```sh
python3 scripts/bootstrap.py
python3 scripts/hl.py init
```

首次还没有项目 `.venv` 时，bootstrap 必须使用 Python 3.11 或更新的解释器。
如果系统 `python3` 较旧，可改用已安装的 `python3.14 scripts/bootstrap.py`，或指定符合版本要求的解释器完整路径。
引导脚本不会自动安装或替换系统 Python；引擎的最低要求仍是 Python 3.11。

已有有效项目 `.venv` 时，普通 `python3` 可以只作为启动跳板：入口先验证并切入本地环境，
再读取依赖配置和启动引擎，不因系统解释器较旧而忽略可用的本地环境。
损坏的 `.venv` 会明确报错，不回退到系统环境或全局 `hl`；按下文步骤重建运行环境后再继续。

bootstrap 在本项目创建 `.venv`，只安装依赖，不生成账本、不下载食品、不设置 Git。
后续入口自动选择它，不必激活环境、安装 uv 或修改 PATH；重复引导只补缺失或版本不满足的依赖。
依赖声明只有 `pyproject.toml` 一份。`init` 才在**同一个项目根目录**创建 `hl.toml`、账本结构和 `.hl`，
格式 2 初始化还会补齐缺少的 `HEALTH_LOG_V2.md`，已有正文和根个人规则不覆盖。
已有有效格式 2 项目重复 init 时须先通过校验，再补缺少的指南；不能用它代替损坏恢复、规则更新或旧格式迁移。

已有 `hl.toml` 的项目先读取实际规则、配置和已有记录，检查后接着用；不为接手新聊天新建账本。
根 `AGENTS.md` 是日常入口；接着读本项目 `HEALTH_LOG_V2.md`，尚未生成时按根指南读随程序的操作模板。
已有格式 1 按[迁移说明](migration.md)预检和备份后升级。

## 准备或校验食品库

先检查本项目现有食品库；已经齐全并通过校验时直接复用，不因换 AI 或升级程序重新下载或更换版本。
自有概念、菜谱、量词和参考表在 `src/hl/data`。完整第三方快照的来源与校验清单见
[项目数据](../data/foods/README.md)；公开模板只带说明和清单，不带完整第三方数据。

缺食品库且本项目已有完整 `data/foods/raw/cn6`、`data/foods/raw/boohee` 时，优先离线构建：

```sh
python3 scripts/hl.py foods build data/foods/raw/cn6
python3 scripts/hl.py foods build data/foods/raw/boohee
```

现有转换器会将结果写入本项目 `.hl` 并维护食品校验值。不能把 `compiled/*.json` 当原始目录，
也不要手工替换哈希或用重建覆盖尚未查清的损坏。

没有可用的完整本地原始数据时，按固定来源和版本下载：

```sh
python3 scripts/hl.py foods fetch
```

准备完成后运行：

```sh
python3 scripts/hl.py check
python3 scripts/hl.py doctor
python3 scripts/hl.py recent --limit 20
```

检查通过后再开始记账。依赖和食品数据齐全的本地引擎可离线运行，云端 AI 对话仍需要对应服务的网络。
普通结构化写入不依赖 hooks 或宿主信任注册；未启用可选原话采集时，来源只能称为 Agent 提交。

## 项目入口与外部账本兼容

`python3 scripts/hl.py` 始终运行它所在项目的源码，默认数据目录是这个**脚本所属的项目根目录**，
忽略继承的 `HL_DATA`，也不从当前工作目录向上另找账本。因此从其他目录运行绝对路径也指向同一项目：

```sh
python3 /持久目录/my-health-log/scripts/hl.py today
```

已有分离账本或维护工具仍可显式指定外部目录：

```sh
python3 scripts/hl.py --data /另一个私人账本 check
python3 scripts/hl.py init /新的外部私人账本
```

这属于兼容入口，不是普通用户开始使用的必要步骤。选择外部目录不会替宿主加载其规则，
使用前须读取那个账本的实际个人指南。裸安装的 `hl` 保留原有 `HL_DATA`/路径查找行为，
本项目的一目录默认仅由 `scripts/hl.py` 提供；不要混用两个入口猜测写入位置。

## 没有 Git、网络或食物缓存

| 环境 | 可以做什么 | 如何恢复缺少的能力 |
| --- | --- | --- |
| 没有 Git | 引擎本地数据、签名、审计和查询仍可工作；没有 Git 自动提交历史 | 若需要 Git 历史，安装 Git 后按 `doctor` 的提示启用；Git 从来不是完整备份 |
| 没有网络，依赖已安装 | 使用本地缓存和账本，普通记录与查询不需联网 | 联网后才运行 `foods fetch` 更新/恢复缓存 |
| 没有网络，也没有依赖 | 安装尚未完成，不声称可以记账 | 使用目标系统/同一 Python 版本预备的 wheel 包离线安装，或联网重跑 bootstrap |
| 没有食品缓存 | 不能声称已用食品库精算；有依据的显式估算按引擎契约标为估算，未知营养保持未知 | `foods fetch` 下载；已有原始数据用 `foods build <目录>`；也可从完整备份恢复缓存 |

安装屏蔽系统、用户和 `.venv/pip.conf` 中的 pip 配置及继承的 `PIP_*` 选项，防止隐藏的
安装目标或远程包目录改变本地/离线行为。不会自动切换第三方包源。需要镜像时显式指定：

```sh
python3 scripts/bootstrap.py --index-url https://你的镜像/simple
```

离线安装：先在有网络、与目标系统及 Python 版本兼容的机器上准备 `jsonschema>=4.18`
和 `pyyaml>=6.0` 及其传递依赖的 wheel 文件（以该源码的 `pyproject.toml` 为准）。例如：

```sh
python3 -m pip download --only-binary=:all: --dest health-log-wheels 'jsonschema>=4.18' 'pyyaml>=6.0'
```

把源码与 wheel 目录一起带到目标机器，然后运行：

```sh
python3 scripts/bootstrap.py --offline --wheelhouse /完整路径/health-log-wheels
```

`--offline` 不联系包索引；缺包会明确失败，不静默切回联网。没有任何本地 wheel 时，
仅靠空的 `.venv` 无法完成安装。Linux 若缺 `venv`/`ensurepip`，需要系统提供的
`python3-venv` 包；引导脚本不会擅自安装系统软件。

`--dev` 的离线 wheelhouse 还需包含 `pyproject.toml` 中 dev 组的全部依赖。构建 wheel/sdist
另有 `[build-system]` 的后端依赖；运行 `python -m build` 默认创建构建隔离环境并可能联网，
不能把“bootstrap 离线成功”当成“离线构建一定可用”。通常使用源码入口即可，无需构建包。
常规联网安装可复用 pip 缓存，但仍可能访问包索引；缓存不是保证离线安装成功的 wheelhouse。

## 换电脑与完整备份

1. 停止写入并运行 `python3 scripts/hl.py check`。整体复制这个私有项目，包括程序、个人规则、
   配置、记录和所有隐藏文件，尤其是 `.hl/secret`、收据、manifest 与缓存。只复制 `log/` 或 Git 跟踪文件不够。
   公共模板默认忽略个人数据，私有仓库也不会自动跟踪；用户按[发布说明](publication.md#保存自己的项目)
   选择自己的 Git 跟踪方式后，仍需完整备份 `.hl` 等未跟踪内容。
2. `.venv` 可以不搬；它带有旧机器路径和平台文件，在新电脑的项目根目录重新运行 bootstrap。
3. 运行 `python3 scripts/hl.py check`、`doctor` 和 `recent`，核对成功后再继续。新 AI 仍只需打开这一个目录。
4. 缺密钥、坏签名或不支持的格式不能靠重新 init、重签或删除历史解决，按[恢复说明](migration.md)处理。

已复制坏 `.venv` 时，先确认路径确是本项目的运行环境，再将它移走并重建。**`.hl` 不能删除**。

## 只更新程序，保留个人内容

升级前完整备份。按新版本 `pyproject.toml` 的公开程序允许清单更新 `src/hl`、`scripts`、文档、
依赖声明和可分发运行资源，再运行 bootstrap、check 和 doctor；不把新版目录整体覆盖或镜像删除到自己的项目。

必须保留 `hl.toml`、`log/`、`plan.yaml`、`defaults.yaml`、个人 `foods/`、`.hl/` 和全部个人规则。
根 `AGENTS.md`、已有 `HEALTH_LOG_V2.md`、`CLAUDE.md` 及其他个人指南先比较并合并适用规则，
不能用公共模板直接覆盖。`data/foods/raw`、`compiled` 的私有完整数据也保留，不因公开新版未带它们而删除。
格式迁移是另一步显式操作；bootstrap 和程序文件更新都不会代替它。

开发环境可运行 `python3 scripts/bootstrap.py --dev` 安装本项目开发依赖，仍只使用 `.venv`。
公开副本不包含私有测试套件，不能把缺少测试文件称为业务回归通过。

## 入口的边界

- `scripts/runtime.py` 唯一负责本地解释器和依赖检查；两个脚本不各自维护一套选择策略。
- `scripts/bootstrap.py` 只准备运行环境，不安装全局命令、不设置 Git、不下载食物、不写账本。
- `scripts/hl.py` 默认绑定本项目根账本，只分发到当前源码 `src/hl`，不寻找全局 `hl`；缺依赖返回 JSON 错误，
  明确要求运行 bootstrap。读取命令不会突然联网安装软件。
- 业务写入、校验、日期、事务和迁移仍由引擎负责。脚本不实现第二套业务规则。
