# 固定版本食品基础数据

这里保存项目已经下载、整理和核对过的两份食品基础库，方便在私有开发副本中离线重建。
它们是通用食品数据，不包含个人饮食、体重、目标、用户食品标签、账本配置、签名密钥或操作历史。

原始数据和整理表仅在私有 Git 仓库保存；公开程序可提供本说明和 `manifest.json`，不包含
`raw/`、`compiled/` 的完整第三方数据。公开下载者取得的清单不是数据文件本身。

## 数据内容

| 来源 | 原始数据 | 整理后运行表 |
| --- | --- | --- |
| 中国食物成分表第 6 版数据副本 | `raw/cn6/`：61 个食品 JSON、1 个整理说明 JSON；1677 条食品，1,378,452 字节 | `compiled/cn6.json`：1677 条，353,742 字节 |
| 薄荷食品库数据副本 | `raw/boohee/all.csv` 与 `food_detail_backup.json`：各 8140 条、按食品编号配对；共 18,729,737 字节 | `compiled/boohee.json`：8106 条，2,532,167 字节 |

两份整理表合计 9783 条、2,885,909 字节。CSV 和详情中的同一食品不能重复算成两条。
CN6 的 `enrich_log.json` 是上游整理说明，不计入食品记录。

固定来源：

- CN6：[`Sanotsu/china-food-composition-data`](https://github.com/Sanotsu/china-food-composition-data/tree/d15675c27582748307023b7ee7aca2a63fc52756)，
  提交 `d15675c27582748307023b7ee7aca2a63fc52756`，数据目录 `json_data_v3_20260825_qwen38max_kimi_k3_fixed_en`。
- 薄荷：[`jarheadjoe/scrapy_boohee`](https://github.com/jarheadjoe/scrapy_boohee/tree/a64c26df9aba061b0983f4d19fab8945c532ba6b)，
  提交 `a64c26df9aba061b0983f4d19fab8945c532ba6b`，使用仓库根目录的上述 CSV 和详情 JSON。

原始文件按下载时的字节保留；整理表来自既有 `foods` 转换器，不是新增食品协议。
转换器源码提交是 `3cb61b63a336d584cb4e9d628ab30c87620e27b8`。
对应的[公开源码提交](https://github.com/Xbang0222/health-log-public/tree/4c33ddbf21163ac5254405c261aceda48021281c)
是 `4c33ddbf21163ac5254405c261aceda48021281c`；清单列出的转换器文件已逐字节核对一致。
[manifest.json](manifest.json) 记录每个原始/整理数据文件的相对路径、字节数、SHA-256、条数和质量处理统计。
每份原始库的聚合哈希与 `hl foods fetch` 相同：按文件名排序，将每个文件写为
`SHA256`、两个空格、文件名、换行，再对整个 UTF-8 字节序列取 SHA-256。
清单不包含机器绝对路径或个人配置；转换器文件路径相对于程序根目录，其余数据路径相对于本目录。

## 之前整理的自有规则数据

这些内容一直保留在程序的运行资源里，不在本次重新复制的第三方数据目录中：

- [concepts.yaml](../../src/hl/data/concepts.yaml)：129 个日常食物概念、品种、常见量词及换算依据。
- [dishes.yaml](../../src/hl/data/dishes.yaml)：18 道菜谱的份量、原料和估算依据。
- [lookalikes.yaml](../../src/hl/data/lookalikes.yaml)：704 个易混淆食物名称区分项。
- [units.yaml](../../src/hl/data/units.yaml)、[cooking.yaml](../../src/hl/data/cooking.yaml)：单位与做法相关规则。
- [reference.yaml](../../src/hl/data/reference.yaml)：13 项带来源的营养参考；不自动替用户设置目标。

概念和菜谱只描述怎样定位、换算或估算，不能替代逐项食品营养表。

## 使用现有入口离线重建

持有本目录的原始数据、并已准备 Python 和项目依赖时，在程序根目录执行。
把示例中的账本路径换成自己的私人持久目录；新账本先初始化，已有账本不需要重新建立：

```sh
python3 scripts/hl.py --data /私有持久目录/health-data init
python3 scripts/hl.py --data /私有持久目录/health-data foods build data/foods/raw/cn6
python3 scripts/hl.py --data /私有持久目录/health-data foods build data/foods/raw/boohee
python3 scripts/hl.py --data /私有持久目录/health-data check
```

两个 `foods build` 分别识别成分表目录和薄荷目录，读取本地文件，无需联网下载；
它们把整理结果安装到所选账本的 `.hl`，同时更新该账本的食品哈希和原始数据路径。
不必新增运行协议，也不要手工改账本哈希、替换密钥或把整个开发目录复制成个人账本。
原始目录之后应保留在可访问的位置，便于按诊断重建。

使用上述固定来源和转换器时，重建结果应与本目录 `compiled/` 两文件逐字节一致：

| 文件 | SHA-256 |
| --- | --- |
| `compiled/cn6.json` | `3872b537c028cd79acf1e264e3693d42162bef97573296e0d5aac990b67a52ef` |
| `compiled/boohee.json` | `75c270117d6c2d2d3c9cda716288af2cc9ea5f061de21b014c2450d5b559fb7e` |

## 质量与未知值

CN6 的 1 条记录原始热量有数、三大营养素全未知，现有转换器把该条热量保留为未知。
薄荷原始 8140 条中，34 条因热量与宏量营养不自洽而排除，收录 8106 条；重名的 19 组、38 条仍保留。
量词整理收下 1052 个，不能可靠解析或克数冲突的量词不采用。完整统计见清单的 `quality`。

缺失营养保持 `null`，不是零；原始 `Tr` 按微量处理并保留 `trace` 标记。
薄荷数据、菜谱与模型估算继续使用原有来源和估算标记；常见份量换算不是用户实际称重。
基础库有多少条，也不能证明用户某餐一定匹配准确。

## 来源条款与分发边界

工程自身的源码、概念表和菜谱组织遵循项目 MIT 许可证；MIT 不会替第三方食品数据赋予许可。

- CN6 的[固定版本上游说明](https://github.com/Sanotsu/china-food-composition-data/blob/d15675c27582748307023b7ee7aca2a63fc52756/README.md)
  声明内容版权归原作者，脚本供个人学习研究；该版本没有独立 LICENSE、COPYING 或 NOTICE 文件，
  未给出全库明确的通用再分发授权。
- 薄荷整理项目的[固定版本上游说明](https://github.com/jarheadjoe/scrapy_boohee/blob/a64c26df9aba061b0983f4d19fab8945c532ba6b/README.md)
  虽提到 GPL-3.0，同时另有非商用、禁止公众号/自媒体转载、下载后 24 小时删除等限制，并称特别声明优先；
  该版本没有独立许可文件，不能将它标成已取得统一通用再分发许可的食品库。

因此，本目录不宣称两份完整数据都是开源数据，也不将其整体标为 MIT。
完整 `raw/` 与 `compiled/` 只保留在私有开发仓库；公开项目仅保留来源、清单、说明和原有下载/构建能力。
未来如取得可核实的不同授权，再单独调整对应数据的分发范围。
