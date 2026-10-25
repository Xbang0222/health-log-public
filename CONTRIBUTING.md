# 参与开发

先阅读[项目架构](docs/architecture.md)和[AI 接入指南](docs/agent-integration.md)。
根目录 `AGENTS.md` 按用户任务引导日常记录或开发，`HEALTH_LOG_V2.md` 是完整操作契约。
私有仓库同时保存程序、食品数据、账本、个人规则和开发材料；无需另建一个日常项目。
用户明确要求开发时使用本页的工程约定；不要把日常用户带入开发流程。

## 给开发 Agent 的边界

- `intents` 是唯一日常写服务，`foods` 管营养，`ledgercheck/manifests` 管完整性。
  多文件写入走 `storage.transactions`，读写同锁，更正必须校验版本。
- 正式个人账本只用于用户明确要求的使用或部署，不能拿它做工程测试。
  所有回归使用临时隔离账本和合成数据；不修改全局 `hl`。
  正式账本就在本仓库根，测试不能直接调用默认指向本根的启动脚本写入。
- 不启动 Docker Desktop，不打开桌面应用凑测试平台，不擅自改变远端可见性或上传个人数据。
- 保留私有开发历史、原有证据和个人规则。私有治理文件不自动改写；当前用户需求优先于旧产品设计。
- 新验证断言实际日期、餐次、数量、未改项目、估算与失败回滚，不只断言 `check` 成功。
- 私有工作副本含 `tests/` 时运行 `.venv/bin/python -m pytest -q` 与测试静态检查；
  公开副本没有测试套件，不能把缺失测试报成通过。

## 准备环境

需要 Python 3.11 或更新版本的 macOS / Linux；原生 Windows 目前不支持文件锁。
从源码目录运行：

```sh
python3 scripts/bootstrap.py --dev
.venv/bin/ruff check src scripts
python3 scripts/hl.py --help
.venv/bin/python -m build
```

依赖安装在本项目 `.venv`，不要求全局 `hl`、uv 或 Git hooks。Linux 和 Windows/WSL 的具体环境说明见
[安装文档](docs/portable-install.md)。以上是静态检查、入口与打包步骤，不代表完成业务回归。

完整自动化测试、测试夹具、模型对话与审查过程保留在维护者的私有开发环境，公开分发不含这些材料。
`--dev` 仍包含维护者使用的 pytest 等依赖。公开下载者不会因此获得私有测试套件，
也不应把“没有测试文件”误报成“测试全部通过”。有私有工作副本的维护者按其本地配置运行回归。

## 修改原则

- 日常新增、更正、删除和设置统一走 `intents`，不要恢复已退役的旧语言写协议。
- 自然语言理解交给 AI；引擎维护结构、数值、来源诚实性、版本、幂等、事务和完整性。
- 每个模块保持单一职责，命令层调用共享服务，不相互调用另一条命令。
- 多文件写入走 `storage.transactions`，更正先读取当前版本，失败后不留下半份记录。
- 修改用户体验时同步维护 `src/hl/data/templates/AGENTS.md` 和相关用户文档。
  `init` 不覆盖已有个人指南，更新程序后需要按用户原规则合并新说明。
- 不用真实饮食或财务数据测试，不把凭据、个人规则、缓存、机器路径或模型对话放进公开补丁。

提交问题时附最小虚构示例、运行环境、预期与实际结果；删去个人记录、API 密钥、
账本 `.hl/secret` 和完整工具日志。不要把签名密钥当作普通调试附件。

## 分发前

源代码包使用明确允许清单；wheel 只包含 `src/hl` 运行代码和资源。
私有工程的完整食品数据位于 `data/foods/raw` 和 `compiled`，公开分发仅允许对应 README 和 manifest；
数据处理与离线重建步骤见[项目数据说明](data/foods/README.md)。
公开源码用 `python3 scripts/export_public.py /新的导出目录` 生成，再核对实际构建产物。
根 `.gitignore` 用于私有项目；导出和源码包使用公共忽略规则，防止新用户误提交个人记录。
通用 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 与 README 可公开，个人偏好放在不导出的
`PERSONAL_RULES.md`。不能只看 `.gitignore`、沿用旧包或直接复制私有 Git 历史。
详细边界见[项目与发布说明](docs/publication.md)。
