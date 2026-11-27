# 外轮廓花瓣：检测与规整

`stamp_pipeline.py` 默认 `--frame-regularize auto`，只处理 `--frame-mode silhouette` 的花瓣/扇贝外框；动物剪影、异形轮廓不会动。

## 检测

把外轮廓按质心转成极坐标 `r(θ)`，平滑后找峰/谷：

- 瓣数 `N` = 峰谷数的中位；只接受 6–24
- 峰半径 `R`、谷半径 `r`、振幅 `amp=(R-r)/R`
- 角间距变异 `spacing_cv`、峰半径变异 `peak_radius_cv`
- 圆度 `circularity`、实心度 `solidity=area/convex_hull.area`

自动规整必须同时满足：

```
solidity >= 0.92
circularity >= 0.60
8 <= N <= 24
0.02 <= amp <= 0.12
spacing_cv >= 0.10 或 peak_radius_cv >= 0.015
```

前四条排除动物/异形，后一条只抓“大小瓣/间距不均”。

## 重建

用检测到的 `N / R / r / phase` 重建等距圆形弧花瓣：

- 每瓣是一段圆弧，瓣间交点为谷
- 所有瓣共用同一 `R/r`，角间距固定 `2π/N`
- 面积变化超过原轮廓 ±20% 时拒绝
- 规整后若切到图案（`pattern.difference(new_base)` 超阈值）自动回退原轮廓，记 `pattern_conflict`

## 命令

```text
--frame-regularize auto     # 默认：明显不均才规整
--frame-regularize force    # 强制规整
--frame-regularize off      # 保留原轮廓
--frame-petals 12           # 指定瓣数（会触发规整；配 force 更明确）
```

## 产物

- `report.json` → `frame`：`detected`（N、CV、圆度、实心度、suggest）、`applied`、`reason`、`petals_used`、`area_change_pct`
- `frame_check.png`：原轮廓（绿）/ 峰（红）/ 谷（蓝）/ 规整后（橙）叠加图；只在检测到花瓣且建议或已规整时生成
- `MANIFEST.md` 头部会标“外轮廓规整 N 瓣”

## 实测

| 图 | N | 间距 CV | 实心度 | 结果 |
|---|---|---|---|---|
| house | 16 | 21.5% | 0.970 | 规整，面积 +0.7% |
| santa | 18 | 6.8% | 0.968 | 已较规整，保留 |
| tree | 17 | 4.8% | 0.971 | 已较规整，保留 |
| angel_dog | 10 | 53.6% | 0.787 | 非花瓣框，保留 |