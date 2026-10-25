# 参与开发

先阅读[项目架构](docs/architecture.md)和[AI 接入指南](docs/agent-integration.md)。
源码目录 `AGENTS.md` 约定工程边界，账本内的 Agent 指南约定日常使用；二者不能混用。

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
- 不用真实饮食或财务数据测试，不把凭据、个人规则、缓存、机器路径或模型对话放进公开补丁。

提交问题时附最小虚构示例、运行环境、预期与实际结果；删去个人记录、API 密钥、
账本 `.hl/secret` 和完整工具日志。不要把签名密钥当作普通调试附件。

## 分发前

源代码包使用明确允许清单；wheel 只包含 `src/hl` 运行代码和资源。
私有工程的完整食品数据位于 `data/foods/raw` 和 `compiled`，公开分发仅允许对应 README 和 manifest；
数据处理与离线重建步骤见[项目数据说明](data/foods/README.md)。
分别核对实际构建产物，不能只看 `.gitignore`，也不能沿用过去的旧包。
公开源码快照必须来自审阅后的文件清单，不能包含私有 Git 历史。
详细边界见[项目与发布说明](docs/publication.md)。
