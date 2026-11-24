# 输出放哪：print/ 与 out/<图案>/

## 一句话规则

**能直接丢进切片器的 `.stl` 全在 `print/`；其余（预览、报告、SVG、清单）在 `out/<图案>/`。**
不用挑文件：`print/` 里每一个都可以直接打。

## 目录长这样

```
3D-stamp-print/
├─ print/                       ← ★ 唯一"拿去打印"的地方，只放 .stl
│   ├─ bakers_v3_base.stl         底模（带浮雕，压图案）
│   ├─ bakers_v3_cutter.stl       边框（独立切模，切粘土外形）
│   ├─ handle_slim.stl            手柄 1 个（试打 / 补件）
│   ├─ handle_x6.stl              手柄 6 个一排（124×14）
│   └─ handle_x12.stl             手柄 12 个一盘（124×36）
├─ out/
│   ├─ bakers_v3/                ← 这一次运行的全部记录
│   │   ├─ MANIFEST.md            这批出了哪些文件、哪个能打（自动生成）
│   │   ├─ report.json            几何体检：尺寸/面数/水密/线宽/边框参数
│   │   ├─ preview.png            三栏预览（镜像实物 / 压印效果 / 半剖）
│   │   ├─ model.html             单文件 3D 预览，双击即开
│   │   ├─ lines.svg              分层 SVG（底面/图案分开，可手改）
│   │   └─ shot_*.png             几张开好的视角截图（默认/装配/侧视/背面）
│   ├─ handles/                 手柄体检 json + 联排俯视图
│   └─ _archive/                淘汰件留档（v2 那批、旧的 85mm 版），别拿去打
├─ PRINT.md                     ← 打印总表（自动生成，跨所有图案）
├─ make_print_index.py          扫 print/ 生成 PRINT.md
└─ guides/ parts.md printing.md output-layout.md
```

## 命名规则（脚本自动保证，别手改文件名）

| 文件名 | 含义 | 谁生成 |
|---|---|---|
| `<图案>_base.stl` | 底模 | `stamp_pipeline.py --out out\<图案>` |
| `<图案>_cutter.stl` | 边框 | 同上（`--no-cutter` 时不出） |
| `handle_slim.stl` | 手柄单个 | `make_handle.py` |
| `handle_x6.stl` / `handle_x12.stl` | 手柄联排 | `make_handle.py --count 6 / 12` |

`<图案>` 就是你给 `--out` 起的名字（`out\bakers_v3` → `bakers_v3`）。换新图案就换个名字，老的不会被覆盖。

## 每次运行留下什么

一条命令下去，同时写两处：

```powershell
python stamp_pipeline.py --input inputs\bakers_framed.png --out out\bakers_v3 --size 85 --relief 1.8
```

- `print/bakers_v3_base.stl`、`print/bakers_v3_cutter.stl` → **可打印**
- `out/bakers_v3/` 里的 report / preview / lines.svg / MANIFEST.md → **只给人看**

跑完会自动刷新根目录 `PRINT.md`（跨图案总表），以及该图案自己的 `MANIFEST.md`。

## PRINT.md 是自动的

- 由 `make_print_index.py` 扫描 `print/` 生成，**不要手改**；重出件后自动重算。
- 想单独检查一下就 `python make_print_index.py --check`：退出码 0 = 全部可打。
- 它会主动报三类问题：命名不符合约定、网格非水密、只有底模没有边框（是不是用了 `--no-cutter`）。

## 淘汰与归档（不删）

被新版本取代的成品挪到 `out/_archive/`，只留档、不打印。归档原因写进 `CHANGELOG.md`。
真正删除要你点头——脚本和 Agent 都不会自己删。

## 老写法兼容

以前 `--out out\bakers` 会生成 `out\bakers.stl` 这种平铺文件。现在 `--out` 一律当**图案目录名**处理：

- `--out out\bakers_v3` → 目录 `out/bakers_v3`
- `--out out\bakers_v3.stl` → 也认，按 `bakers_v3` 处理（老命令行不用改）

可打印件的落点是 `print/<图案>_base.stl`，不再跟着 `--out` 走；要换位置用 `--print-dir <目录>`。
