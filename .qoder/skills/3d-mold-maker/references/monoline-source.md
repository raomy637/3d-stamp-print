# monoline 细线源稿口径（2026-11-27 增补）

竞品参考件实测线宽 0.3–1.4mm ≈ 2 条挤出线：Arachne 沿笔画铺 2 条变宽墙即填实，内部没有放填充的缝 ⇒ 无蜂窝、表面是顺笔画的直线走线。我们存量件线宽 1.3–3.0mm，只能靠切片实心（100% 填充 + 8 墙），表面是实心斜纹。**两条路线并存，按件选，不混用。**

## 路线选择

| 路线 | 适用 | 源稿 | 切片 |
|---|---|---|---|
| SVG 矢量收缩（首选） | 客户/设计源是 SVG | `src/tools/svg_shrink.py` | 默认 2–3 墙 + Arachne |
| 位图 → SVG 封顶 + 花瓣等径（**位图首选**） | 只有 PNG/JPG，且要「线宽统一上限 + 外框花瓣一样大」 | `src/tools/raster_to_svg.py` | 默认 2–3 墙 + Arachne |
| SVG 范围压缩 | SVG、线宽本来不等、要保比例 | `src/tools/svg_shrink.py --min-mm/--max-mm` | 默认 2–3 墙 + Arachne |
| 位图代码归一 | 只有 PNG/JPG、只要整体变细 | `src/tools/monoline_normalize.py` | 默认 2–3 墙 + Arachne |
| 粗线存量 | 已有订单、粗字重源稿 | 不动 | 100% 填充 + 8 墙（0.4 喷嘴）+ Arachne + 顶壳 6，熨烫关 |

### 位图 → SVG 封顶 + 花瓣等径（2026-11-28 新增，house 实测）

位图源稿要「换 SVG + 线宽最细处 1mm + 文案 1mm + 花瓣一样大」时走这条：**先矢量化，再在矢量层封顶**，图案拓扑与字形全部来自原稿（骨架定位，不用生图模型）。

```text
.venv\Scripts\python.exe src\tools\raster_to_svg.py --input 原图.png ^
  --out-svg 图_1mm.svg --out-png 图_1mm.png --report 图_1mm.json ^
  --size 101.6 --cap-mm 1.0 --frame-mm 1.5 --px 3000
.venv\Scripts\python.exe src\stamp_pipeline.py --input 图_1mm.png --out out\<job> --size 101.6 ^
  --print-dir print --job <job>
.venv\Scripts\python.exe tests\test_raster_to_svg.py          # 5 项判据回归
.venv\Scripts\python.exe tests\test_raster_to_svg.py red      # 基线：--cap-mm 3.0 → 判据 1 必 FAIL
```

- **只压不涨**：每块骨架 → 剪毛刺 → 逐点半径 `r = min(局部半宽, cap/2)` → 按「最近骨架点半径」重建。源稿比 cap 细的地方保持原样（用户明确要求：原稿 <1mm 的线不要拉粗）。**不要**用统一半径（那是 monoline_normalize 的行为，会把细线拉到 cap）。
- **花瓣等径**：填充成剪影 → 极坐标测瓣数与峰/谷 → `build_scallop_polygon` 建理想等径花瓣 → 沿其边界径向内缩 `w/2` 得中线 → 描边 `--frame-mm`。实测 house 16 瓣：角间距 CV 21.5% → **0%**，峰半径 CV 0.7% → **0%**。
- 输出 SVG 用 `fill-rule=evenodd` 单层实心路径（单位 mm，可直接进设计软件手改）；PNG 供管线。
- 三个实测踩过的坑：
  1. **栅格化不能「逐多边形先填外框再填孔」**——外框是环，环的孔里还装着文字，填白会把先前画好的字擦掉（表现为文字被整齐切掉一截）。改成**全局嵌套深度**绘制：深度偶数黑、奇数白，按深度升序画。
  2. **每瓣画一整段圆弧再并集会叠出三角形补丁**——瓣很浅时圆弧跨角远大于 2π/n（house 实测 37.7° vs 11.25°）。必须用理想多边形边界反算 `r(θ)`。
  3. **`ideal.buffer(-w)` 内缩尖点会出直线和弦补丁**——沿中线描边代替内缩。
- 实测（house 源 1254px / 成品 101.6mm）：源线宽 0.97/1.50/1.82mm（外框 1.82）→ 输出骨架中位 **1.05mm**、95 分位 1.12、最粗块 1.19（字母交叉鼓包），源最细 0.97 的块保持 1.01；39 块 → 39 块；源骨架覆盖 100%；外框 16 瓣等径、环宽 1.5mm；base 100×100×5.5mm 水密 25.4cm³，STL 剖切确认图案完整、文字正确。
- `--cap-mm 0.8` 实测：输出骨架中位 **0.81mm**（95 分位 0.82、最粗图案块 0.82），39 块不变，源骨架覆盖 95.4%；管线报 `stroke_stats` min 0.86 / 中位 1.02 / max 1.18（38 块），base 100×100×5.5mm 水密 24.75cm³。0.8mm ≈ 1.9 条挤出线，Arachne 2 墙即可填实。
- ⚠ **字形抖动（字母变形的真凶）不是模型/切片参数**：cap 到 0.8mm 时源图 1254px 下字宽只有约 10px，骨架逐点半径的 ±1px 量化 = ±0.08mm，尖角处骨架还有台阶和毛刺 ⇒ 边缘呈波浪、字形走形（用户实测字母"M/E"发毛、转角发胖）。切片只决定走线，不会改字形；任何"线条变细"的路线都会把源稿分辨率不足放大出来。
  修法三条（已做成默认参数）：`--work-scale 3`（先 3 倍放大再封顶，量化误差降到 1/3）、`--smooth 0.8`（只平滑"半径值"不碰边界，去掉沿骨架的宽度抖动）、`--simplify-mm 0.02`（压顶点数，兼治 OpenSCAD 并集失败）。实测同稿 0.8mm：1x 版字母边缘明显毛糙；3x+smooth 版中位 0.82mm、字形干净（对照 `work/订单/.../house/_记录/house_08c_letter_zoom.png`）。
- ⚠ **出模用 `--px 2000`，别用 3000**：3000px 时轮廓顶点翻倍，实测触发 OpenSCAD `Not all meshes are volumes!` → 退化为拼接，`cutter.stl` / `plate.stl` 水密变 False（base 仍水密）。同一份稿用 2000px 重跑即恢复正常。
- **镜像核验法**（用户提出"没按 skill 镜像"时先量再答）：取 STL z=底板+浮雕/2 剖切 → 与源稿图案（去外框）按内容框对齐 → 3px 容差比覆盖率。house v5 实测：**镜像稿 100% 覆盖、未镜像稿 61%** ⇒ 镜像正确（底模本来就该是镜像的，正看文字反是正常现象）。注意 `to_2D()` 的坐标基准不可假设，用它出图时要按实际渲染核对朝向。
- ⚠ `report.json` 的 `stroke_stats_mm` 仍是「每块最大宽度」，本例报 min 1.1 / 中位 1.34 / max 1.65（鼓包抬高），**判断封顶是否到位看 `raster_to_svg` 自己打印的「实测线宽」或 `house_1mm.json` 的 `out_width`**。
- 注意：管线 `--frame-mode silhouette`（默认）会把外框环当底面剪影、丢弃框体，所以**外框线本身不会成为浮雕线**；花瓣等径影响的是成品外轮廓。需要框线也凸起时用 `--frame-mode keep`，但那会让边框变成粗浮雕，另行确认。

### SVG 矢量收缩（首选，几何零漂移）

矢量最忠实：**几何一个点都不动，只改线宽**，而且不用骨架重建，不存在拆字/长毛刺。

```text
.venv\Scripts\python.exe src\tools\svg_shrink.py --input 设计.svg --out 细线.png ^
  --size 101.6 --target-mm 0.6 --frame-mm 1.5 --px 3000
```

**线宽范围压缩**（推荐，用于线宽本来不等、又不想压死细线的稿）：

```text
.venv\Scripts\python.exe src\tools\svg_shrink.py --input 设计.svg --out 细线.png ^
  --size 101.6 --min-mm 1.0 --max-mm 1.4 --frame-mm 1.5 --px 3000
```

映射 `w' = min + (w - w_src_min) * (max - min)/(w_src_max - w_src_min)`：**最细那条 → min，其余按同一斜率收窄**，稿内粗细比例保留、整体变细；比 min 还细的走骨架加粗到 min。给了 `--min-mm` 就自动启用，`--max-mm` 缺省 = min×1.4；工具会打印连通块数量变化，`N → N-1` 说明有线条加粗后并块（需回退或拉大间距）。
1mm ≈ 2.4 条挤出线（0.42），比 0.6mm 更抗压、脱模更稳，同样不会出现蜂窝。

- 自动判别两种 SVG：**描边式**（fill 全为 none）直接改 `stroke-width`，精确等于目标线宽；**填充式**（有实体 fill）用「骨架中位半宽」量真实线宽后做**距离变换腐蚀**（`edt > (w-target)/2`），线宽减 2d、中心线严格不变。
  ⚠ 不能用 `2*面积/周长` 估宽度：短弧/字母笔画会低估一半（实测只收到 1.27mm 而非 0.6mm）。
- 渲染通道本机 msedge/chrome headless 截图（无 cairo/cairosvg）；`--px 3000` 对 101.6mm 件约 0.033mm/px，够准。
- **外框必须单独给宽度**（`--frame-mm`，默认 1.5）：设计稿的外框常是 0.2mm 装饰描边，环自身面积仅 0.6% 图幅 → `find_frame` 不认 → 底面退化成圆。加粗到 1.5mm 后环面积约 4.8% ✓。外框只取剪影、不成浮雕线，加粗不影响图案观感。
- 成品实测（christmas 设计 82.44mm → 出 101.6mm，target 0.6）：输出 PNG 骨架中位线宽 **0.61–0.67mm**，外框 1.49mm，图案 28 条，外框识别为 16.6x 填充比花瓣剪影，base 100×100×5.5mm、水密、24.7cm³。
- **读数口径差异**：`report.json` 的 `stroke_stats` 取「每个连通块的局部最大宽度（dt.max*2）」，字母交叉/合并处的鼓包会把它抬高（本例中位 1.14、max 2.18），**不代表线的粗细**；判断收细是否到位看工具输出行「实测线宽 mm」或骨架中位。

```text
.venv\Scripts\python.exe src\tools\monoline_normalize.py --input 原图.png --out 细线.png --size 101.6 --target-mm 0.6
.venv\Scripts\python.exe src\stamp_pipeline.py --input 细线.png --out out\<job> --size 101.6 --relief 2.5 --print-dir print --no-index
.venv\Scripts\python.exe tests\test_monoline_normalize.py new 0.6   # 位图路线验收判据回归
```

- 目标线宽 = 2×喷嘴线宽是**上限愿望**，实际受源稿最密特征间距限制：中心线归一后相邻平行笔画间距 < 目标线宽就会并块。santa 原图实测上限 ≈0.6mm（雪花分叉/胡子短弧间距 ≈0.67mm）；要 0.9mm 必须源稿本身留更大间距（重画），否则接受合并。0.6mm 仍在竞品实测 0.3–1.4mm 区间内，0.4 喷嘴 Arachne 1–2 条变宽墙填实、无填充缝。
- **首选代码中心线归一**：`src/tools/monoline_normalize.py`（骨架 → 剪毛刺 → 定半径重建，**不做 ∩原区域**）。验收测试 `tests/test_monoline_normalize.py`：线宽均匀、不拆字、中心线覆盖、不长毛刺；RED 基线 = `cap_stroke_width`（∩原区域留粗块，线宽 0.88–1.81 不均匀）。
- **禁止生图模型重新创作订单图案**（文生图会漂移构图/字形/细节）；AI 编辑只作最后备选且必须与原图逐项对比。`--stroke-cap` 维持量产禁用。
- 细线风格改变字重观感（粗字变中心线细字），订单件交付前先给客户确认。

## 源稿三条要求

1. **内部线条细且均匀**（monoline），无填充色块、无灰度阴影。
2. **外框单闭合环、与内部图案分离**（不接触），bbox 铺满 >80%，且**环自身面积 ≥2% 图幅**——`find_frame` 的噪声门槛，细线外框最容易栽在这（house 细线稿外框 1.8% → `no_frame` → 退化圆底）。外框只取剪影、不成浮雕线，所以**外框可单独加粗**（建议线宽 ≈2–2.5% 图幅），不影响内部细线观感。花瓣/异形都走这条，外框形状即成品形状。
3. **无多余内环**：AI 细线稿常多画一圈内圆。prep 按「环状连通块：填充比 >3 且 span 0.5–0.88」删除；**只把删除区涂白、保留其余灰度抗锯齿**——纯 0/255 二值图会让 Otsu 阈值退化为 0，整图判空。

## 核验落点（读 report.json，fail-closed）

- 源稿有外框但 `frame.reason == "no_frame"` ⇒ **停**，修源稿（外框加粗/与图案分离），不得交圆底件。
- 走 `raster_to_svg` 的件，先过 `tests/test_raster_to_svg.py`：线宽封顶（中位 ≤ cap+0.10、95 分位 ≤ cap+0.20）、不增粗、细线不拉粗、块数不少（≥90%）、源骨架覆盖 ≥95%、外框峰半径与角间距 CV < 1.5%。任一项 FAIL ⇒ 不 build。
- 花瓣框件：`info["spacing_cv_after"]` 与 `peak_cv_after` 必须为 0（等径重建），且 `--petals` 未误改成别值；成品轮廓只有一套一致的花瓣，不能大小混排。
- monoline 路线 `stroke_stats_mm.max > 1.3` ⇒ 源稿混入粗笔画，停，重画。注意 report 的 min 是加粗前统计，垫细线看日志「线宽体检…0 个会消失」。
- `preview.png` 缺部件 ≠ STL 缺部件：双环源稿会触发预览把内部图案当洞填掉的渲染 bug。**事实来源是 STL 剖切**（trimesh `section` 取 z = 底板 + 浮雕/2，栅格化看闭合环嵌套）。

## 命令与实测

```text
.venv\Scripts\python.exe src\tools\monoline_normalize.py --input 原图.png --out 细线.png --size 101.6 --target-mm 0.6
.venv\Scripts\python.exe src\stamp_pipeline.py --input 细线.png --out out\<job> --size 101.6 --relief 2.5 ^
  --print-dir print --no-index
.venv\Scripts\python.exe tests\test_monoline_normalize.py new 0.6   # 验收判据回归
```

| 件 | 线宽 min/中位/max mm | 外框 | 墙数提示 |
|---|---|---|---|
| house 细线（生图重画，外框未加粗，反例） | 0.48 / 0.80 / 1.18 | `no_frame` → 圆底，**拒收** | 3 |
| santa 位图代码归一 0.6mm | 0.58 / 0.71 / 1.02 | 18 瓣继承 | 3 |
| christmas SVG 收缩 0.6mm | 0.61 / 0.64 / 1.49(外框) 实测 | 16.6x 填充比花瓣继承 | 6（含交叉鼓包） |
| christmas SVG 范围压缩 1.0–1.4mm | 源 1.41–1.79 → 目标 1.00–1.40 | 花瓣继承 | 7 |
| angel_dog SVG 范围压缩（源全 0.24mm） | 全部 → 1.00mm 实测 1.00–1.48 | 无框（原稿即无花瓣环） | — |
| house 位图→SVG 封顶 1.0mm | 源 0.97/1.50/1.82 → 输出 1.01/1.05/1.19 实测 | 16 瓣等径（间距 CV 0 %）、环 1.5mm | 4 |
| house 基线（cap 3.0 等于不封顶） | 中位 1.54 / 95分位 1.77 → 判据 1 FAIL | — | — |

证据留档：`work/_实验/svg_shrink/`（SVG 路线：原稿渲染、收细稿、对比板、剖切、STL）、`work/_实验/raster2svg/`（位图→SVG 封顶路线：SVG/PNG/JSON/剖切/STL）、`work/_实验/monoline_code/`（位图归一）、`monoline_house/`、`monoline_santa/`（生图反例）；cap 收细反证见 `work/_实验/width_diag_demo.png`。