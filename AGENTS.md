# health-log 工程协作

这是程序源码，不是个人账本。先读 `docs/architecture.md`、`CONTRIBUTING.md` 和
`docs/publication.md`。日常记账应读个人账本的 `HEALTH_LOG_V2.md`（如果存在），否则读其 `AGENTS.md`。
旧语言写协议已退役，不得复活第二套语言裁决服务。

- 统一日常写服务在 intents；营养数据在 foods；完整性在 ledgercheck/manifests；
  多文件写入必须走 storage.transactions，读写持有同一把锁，所有更正需版本校验。
- Agent 负责语义理解，原话来源等级必须诚实，不用词面规则假装证明语义。
- 正式个人账本和全局安装 `hl` 不在工程验证范围，只用明确的临时隔离账本。
  不把个人数据用于验证，不擅自同步账本、改变仓库可见性或公开私有开发历史。
- 不启动 Docker Desktop/容器引擎，不打开用户桌面应用来凑测试平台。
- 新测试断言实际日期/餐次/数量/未改项目/估算与失败回滚；不能只断言 check 成功。
- 基本验证：`python3 scripts/bootstrap.py --dev`，`.venv/bin/ruff check src scripts`，
  `python3 scripts/hl.py --help`，`.venv/bin/python -m build`。重大节点留明证据和未测边界。
- 私有开发副本若包含 `tests/`，另运行 `.venv/bin/python -m pytest -q` 和测试代码静态检查。
  公开副本不含测试套件，不能把缺失测试称为通过。已有私有证据、规则和历史必须保留，不能覆盖清理。
  私有治理文件不因分发整理而改写；当前用户需求优先于历史产品设计。
- 公开分发按 pyproject.toml 允许清单，不含测试、审查过程、个人账本、凭据或旧 Git 历史。
  `data/foods/raw`、`data/foods/compiled` 是私有工程保存的第三方完整数据，公开只带其 README 和 manifest。
- 日常用户 Agent 规则维护 `src/hl/data/templates/AGENTS.md`，不要把工程实现细节塞进用户反馈。
