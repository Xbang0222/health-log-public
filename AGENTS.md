# health-log 日常使用入口

这是可以独立使用的私人健康记录项目：程序、食品数据和个人账本都在这个目录内。
除非用户明确要求开发程序，否则按日常记录任务处理，不修改实现代码。

## 开始或接手

1. 所有日常工具使用本项目 `python3 scripts/hl.py`。入口默认绑定脚本所属项目，
   不受调用目录或继承的 `HL_DATA` 影响；无需另一个程序目录、全局 `hl` 或 hooks。
   从别处调用时使用本项目脚本的绝对路径。只有用户明确选择外部账本才使用 `--data`。
2. 先读本目录 `HEALTH_LOG_V2.md`；没有时读 `src/hl/data/templates/AGENTS.md` 了解操作契约。
   保留原有个人偏好。完整协议由模板维护，根文件只负责引导。
3. 缺少运行依赖时执行 `python3 scripts/bootstrap.py`；它只准备项目 `.venv`。
   真正的新项目用 `python3 scripts/hl.py init` 初始化本目录，不另建兄弟目录。
   已有 `log/`、`.hl/` 等账本痕迹但配置丢失时按恢复说明处理，不能当新项目重建。
4. 已有账本先 `doctor`、`check`、`recent`。格式 1 可查询；需要写入时按
   [迁移说明](docs/migration.md)预检、备份后迁移，不能直接改格式号或重新签名。
5. 食品库已有效就继续用。缺少时优先从本项目 `data/foods/raw/cn6`、`data/foods/raw/boohee`
   分别 `foods build`；无本地快照再 `foods fetch`。按[安装说明](docs/portable-install.md)核对后再说就绪。
6. 初次使用简短教用户说“早餐两个鸡蛋”“刚才改成一个”“今天记了什么”；
   不强制收集个人资料或设置目标。老用户直接处理当前请求，不重复教程。

## 日常约定

- 读写通过工具，唯一写入口是 `intent`；不要直接改 `log/`、`foods/`、`.hl/`、计划或配置。
- 只在实际成功后说已记、已改；不编份量，不把未记录说成没吃，不把估算说成实测。
- 项目和个人数据保持私有。不要把本私人项目整体推到公共模板仓库；远端是否可公开不能凭名字猜。
- 更新只覆盖程序清单，保留账本、密钥、设置和个人规则；备份带整个项目及隐藏 `.hl`。
  `.venv` 可在新电脑重建，`.hl` 不能删除。不要自动设置云同步或通知。

用户教程见 [docs/user-guide.md](docs/user-guide.md)。只有用户明确要求开发、改代码或发布时，
再读 [CONTRIBUTING.md](CONTRIBUTING.md)、[架构](docs/architecture.md)和[发布边界](docs/publication.md)。
