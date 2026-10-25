# 安装、换电脑与离线使用

引擎支持 Python 3.11 及更新版本的 macOS / Linux。Windows 需在 WSL 的 Linux 环境使用；
原生 Windows 尚不支持文件锁。本地运行验证覆盖 macOS 上的 Python 3.11–3.14；
Linux 和 WSL 是适用环境，当前维护记录没有实际 Linux/WSL 运行结果，不把未测系统列作通过。

## 最短路径

把项目源码目录放到电脑上，解压下载的源码也可以，不要求安装 Git。在源码目录运行：

```sh
python3 scripts/bootstrap.py
python3 scripts/hl.py --data ~/health-data init
python3 scripts/hl.py --data ~/health-data foods fetch
python3 scripts/hl.py --data ~/health-data doctor
```

第一条在源码内创建 `.venv`，只安装该项目依赖。后续入口自动选择它，不必激活环境、
安装 uv、修改 PATH 或安装全局 `hl`。重复运行 bootstrap 只补缺失或版本不满足的依赖；
不改账本。依赖声明只有 `pyproject.toml` 一份。

开发者运行 `python3 scripts/bootstrap.py --dev`，同时安装 `dependency-groups.dev` 中的
测试、lint 和构建工具；仍只写本地 `.venv`，也可与 `--offline --wheelhouse` 一起使用。

`--data` 必须指向你选定的**持久数据目录**。`~/health-data` 只是示例：云电脑的 home
也可能随实例销毁，须先确认服务商的持久磁盘/挂载目录，把该目录填进去。引擎无法替你
证明云盘会保留。不要把 `/tmp`、下载缓存或一次性 Agent 工作区当正式账本。

源码与账本可以分开；从任意目录都可使用源码入口的绝对路径：

```sh
python3 /完整路径/health-log/scripts/hl.py --data /持久路径/health-data today
```

`--data` 优先于 `HL_DATA`，没有显式指定时引擎仍可从当前目录向上查找 `hl.toml`。
选择账本不会替 Agent 加载规则：让 Agent 优先读取账本 `HEALTH_LOG_V2.md`（如果存在），
否则读取账本 `AGENTS.md`，再使用上述入口。详情见[AI 接入指南](agent-integration.md)。
正常结构化写入不依赖 Codex/Claude hooks、宿主信任注册或全局配置；可选 hooks 用于
采集宿主原话等增强能力，未启用时来源只能称为 Agent 提交。

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

## 搬家与备份

1. 停止写入，整体复制账本目录，包括所有隐藏文件。尤其保留 `.hl/secret`、审计记录、
   manifest 和缓存；只复制 `log/` 或 Git 仓库是不完整的。
2. 把源码复制或重新解压到新电脑。**不迁移源码的 `.venv`**，它包含旧机器路径和平台
   二进制；在新电脑重新运行 bootstrap。
3. 用新电脑的持久路径运行 `--data <账本> check` 和 `doctor`，先确认完整性再记账。
   缺密钥、损坏签名或不支持的版本不能靠重新 `init`、重签或删除历史解决，应从备份恢复。
4. 旧版本账本按本次迁移说明先预检、备份，再执行显式迁移；引导脚本不迁移健康数据。

已复制坏 `.venv` 时，入口会报运行环境不可用，避免偷偷使用全局旧 `hl`。确认路径是
**源码目录里的 `.venv`** 后，把它移走并重跑 bootstrap。账本中的 **`.hl` 不能删除**。

## 入口的边界

- `scripts/runtime.py` 唯一负责本地解释器和依赖检查；两个脚本不各自维护一套选择策略。
- `scripts/bootstrap.py` 只准备运行环境，不安装全局命令、不设置 Git、不下载食物、不写账本。
- `scripts/hl.py` 只分发到当前源码 `src/hl`，不去寻找全局 `hl`；缺依赖返回 JSON 错误，
  明确要求运行 bootstrap。读取命令不会突然联网安装软件。
- 业务写入、校验、日期、事务和迁移仍由引擎负责。脚本不实现第二套业务规则。
