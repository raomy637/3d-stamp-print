# 打印清单

> 由 `src/make_print_index.py` 自动生成，**别手改**；重跑脚本或重新出件后会自动刷新。
> 最近更新：2026-11-24 23:40

**先看这一句**：能直接丢进切片器的文件全在 `print/` 下，分三个抽屉——`standard/` 是定稿可复用的标准件，`jobs/` 是这一单要打的模具，`test/` 是试打对比件。其余目录（`out/`）都是给人看的。

## 订单模具（`print/jobs/`，一单一个目录）

### `2026-11-24_xmas_pair/B_xmas_cav` （凹模 · 成品 85.0mm · 槽深 1.8mm 外张 5.0° · 底板 3.0mm）

| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |
|---|---|---|---|---|---|
| 底模 | `print/jobs/2026-11-24_xmas_pair/B_xmas_cav/base.stl` | 84.2 × 84.2 × 3.0 | 37,890 | ✓ | 14.91 |
| 边框 | `print/jobs/2026-11-24_xmas_pair/B_xmas_cav/cutter.stl` | 95.4 × 95.4 × 12.0 | 17,736 | ✓ | 5.32 |

### `2026-11-24_xmas_pair/A_xmas` （凸模 · 成品 85.0mm · 浮雕 1.8mm · 底板 3.0mm）

| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |
|---|---|---|---|---|---|
| 底模 | `print/jobs/2026-11-24_xmas_pair/A_xmas/base.stl` | 84.2 × 84.2 × 4.8 | 37,890 | ✓ | 18.56 |
| 边框 | `print/jobs/2026-11-24_xmas_pair/A_xmas/cutter.stl` | 95.4 × 95.4 × 12.0 | 17,736 | ✓ | 5.32 |

### `bakers_cav` （凹模 · 成品 85.0mm · 槽深 1.8mm 外张 5.0° · 底板 3.0mm）

| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |
|---|---|---|---|---|---|
| 底模 | `print/jobs/bakers_cav/base.stl` | 84.2 × 84.2 × 3.0 | 47,980 | ✓ | 14.91 |
| 边框 | `print/jobs/bakers_cav/cutter.stl` | 95.4 × 95.4 × 12.0 | 17,736 | ✓ | 5.32 |

### `bakers_v5` （凸模 · 成品 85.0mm · 浮雕 1.8mm · 底板 3.0mm）

| 件 | 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |
|---|---|---|---|---|---|
| 底模 | `print/jobs/bakers_v5/base.stl` | 84.2 × 84.2 × 4.8 | 37,876 | ✓ | 18.56 |
| 边框 | `print/jobs/bakers_v5/cutter.stl` | 95.4 × 95.4 × 12.0 | 17,736 | ✓ | 5.32 |

打印要点：底模平板贴床、图案（或凹槽）朝上，0.2 喷嘴 0.10 层高 / 4 墙 / 顶面熨烫 / 无支撑；边框翼缘贴床、刃口朝上，4 墙 + 4mm brim，打完翻过来用。详见 `guides/printing.md`。

## 标准件（`print/standard/`，定稿复用，换图不用重打）

| 文件 | 外形 mm | 面数 | 水密 | 体积 cm³ |
|---|---|---|---|---|
| `print/standard/handle_x6.stl` | 124.0 × 14.0 × 25.0 | 10,368 | ✓ | 12.2 |
| `print/standard/handle_x12.stl` | 124.0 × 36.0 × 25.0 | 20,736 | ✓ | 24.4 |
| `print/standard/handle_slim.stl` | 14.0 × 14.0 × 25.0 | 1,728 | ✓ | 2.03 |
| `print/standard/handle_column.stl` | 14.0 × 14.0 × 25.0 | 960 | ✓ | 3.76 |
| `print/standard/handle_column_x6.stl` | 124.0 × 14.0 × 25.0 | 5,760 | ✓ | 22.54 |
| `print/standard/handle_column_x12.stl` | 234.0 × 36.0 × 25.0 | 11,520 | ✓ | 45.09 |
| `print/standard/handle_straight.stl` | 15.0 × 15.0 × 25.0 | 1,344 | ✓ | 2.05 |
| `print/standard/handle_straight_x6.stl` | 130.0 × 15.0 × 25.0 | 8,064 | ✓ | 12.29 |
| `print/standard/handle_straight_x12.stl` | 130.0 × 38.0 × 25.0 | 16,128 | ✓ | 24.59 |

打印要点：底盘贴床直立、无支撑。层高按外观给：0.4 喷嘴 0.12、要手感换 0.2 喷嘴 0.08–0.10。粘接面 φ14，502 涂一薄圈就够。

## 测试件（`print/test/`，试打与对比，随时可删）

| 文件 | 用途 | 外形 mm | 面数 | 水密 |
|---|---|---|---|---|
| `print/test/handle_layer/layer_3.stl` | handle_layer | 65.0 × 15.0 × 25.0 | 4,032 | ✓ |

## 非打印产物（都是给人看的）

| 位置 | 内容 |
|---|---|
| `out/<job>/MANIFEST.md` | 这一单出了什么、每件能不能打（自动生成） |
| `out/<job>/report.json` | 几何体检：尺寸 / 面数 / 水密 / 线宽 / 边框参数 |
| `out/<job>/preview.png` | 三栏预览（实物 / 压印效果 / 剖面带尺寸） |
| `out/<job>/model.html` | 单文件 3D 预览，双击即开 |
| `out/handles/` | 手柄体检 json + 联排俯视图 |
| `out/_archive/` | 淘汰件留档，别拿去打 |

