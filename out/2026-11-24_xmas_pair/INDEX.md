# 批次 2026-11-24_xmas_pair

> 由 `src/batch_molds.py` 自动生成。2 套模具，并行 2 路，总墙钟 0.3 分钟（平均每套 8.2s）。

每套的底模与边框都在同一个单号目录下，配对关系看下表最后一列。

| 单号 | 图案 | 成品 mm | 凸/凹 | 底模 | 边框 | 面数 | 水密 | 耗时 s |
|---|---|---|---|---|---|---|---|---|
| `A_xmas` | bakers_framed.png | 85 | 凸模 | `base.stl` | cutter.stl | 37890 | ✓ | 11.9 |
| `B_xmas_cav` | bakers_framed.png | 85 | 凹模 | `base.stl` | cutter.stl（同 `A_xmas`，不必重复打） | 37890 | ✓ | 11.8 |

成功 2 / 2 套。

打印入口：`print/jobs/2026-11-24_xmas_pair/<单号>/`，底模 + 边框成对；手柄不在这批里（`print/standard/handle_straight.stl`，单独打）。
