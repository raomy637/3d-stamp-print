# OpenSCAD 引擎

> 这份文档解释：为什么把建体从 trimesh 换成 OpenSCAD、两边怎么分工、实测数据、以及踩过的坑。
> 只想知道怎么用，看 README 的 `--engine` 参数即可；批量与整体吞吐看 `batch.md`。

## 一句话

**图案 → OpenSCAD（nightly / Manifold），边框 → trimesh。** 前者吃 2D 轮廓挤出与布尔，后者做等距偏置。

## 为什么不全都交给 OpenSCAD

v11 之前建体走 `shapely 2D 布尔 + trimesh/manifold 3D 并集`。迁到 OpenSCAD 的动机是
借 PJ1（`D:\HA1\PJ1`，名字印章生成器 stampgen）的做法：2D 轮廓给 CGAL，
Python 只管"位图 → 多边形"。收益：

- 参数化模板（`scad/base.scad`），改一个变量就出件，可在 OpenSCAD GUI 里按 F5 预览
- 绕开我们踩过的坑：凹模 sink 模式下图案把顶面切成互不相连的小岛，
  trimesh 的 volume 预检直接失败（当时只能 `check_volume=False` 硬过）
- 网格面数更少（凹模 144.6k → 48.0k 面），切片更快

但边框不能交给它：边框全靠 `offset()` 做墙厚、翼缘、刃口，
OpenSCAD 对一条 2000 点的轮廓反复 offset 实测 **114.7 秒**（2021.01），
trimesh 的同一件只要 **0.50 秒**（229 倍）。所以边框固定走 mesh，与后端快慢无关：
nightly 下 scad 边框只要 0.4s，但**出的网格非水密**，照样不用。

## 实测（本机 i5-13400；nightly 2026.11.23 / Manifold 为默认，2021.01 / CGAL 作对照）

| 件 | 引擎 | 渲染耗时 | 面数 | 体积 | 水密 |
| --- | --- | --- | --- | --- | --- |
| 底模 raise 85mm | nightly Manifold | **1.0s**（进程 14.2s） | 37.9k–39.2k | 18.9 cm³ | ✔ |
| 底模 raise 85mm | 2021.01 CGAL | 19.3s | 37,876 | 18.56 cm³ | ✔ |
| 底模 raise 85mm | mesh | 5.2s（全流程 5.7s） | 56,194 | 18.56 cm³ | ✔ |
| 底模 sink 85mm | nightly Manifold | **1.0s** | 47.9k | 14.90 cm³ | ✔ |
| 底模 sink 85mm | 2021.01 CGAL | 25.6s | 47,980 | 14.90 cm³ | ✔ |
| 底模 sink 85mm | mesh（v10 件） | — | 144,648 | 14.65 cm³ | ✔ |
| 边框 85mm | nightly Manifold | 0.4s | — | — | **✗ 非水密** |
| 边框 85mm | 2021.01 CGAL | 114.7s | — | — | ✔ |
| 边框 85mm | mesh | **0.50s** | 58,930 | 5.62 cm³ | ✔ |
| 手柄 φ10/φ15×25 | 两版都 <1s | — | 1,344 | 2.05 cm³ | ✔ |

- 两个 raise 件的体积在 CGAL 下**完全一致**（18.56），说明 2D 轮廓与挤出高度没有偏差；
  nightly 出 18.9（+1.8%），差在曲面离散，不是几何错。
- sink 与 mesh 差 1.7%，来自拔模近似方式不同（见坑 3）。
- **渲染只是全流程的一部分**：单套 10.3s 里有 4.7s 是 Python 导入、1s 是 OpenSCAD，
  其余是轮廓提取与布尔；40 套并行 96 秒的口径与提速拆解在 `batch.md`。

## 架构

```
位图 ─► mask 清理 ─► shapely 多边形（Python 负责）
                      ├─► geom_to_scad_module()  ─► polygon(points, paths)  ─┐
                      │                                                    ├─► job.scad ─► openscad ─► STL
                      └─► 参数（-D 传入）─────────────────────────────────┘
```

- `src/scad_engine.py`：`geom_to_scad_module`、`write_job_scad`、`render`、`draft_ratio`
- `scad/base.scad`：底模（`mode=raise|sink`、`base_t`、`relief`、`draft_ratio`）
- `scad/cutter.scad`：边框（`--cutter-engine scad` 才用，默认 mesh）
- `scad/handle.scad`：手柄（`rotate_extrude` 转 `profile` 数组）

## 三个坑

**1. 不要用 SVG import，用 polygon() 内联。**
OpenSCAD 2021.01 对多个 SVG 的 y 轴映射不一致：`outline.svg` 落在 y 0..84.2，
`pattern.svg` 落在 y 72.37..168.4（同一份坐标），两件 union 直接错位、
输出 10 个互不相连的壳。polygon() 是纯数值，没有解析歧义。
（单个 SVG 是对的：even-odd 面积核对偏差 0.0%，但多件就崩。）

**2. 参数必须走 `-D`，不能靠 job.scad 里赋值。**
模板里 `mode = is_undef(mode) ? "raise" : mode;` 的写法在 PJ1 里是配 `-D` 用的。
如果在 job.scad 里先写 `mode = "sink";` 再内联模板，OpenSCAD 同作用域"最后赋值优先"，
`is_undef(mode)` 取到的是未定义 → 永远回落默认值（实测 raise/sink 出同一件）。
现在：job.scad 只放 2D 模块与模板正文，所有参数由 `render(defs=...)` 转成 `-D`。

**3. 凹模拔模不要用多层 offset。**
图案 59 条子路径 × 8 段 offset 实测 **>10 分钟没跑完**。改用
`linear_extrude(height, scale=ratio)` 一次成型，23 秒。
`scale` 是整体等比缩放（不是等距偏置），用包围盒半对角折算：
`ratio = 1 + relief*tan(draft)/R`。最远点内缩量等于设计值，
细线宽度变化 <1%。`--cavity-segments` 在 scad 引擎下不起作用（留着是给 mesh 引擎）。

**4. nightly 出的边框网格不水密。**
`--cutter-engine scad` 在 nightly 下 0.4s 就出，但 `is_watertight=False`（0.4mm 薄刃与翼缘相接处有缝）。
mesh 路径 0.5s 且水密，所以边框固定 mesh，不要为了"统一引擎"改回去。

**5. 2021.01 不认 `--enable=fast-csg`。**
传这个参数会直接打 help、退出码非 0。`render()` 已经不加；换版本时别把它加回来。
nightly 也不需要它——Manifold 是默认后端，要退回 CGAL 用 `--backend CGAL`（只在对照时用）。

## 安装

两版并存，`find_openscad()` 的探测顺序是：`OPENSCAD_BIN` → `tools/openscad_nightly/*/openscad.com` → `tools/openscad/`（2021.01）→ PATH。

| 版本 | 放哪 | 说明 |
|---|---|---|
| **nightly（推荐，默认吃这个）** | `tools/openscad_nightly/OpenSCAD-2026.11.23-x86-64/` | 官方只发 nightly；2025-08-18 起 Manifold 是默认后端。解包约 224MB，`.gitignore` 已排除 |
| 2021.01（备选） | `tools/openscad/` | 43MB，老件对照、Manifold 出问题时的退路 |
| 任意位置 | 设 `OPENSCAD_BIN=D:\path\to\openscad.com` | 优先级最高 |
| PATH | 装系统里 | 最后兜底 |

nightly 下载：`https://files.openscad.org/snapshots/OpenSCAD-2026.11.23-x86-64.zip`（约 68MB）。
找不到任何 OpenSCAD 时 `--engine scad` 会**自动回退 mesh** 并打一行日志，不会中断出件。

## 回退与对照

```
python src\stamp_pipeline.py --input 图.png --out out\xxx --engine mesh
```

两个引擎出的件可以直接比：`report.json` 里 `engine` / `scad_render_s` 记录本次走哪条路。

## 加新件

1. 在 `scad/` 下写模板，参数用 `is_undef(x) ? 默认 : x` 声明
2. Python 侧准备 2D 模块：`scad_engine.geom_to_scad_module(geom, "xxx_2d")`
3. `write_job_scad({"xxx_2d": ...}, SCAD_DIR/"xxx.scad", job_dir/"xxx_job.scad")`
4. `render(..., defs={"a": 1.0})`，成功后用 `trimesh.load` 接管（体检、导出、预览都不变）
