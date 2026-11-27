# 输出放哪：work（现行）/ print + out（旧批次）

## 一句话规则

**新单一律进 `work/`**，目录树、命名与 manifest 以 [folder-layout.md](../.qoder/skills/3d-mold-maker/references/folder-layout.md) 为唯一事实来源；**历史批次仍留在 `print/`（可打印件）+ `out/`（记录）**，脚本与 `PRINT.md` 继续兼容。

## 现行：work/

```
work/
├─ _inbox/<批次名>/                收件箱（只读，复制不移动）
├─ 打样/<项目名>/{原始图,打印模型,_记录}
├─ 订单/<YYYYMMDD>/<订单号>/...    多款式时加一层 <款式>
├─ _实验/                          探针、对比、print/test
└─ _归档/                          历史件、_archive、无法归类件
```

- `打印模型/` 只放 `base.stl`、`cutter.stl`、`plate.stl`（印章；`plate` = 两件同一文件）或 `outline.stl`、`lid.stl`（宠物浮雕）。
- 报告、`preview.png`、`model.html`、`frame_check.png`、`validation.json` 等进同级 `_记录/`。
- 归类用 `workspace.py`：`plan`（只读）→ `apply`（复制原图）→ 预览 → `collect`（收 STL 与记录）。
- `work/` 已 gitignore；交付件不进 git。

## 旧批次：print/ + out/

```
print/standard/                    定稿手柄：单个 / x6 / x12
print/jobs/<job>/                  单套：base.stl + cutter.stl + plate.stl（底模套边框合盘）
print/jobs/<批次>/<单号>/          批量：同样 base + cutter 同目录
print/test/                        试打、层高对比、参数实验
out/<job>/                         report / preview / model.html / lines.svg / MANIFEST
out/<批次>/<单号>/                 批量记录
out/<批次>/INDEX.md + batch.json   批次总表与机器读结果
out/handles/                       手柄体检图与对比记录
out/_archive/                      淘汰件留档
```

| 抽屉 | 含义 | 生命周期 | 谁往里写 |
|---|---|---|---|
| `print/standard/` | 定稿标准件，一套配所有图案 | 长期；换尺寸才重做 | `src/make_handle.py` |
| `print/jobs/<job>/` | 这一单的模具，跟图案绑定 | 单次；换图必须重做 | `stamp_pipeline.py`；批量 `batch_molds.py` |
| `print/test/` | 试打、层高对比、参数实验 | 临时；可整目录删 | `src/tools/` 等 |

判断“该不该保留”只看一条：**跟图案走的（jobs）、跟标准走的（standard）、还是只试一下（test）**。

## 预览与 model.html（按工具分口径）

- `stamp_pipeline.py` 自动出 `preview.png`、`report.json`、`MANIFEST.md`，**不出 `model.html`**。
- 单套要 3D HTML 时，另跑 `src/viewer/make_viewer.py`：

```powershell
python src\viewer\make_viewer.py --stl print\jobs\bakers_v6\base.stl --cutter print\jobs\bakers_v6\cutter.stl `
  --handle print\standard\handle_straight.stl --report out\bakers_v6\report.json `
  --out out\bakers_v6\model.html
```

- `batch_molds.py` 默认每套自动生成 `model.html`；只有 `--no-html` 才跳过。
- 新 `work/` 单：把 HTML 输出到该件 `_记录` 下的 `model.html`，再跑 `workspace.py collect` 收件。

## 批量：多一级批次，配对不变

```
print/jobs/<批次>/<单号>/{base,cutter}.stl
out/<批次>/<单号>/…  +  out/<批次>/INDEX.md、batch.json
```

`<批次>` 是 `日期_主题_数量` 形式的纯 ASCII 名，`<单号>` 是图案 slug。**底模和边框永远同目录**，跨套不会混。批量跑完后用 `workspace.py collect` 收进 `work/订单`；清单格式、命名、并行参数与性能见 [batch.md](batch.md)。

## 命名规则（脚本自动保证，别手改）

| 文件 | 含义 | 谁生成 |
|---|---|---|
| `jobs/<job>/base.stl` | 底模 / 凹模 | `stamp_pipeline.py` |
| `jobs/<job>/cutter.stl` | 边框 | 同上（`--no-cutter` 时不出） |
| `jobs/<job>/plate.stl` | 合盘：底模同心套在边框内腔、同一 STL（两件独立） | 同上（`--no-cutter` 时不出） |
| `jobs/<批次>/<单号>/{base,cutter}.stl` | 批量时的同一对 | `batch_molds.py` |
| `print/standard/handle_straight.stl` | 手柄单个（定稿） | `make_handle.py` |
| `print/standard/handle_straight_x6.stl` / `_x12.stl` | 手柄联排 | `make_handle.py --count 6 / 12` |
| `test/<组名>/<任意>.stl` | 试打件 | `tools/` 下的脚本或手放 |

`<job>` 就是 `--out` 的最后一段目录名（`out\bakers_v6` → `out/bakers_v6`、件在 `print/jobs/bakers_v6/`）。批量时 `<job>` 是 `<批次>/<单号>`，两级一起构成 job 名——配对不靠文件名。

## PRINT.md 的覆盖范围

- 由 `src/make_print_index.py` 扫描 `print/` 三档生成，**不要手改**；只覆盖旧批次。
- 单独检查：`python src\make_print_index.py --check`，退出码 0 = 旧批次全部可打。
- 报的问题分四类：读不出来、非水密、`jobs/<job>` 只有底模没边框、文件名不合约定。
- **`work/` 订单不在 `PRINT.md` 内**；验收读各件 `_记录` 里的 `report.json`（宠物读 `validation.json`）。

## 淘汰与归档

- 旧批次淘汰件挪到 `out/_archive/`，只留档、不打印；原因写进 `CHANGELOG.md`。
- 新单历史件进 `work/_归档/`；迁移只复制、不删旧件，映射见 folder-layout。
- 真正删除要用户点头——脚本和 Agent 都不会自己删。

## 老写法兼容

- `--out out\bakers_v6` → 目录 `out/bakers_v6`
- `--out out\bakers_v6.stl` → 也认，按 `bakers_v6` 处理
- 旧布局的 `print\<job>_base.stl` 已迁到 `print/jobs/<job>/base.stl`
- 换打印根目录用 `--print-dir <目录>`，仍沿用 `jobs/<job>/` 子结构
