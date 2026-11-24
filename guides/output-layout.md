# 输出放哪：src / print / out

## 一句话规则

**脚本全在 `src/`；能直接丢进切片器的 `.stl` 全在 `print/`（分 standard / jobs / test 三档）；其余记录在 `out/<job>/`。**

## 目录长这样

```
3D-stamp-print/
├─ src/                          ← 所有代码，和产出彻底分开
│   ├─ stamp_pipeline.py           线稿 → 底模 + 边框 + 清单 + 预览
│   ├─ make_handle.py              手柄（标准件）
│   ├─ make_print_index.py         扫 print/ 生成 PRINT.md
│   ├─ viewer/                     make_viewer.py（单文件 3D）+ libs/
│   └─ tools/                      handle_layer_test.py（层高对比）・preview_handle_batch.py（排布图）
├─ print/                        ← ★ 唯一"拿去打印"的地方，只放 .stl
│   ├─ standard/                   定稿、可复用、不跟单走
│   │   ├─ handle_slim.stl            手柄 1 个（补件 / 试打）
│   │   ├─ handle_x6.stl              手柄 6 个一排（124×14）
│   │   └─ handle_x12.stl             手柄 12 个一盘（124×36）
│   ├─ jobs/                       一单一个目录，删单就删目录
│   │   ├─ bakers_v3/
│   │   │   ├─ base.stl               底模（凸模压图案）
│   │   │   └─ cutter.stl             边框
│   │   └─ bakers_cav/
│   │       ├─ base.stl               凹模（刻图案，成品凸起）
│   │       └─ cutter.stl
│   └─ test/                       试打、对比、实验件，随时可删
│       └─ handle_layer/layer_3.stl   层高对比件（三个手柄一排）
├─ out/
│   ├─ <job>/                    每次运行的全部记录
│   │   ├─ MANIFEST.md             这一单出了什么、哪个能打（自动生成）
│   │   ├─ report.json             几何体检：尺寸/面数/水密/线宽/边框参数
│   │   ├─ preview.png             三栏预览（实物 / 压印效果 / 剖面）
│   │   ├─ model.html              单文件 3D 预览，双击即开
│   │   ├─ lines.svg               分层 SVG（--svg 才有）
│   │   └─ shot_*.png              视角截图（视口调试后留存）
│   ├─ handles/                  手柄体检 json + 联排俯视图 + layer_test.md
│   └─ _archive/                 淘汰件留档，别拿去打
├─ inputs/                      源图
├─ guides/                      parts / cavity / printing / output-layout
├─ PRINT.md                     ← 打印总表（自动生成）
└─ README.md · CHANGELOG.md
```

## 三档的分界（为什么要这么分）

| 抽屉 | 含义 | 生命周期 | 谁往里写 |
|---|---|---|---|
| `print/standard/` | 定稿的标准件，一套配所有图案 | 长期；换尺寸才重做 | `src/make_handle.py` |
| `print/jobs/<job>/` | 这一单的模具，跟图案绑定 | 单次；换图必须重做 | `src/stamp_pipeline.py --out out\<job>` |
| `print/test/` | 试打、层高对比、参数实验 | 临时；可以整目录删 | `src/tools/handle_layer_test.py` 等 |

判断"这文件该不该保留"只看一条：**它是跟图案走的（jobs），还是跟模具标准走的（standard），还是只是试一下（test）**。

## 命名规则（脚本自动保证，别手改）

| 文件 | 含义 | 谁生成 |
|---|---|---|
| `jobs/<job>/base.stl` | 底模 / 凹模 | `stamp_pipeline.py --out out\<job>` |
| `jobs/<job>/cutter.stl` | 边框 | 同上（`--no-cutter` 时不出） |
| `standard/handle_slim.stl` | 手柄单个 | `make_handle.py` |
| `standard/handle_x6.stl` / `handle_x12.stl` | 手柄联排 | `make_handle.py --count 6 / 12` |
| `test/<组名>/<任意>.stl` | 试打件 | `tools/` 下的脚本或你手放 |

`<job>` 就是你给 `--out` 起的名字（`out\bakers_v3` → 目录 `out/bakers_v3`、件在 `print/jobs/bakers_v3/`）。换新图案就换个名字，老的不覆盖。

## 每次运行留下什么

```powershell
python src\stamp_pipeline.py --input inputs\bakers_framed.png --out out\bakers_v3 --size 85 --relief 1.8
```

- `print/jobs/bakers_v3/base.stl`、`print/jobs/bakers_v3/cutter.stl` → **可打印**
- `out/bakers_v3/` 里的 report / preview / lines.svg / MANIFEST.md → **只给人看**

跑完自动刷新根目录 `PRINT.md` 与该单的 `MANIFEST.md`。

## PRINT.md 是自动的

- 由 `src/make_print_index.py` 扫描 `print/` 三档生成，**不要手改**；重出件后自动重算。
- 单独检查：`python src\make_print_index.py --check`，退出码 0 = 全部可打。
- 报的问题分四类：读不出来、非水密、`jobs/<job>` 只有底模没边框、文件名不合约定。

## 淘汰与归档（不删）

被新版取代的成品挪到 `out/_archive/`，只留档、不打印；归档原因写进 `CHANGELOG.md`。真正删除要你点头——脚本和 Agent 都不会自己删。

## 老写法兼容

- `--out out\bakers_v3` → 目录 `out/bakers_v3`
- `--out out\bakers_v3.stl` → 也认，按 `bakers_v3` 处理（老命令行不用改）
- 旧布局的 `print\<job>_base.stl` 已迁到 `print/jobs/<job>/base.stl`；脚本不再往 `print/` 根写件
- 要换打印根目录用 `--print-dir <目录>`，仍然沿用 `jobs/<job>/` 的子结构
