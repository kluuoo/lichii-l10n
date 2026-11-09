# Lichii 汉化：审计工具与成品

面向 Lichii（`C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125`）的 Qt 前端，
在没装 Qt Linguist 的机器上完成“字符串抽取 → 缺失统计 → 中文翻译 → 合并 → 校验”的全流程。

## 成品（直接用）

| 文件 | 说明 |
|---|---|
| `zh_CN.ts` | **补译完成的翻译文件**：2316 条消息，0 未完成、0 空译文；覆盖 Lichii 新增的 NUP、兼容性报告、着色器预热、更新器、麦克风、帧生成等全部界面 |
| `zh_CN.patch` | 相对原 `dist/languages/zh_CN.ts` 的 unified diff，可 `git apply` |
| `汉化方案.md` | 完整方案：管线、阻塞点、术语表、分批、验收、落地命令 |

落地：把 `zh_CN.ts` 覆盖到 `<项目>/dist/languages/zh_CN.ts`，构建时加
`-DENABLE_QT_TRANSLATION=ON`（需要 Qt LinguistTools 提供 `lrelease`）。

## 工具链

| 脚本 | 作用 |
|---|---|
| `extract.py` | 近似 `lupdate`：扫描 `src/yuzu`、`src/qt_common`、`src/frontend_common` 的 `.cpp/.h/.ui`，抽取 `tr()` / `QCoreApplication::translate()` / `QT_TRANSLATE_NOOP()` / `.ui` 字符串，与 `zh_CN.ts` 比对 |
| `context_scan.py` | 花括号作用域分析，推断每条 `tr()` 的上下文（函数体 → 类体 → 命名空间），处理 `tr` lambda 与 `translate("Ctx", ...)` |
| `analyze.py` | 批次归类 + “Eden→Lichii” 可继承条目识别（早期版本） |
| `build_queue2.py` | 生成最终待译队列 `queue2.csv` / `order.txt`，上下文经真实声明与原 `.ts` 交叉校准 |
| `tr_a.py` / `tr_b.py` / `tr_c.py` | 357 条人工中文译文（按索引分段） |
| `merge.py` | 校验（占位符、HTML 标签、空值）并合并进 `zh_CN.ts`，补齐 `unfinished` 与损坏旧译文 |
| `verify.py` | 成品校验：覆盖率、`unfinished`、空译文、占位符/标签一致性 |
| `tsstat.py` | 各语言 `.ts` 完成度统计 |
| `ctx_check2.py` / `inspect_ctx*.py` | 上下文排查辅助脚本 |

## 复现

```powershell
$py = "C:\Users\Lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$root = "C:\Users\Lenovo\Downloads\Lichii-build-125\Lichii-build-125"

python -I extract.py $root .      # 生成 missing.csv / unfinished.csv / stale.csv
python -I build_queue2.py         # 生成 queue2.csv / order.txt
python -I merge.py                # 生成 zh_CN.ts
python -I verify.py               # 校验
```

## 数据文件

| 文件 | 说明 |
|---|---|
| `queue2.csv` | 357 条待译清单：索引、批次、文件、行号、上下文、源串 |
| `order.txt` | 同上，便于人工阅读 |
| `missing.csv` / `unfinished.csv` / `stale.csv` | 审计明细 |
| `summary.json` / `stats.json` | 统计 |

## 校验口径

- 覆盖率：harvested 2004 条唯一源串，除 2 条非 UI 文本（上下文名 `ConfigureUI`、`fmt` 模板 `"{} percentage (e.g. 50%)"`）外全部命中；
- 占位符：`%1..%9`、`%L1`、`%n`、`%%` 的多重集合必须一致；
- HTML：标签多重集合必须一致；
- 上下文：必须是工程内真实声明（`class`/`struct`/`namespace`）或原 `.ts` 已有上下文，否则运行时会查询失败、界面仍是英文。

## 已知局限

- 不解析复数形式差异（中文单复数同形，直接写一条 `<numerusform>`）；
- 不做 `lupdate` 的 `location` 行更新（新增条目无 `<location>`，`lupdate` 下次运行会补）；
- 上下文推断基于启发式，已用交叉校验兜底，但改类名后仍需重新跑 `lupdate`。
