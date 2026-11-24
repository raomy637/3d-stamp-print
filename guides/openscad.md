# OpenSCAD 引擎（v11）

> 这份文档解释：为什么把建体从 trimesh 换成 OpenSCAD、两边怎么分工、实测数据、以及踩过的坑。
> 只想知道怎么用，看 README 的 `--engine` 参数即可。

## 一句话

**图案 → OpenSCAD，边框 → trimesh。** 前者吃 2D 轮廓挤出与布尔，后者做等距偏置。

## 为什么不全都交给 OpenSCAD

v11 之前建体走 `shapely 2D 布尔 + trimesh/manifold 3D 并集`。迁到 OpenSCAD 的动机是
借 PJ1（`D:\HA1\PJ1`，名字印章生成器 stampgen）的做法：2D 轮廓给 CGAL，
Python 只管"位图 → 多边形"。收益：

- 参数化模板（`scad/base.scad`），改一个变量就出件，可在 OpenSCAD GUI 里按 F5 预览
- 绕开我们踩过的坑：凹模 sink 模式下图案把顶面切成互不相连的小岛，
  trimesh 的 volume 预检直接失败（当时只能 `check_volume=False` 硬过）
- 网格面数更少（凹模 144.6k → 48.0k 面），切片更快

但边框不能交给它：边框全靠 `offset()` 做墙厚、翼缘、8 段刃口，
OpenSCAD 对一条 2000 点的轮廓反复 offset 实测 **114.7 秒**，
trimesh 的同一件只要 **0.50 秒**（229 倍）。所以边框固定走 mesh。

## 实测（本机，OpenSCAD 2021.01，i5 级 CPU）

| 件 | 引擎 | 耗时 | 面数 | 体积 | 水密 |
| --- | --- | --- | --- | --- | --- |
| 底模 raise 85mm | OpenSCAD | 19.3s | 37,876 | 18.56 cm³ | ✔ |
| 底模 raise 85mm | mesh | 5.2s（全流程 5.7s） | 56,194 | 18.56 cm³ | ✔ |
| 底模 sink 85mm | OpenSCAD | 25.6s | 47,980 | 14.90 cm³ | ✔ |
| 底模 sink 85mm | mesh（v10 件） | — | 144,648 | 14.65 cm³ | ✔ |
| 边框 85mm | OpenSCAD | 114.7s | — | — | ✔ |
| 边框 85mm | mesh | 0.50s | 58,930 | 5.62 cm³ | ✔ |
| 手柄 φ14×25 | OpenSCAD | <1s | 1,728 | 2.03 cm³ | ✔ |

两个 raise 件的体积**完全一致**（18.56），说明 2D 轮廓与挤出高度没有偏差；
sink 差 1.7%，来自拔模近似方式不同（见下）。

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

## 安装

OpenSCAD 约 43MB，不进 git（`.gitignore` 已排除 `tools/openscad/`）。三种给法：

1. 本机已有：把便携版放到 `tools/openscad/`（`openscad.exe` / `openscad.com` 任一）
2. 任意位置：设环境变量 `OPENSCAD_BIN=D:\path\to\openscad.com`
3. 装在 PATH 里：`find_openscad()` 会自动找到

找不到时 `--engine scad` 会**自动回退 mesh** 并打一行日志，不会中断出件。

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
