# 变更记录

> 只记「改了什么 + 为什么」。现状看 `README.md`，历史细节留在这里，避免 README 膨胀。

## v11.24 · 2026-11-27 · svg_shrink 支持线宽范围压缩（最细定 1mm、其余同斜率收窄）

- 需求：用户线宽本来不等，不想一刀切压到 0.6mm（会把细线压没），希望「最细 1mm、其余等比例收窄」。
- 新增 `--min-mm / --max-mm`：映射 `w' = min + (w - w_src_min) * (max-min)/(w_src_max-w_src_min)`。粗线走距离变换腐蚀（中心线不变），比下限还细的走骨架加粗；描边式按每个 stroke-width 换算，填充式按连通块实测宽换算。
- 会报连通块数量变化（`N → N-1` 即有线条加粗后并块），作为回退信号。
- 实测：christmas 源 1.41–1.79mm → 1.00–1.40mm（无并块）；angel_dog 源全 0.24mm → 全部 1.00mm（实测 1.00–1.48）。范围压缩件 base 98.84×99.99×5.5mm、水密、25.8cm³、图案 28 条。
- 口径：1mm ≈ 2.4 条挤出线，比 0.6mm 抗压/脱模更稳，同样无蜂窝；skill 与 design-rules 记为推荐用法。

## v11.23 · 2026-11-27 · 新增 SVG 矢量收缩路线（细线首选）

- 需求：用户希望直接给 SVG，由代码收细线条再出模。新增 `src/tools/svg_shrink.py`，**几何零漂移**（只改线宽，不动任何点）。
- 自动判别两种 SVG：描边式（fill 全 none）改 `stroke-width`，精确等目标线宽；填充式（实体 fill）用「骨架中位半宽」量真实线宽后做距离变换腐蚀（线宽减 2d，中心线严格不变），不重建骨架故不拆字。
- 踩坑 1：`2*面积/周长` 估宽度在短弧/字母上低估一半（设 0.6 只收到 1.27mm），改用骨架 EDT 中位数。
- 踩坑 2：SVG 常把外框画成 0.2mm 装饰描边（环面积 0.6% < find_frame 的 2% 门槛 → 底面退化圆）。加 `--frame-mm`（默认 1.5）单独加粗外框环，只取剪影不影响图案；christmas 件加粗后 16.6x 填充比、花瓣剪影正常继承。
- 渲染通道：本机 msedge/chrome headless 截图（无 cairo/cairosvg）；`--px 3000`。
- 成品实测（christmas 82.44mm → 101.6mm，target 0.6）：输出骨架中位线宽 0.61–0.67mm、外框 1.49mm、图案 28 条、base 100×100×5.5mm 水密 24.7cm³。
- 口径：`stroke_stats` 取「连通块局部最大宽度」，交叉鼓包会抬高读数（本例中位 1.14/max 2.18），判收细是否到位看工具输出「实测线宽 mm」。skill 与 design-rules 把 SVG 路线列为首选，位图归一退为备选。

## v11.22 · 2026-11-27 · 细线路线改代码中心线归一，弃生图重创作

- 用户纠正：生图模型"重画"漂移了订单图案（构图/五官/字形），不可接受。新增 `src/tools/monoline_normalize.py`：骨架 → 剪毛刺 → 定半径重建（**不做 ∩原区域**，cap 的粗块根因），外框环保留原样；输出保留灰度抗锯齿、黑线白底。
- TDD：`tests/test_monoline_normalize.py` 四判据（线宽均匀/不拆字/中心线覆盖/不长毛刺）。RED = cap（0.88–1.81mm 不均匀）；GREEN = 新实现。
- 几何约束实测：目标线宽受源稿最密特征间距限制——santa 雪花分叉/胡子短弧间距 ≈0.67mm，0.9mm 必并块（1.77mm 宽块），**忠实话上限 ≈0.6mm**；0.6mm 仍处竞品 0.3–1.4mm 区间，0.4 喷嘴 Arachne 1–2 变宽墙填实。santa 代码归一件：线宽 0.58/0.71/1.02mm、18 瓣外框继承、28 个图案多边形与原图一致，忠实度对比与剖切在 `work/_实验/monoline_code/`。
- 口径同步：skill monoline-source 与 SKILL.md、pipeline-commands、design-rules 第 5 条改为"代码归一首选、重画备选、禁生图重创作"。

## v11.21 · 2026-11-27 · monoline 细线路线定稿：线宽靠源稿、外框靠剪影

- 结论：竞品无蜂窝 + 直线观感的根因是**源稿线宽 ≈2×挤出线宽**（参考件实测 0.3–1.4mm），Arachne 2 条变宽墙填实整条线；不是建模算法差异。粗线存量件继续切片实心（100% + 8 墙），细线观感只能重画 monoline 源稿（0.4 喷嘴 0.9mm），`--stroke-cap` 维持量产禁用。
- 外框门槛实测：`find_frame` 要求环自身面积 ≥2% 图幅；house 细线稿外框 1.8% → `no_frame` 退化圆底（拒收反例）。外框只取剪影，**可单独加粗**不影响细线观感；santa 细线稿外框加粗到 3.8% 后 19 瓣正常继承。
- AI 细线稿 prep 两条：多余内环按「填充比 >3 且 span 0.5–0.88」删除；只涂白删除区保留灰度抗锯齿（纯 0/255 二值图 Otsu 阈值退化为 0，整图判空）。
- 预览 bug 留档：双环源稿（外框 + 内圆同存）时 `preview.png` 把内部图案当洞填掉；STL 本身完整，核验以剖切为准。santa/house 细线验证件与剖切图在 `work/_实验/monoline_santa/`、`monoline_house/`。
- 落点：skill 新增 `references/monoline-source.md`（源稿三要求 + report 核验 fail-closed：`no_frame` 停、monoline max>1.3 停），SKILL.md 硬门槛加第 11 条线宽路线、核验红线改双路线；`guides/design-rules.md` 增第 5 条、README 输入要求与口径标题同步。

## v11.20 · 2026-11-27 · 墙数按最大笔画倒推（wall_hint），不靠收细模型

- 量化规则：**墙面数 × 线宽 ≥ 该单最大笔画宽度**时，笔画内部不存在可放稀疏填充的空间，蜂窝与填充比例彻底无关。三单实测最大笔画 house 2.87 / santa 2.98 / tree 2.80mm，0.42mm 线宽对应 `wall_hint` = **7 / 8 / 7**，统一取 **8 墙**（8 × 0.42 = 3.36mm）。
- `stamp_pipeline.py` 在出件日志打印建议墙数，`report.json` 新增 `wall_hint`（⌈max ÷ 0.42⌉，下限 2）；`MANIFEST.md`、`PRINT.md`、`README.md`、`guides/printing.md`、`SKILL.md` 统一改为「**100% 填充（底线）+ 0.4 喷嘴 8 墙（第二道保险）**」。4 墙只覆盖 1.68mm，比这宽的笔画中间仍留缝，填充一降就回蜂窝；0.2 喷嘴线宽约 0.22mm，8 墙覆盖不到 3mm，以 100% 填充为准。
- 反证：把 2.5mm 粗字后处理压到 0.9mm（≤2 道挤出线）会把 A 的横杠、M 的 V 口、R 的碗口拆成线状——这是字重与内孔尺寸的几何事实（见 `work/_实验/width_diag_demo.png`），任何骨架/偏移算法都改不了。要细线观感只能按目标线宽**重画源稿**；这三单继续用 v2 几何 + 100% 填充（0.4 喷嘴再加 8 墙）。

## v11.19 · 2026-11-27 · 线宽收细实验（默认关闭，santa A/M 形变）

- 新增 `--stroke-cap MM`（**默认 0=关闭**）：按骨架 + 圆盘把宽笔画收细。实测 santa 收到 1.0mm 时，A/M 等转角多的字母在骨架分叉处出现圆角/枝杈形变，不能用于量产，故保持实验项。
- 结论：防蜂窝靠切片 **100% 填充 + 顶壳 6 + Arachne**，不靠收细模型；凭空收细会改变字形。参考件 `Grand Tumelo-Luulia.stl` 与我们拓扑一致（单壳实心、垂直侧壁），线宽差异（0.3–1.4mm vs 1.3–2.9mm）是物理尺寸差异，不是“轮廓填充”建模差异。
- `report.json` 新增 `stroke_cap_mm` / `stroke_capped_parts`；README、SKILL、pipeline-commands 标注为“实验、量产不用”。
- 4246454365 的 `*_v3.stl` 保留作对照，**不建议打印**；量产仍用 `*_v2.stl`。

## v11.18 · 2026-11-27 · 每次导出附合盘 plate.stl

- 印章线每次同时出三件：`base.stl`、`cutter.stl`、`plate.stl`。`plate` 把底模**同心套进边框内腔**（实际批量就是这么打的），底面同贴床，两件仍独立、朝向不变（底模图案朝上、边框刃口朝上）；间隙 = `--cutter-clearance`（默认 0.8mm）。
- `report.json` 新增 `plate`（layout/间隙/尺寸/面数/水密），`MANIFEST.md` 增加合盘行与说明；间隙 <0.2mm 时日志告警（套着打会粘连）。
- 合盘按切片器口径重焊点后剔除边框偶尔带出的零体积膜片，三款 4 英寸订单实测均为两个水密壳、合盘整体水密。
- `--no-cutter` 或 `--rim-w>0` 时没有合盘；批量出件自动带 `plate.stl`，skill 的 `workspace.py collect` 同步收件。
- 文档：`SKILL.md`、`pipeline-commands.md`、`output-layout.md`、`batch.md`、`printing.md`、`README.md` 同步。

## v11.17 · 2026-11-27 · 浮雕默认高度 1.8 → 2.5mm

- `stamp_pipeline.py --relief` 默认改为 **2.5mm**（凸模浮雕 / 凹模槽深），`batch_molds.py` 清单缺省同步 2.5。
- 凹模槽深仍受「底留 1mm」限制：2.5 槽深需 `--base-thickness 4.0`；被夹时日志明确提示，不再静默压到 2.0。
- `guides/cavity.md` 更新默认深度表与例子：2.5 立体感强，但 <0.9mm 细线深宽比 >2.8:1 时难脱模，这类图降到 1.8 或加粗；槽壁打印同步改为 100% 填充 + 顶壳 6。
- `README.md`、`guides/batch.md`、`guides/parts.md`、`guides/printing.md`、skill 的 `SKILL.md` / `folder-layout.md` / `pipeline-commands.md` 同步新默认。
- 试打件按 2.5mm 重出：`bars_test`（凸条 2.5 高，10.2cm³）、`petals_test`（环高 2.5，18.9cm³）、`pattern_test`（48.75mm，总高 5.5，7.1cm³），三块均水密。
- 顺手修 `render_side`：`--rim-w=0` 时“总高”误加 0.4mm 边框余量（旧图 4.8mm 件标成 5.2），现与 STL 实测一致。
- `MANIFEST.md` 的打印件路径不再硬编码 `print/jobs/<job>/`，改用 `--print-dir` 实际路径（自定义输出目录时不再指错）。
- 订单 4246454365（2026-11-26 的 house / santa / tree）按新规范重出：101.6mm、浮雕 2.5、house 外轮廓自动规整 16 瓣；底模 26.44 / 25.92 / 25.51cm³，全部水密；新件写入各款式 `打印模型/*_v2.stl`，记录在 `_reprint_20261127/`。

## v11.16 · 2026-11-27 · 花瓣外轮廓自动检测与规整

- `stamp_pipeline.py` 新增 `--frame-regularize {off,auto,force}`（默认 auto）与 `--frame-petals N`：极坐标测瓣数/峰谷/相位，用等距圆形弧重建；只在“实心度 ≥0.92、圆度 ≥0.60、8–24 瓣、振幅 2–12%、间距 CV ≥10% 或峰半径 CV ≥1.5%”时触发，动物/异形不动。
- 规整后若切到图案自动回退（`pattern_conflict`）；面积变化限 ±20%。`report.json` 新增 `frame` 记录前后指标，记录目录新增 `frame_check.png`（原轮廓/峰谷/规整轮廓叠加）。
- 回归：house 16 瓣、间距 CV 21.5% → 规整，面积 +0.7%；santa 18 瓣 6.8%、tree 17 瓣 4.8% 保留；angel_dog 实心度 0.787 判为非花瓣框，不误伤。
- Skill 新增 `references/frame-regularize.md`，开工清单与预览步骤同步。

## v11.15 · 2026-11-27 · 修正切片口径：凸起线条必须 100% 填充

- 现象：实物凸起线条表面呈蜂窝。根因是 `guides/printing.md` 把底模填充写成 25% grid；1.0–1.5mm 宽的线条内部只剩稀疏网格，顶面几层只是架在网格上的屋顶。
- 口径改为：**Arachne + 4 墙 + 100% 填充 + 顶壳 6 / 底壳 4**，熨烫仍关；`README.md`、`SKILL.md` 同步。
- 新增最小试打 `work/_实验/20261127_print_test/`：`bars_test.stl` 测 0.8–3.0mm 凸条是否实心；`petals_test.stl` 对比原轮廓 / 16 瓣规整轮廓 / 正圆。house 原图实测 16 瓣，角度间距变异 21.3%，是“大小瓣”的来源。

## v11.14 · 2026-11-26 · 文档治理：work 口径 / model.html 事实 / 引用体积检查

- 口径统一：`README.md` 与 `guides/output-layout.md` 改以 `work/` 为现行数据根，`print/` + `out/` 标注为历史批次；目录规则的唯一事实来源指向 skill 的 `folder-layout.md`，避免两套树并行增长。
- 事实修正：单套 `stamp_pipeline.py` 只自动出 `preview.png`/`report.json`，`model.html` 需另跑 `make_viewer.py`；`batch_molds.py` 才默认每套生成。`README.md`、`SKILL.md`、`pipeline-commands.md` 同步。
- `PRINT.md` 表头由生成器改为“只覆盖旧 `print/` 批次”，重刷后与 `work/订单` 的验收口径（`report.json`）一致。
- `README.md` 从 195 行压到 179 行（索引层 200 红线内），删掉与 `guides/design-rules.md` 重复的四条口径表；本地链接 0 缺失、代码路径引用 0 缺失。

## v11.13 · 2026-11-25 · 三角闭合（`--void-base`）+ 抹掉光环圈线

- 新增 `--void-base {both,cutter}`（默认 `both`）：`cutter` = 挖空区只作用在边框（长出内岛刃），底模保持整片 → 粘土上是一个**闭合的三角线**、泥不漏；`both` = 底模同位置开洞（旧行为）。
- 修「圆圈外侧又出现一个圆环」：光环那圈线在**细节组**里、落在 r≈120px（5.5mm）处，正好贴着沉台外沿 r4.8。改成 `det & ~annulus(105–140px)` 抹掉它；**只动细节组、不碰外轮廓环带** —— 第一版误切了环带一段，`find_frame` 填充比 12.3 → 1.30，底面退化成 100×100 圆盘（日志"未识别到外框"）。
- 重出 `print/jobs/angel_dog_100`（`--void-base cutter`）：底模 86.95×98.40×4.80（19,482 面、水密、16.3cm³、φ6 孔 + 沉台 + 湾处整片留料）、边框内腔 88.5×100.0（内岛闭合刃 + 3.0mm 顶桥）；新增对照件 `print/test/voidA`（`--void-base both`，底模留洞版），两份 `model.html` / 俯视截图都在。
- 文档：`README.md` 参数表补 `--void-base`、工艺口径表改写两种成品口径；`guides/design-rules.md` 2b 补底模开洞/留料的选择、第 3 节补"光环圈线必须抹掉"及误切环带的症状；`SKILL.md` 第 2、3 条同步（仍 120 行）。

## v11.12 · 2026-11-25 · 双刃闭合 + 底模留空 + 环形沉台挂环

- 新增 `--void-mask PNG`（挖空区掩码，黑=挖掉，与 `--input` 同尺寸同原点，脚本校验 shape）：内腔 `difference(void)` 后，`build_cutter` 的 **wall/edge 段不扣 void**（洞口自然长出「宽度=壁厚」的内岛刃，刃口闭合），只对 **flange 段扣 void**（否则翼缘会在洞口补一块板）。第一次实现时对所有段都扣了 void，内岛根本没长出来 —— 判据是日志里没有「内岛刃顶桥」。
- 新增 `--island-bridge MM`（默认 3.0）：`nearest_points` 在外圈与内岛之间搭顶桥，z 取 `max(height-2, top)..height`，只占顶部 2mm，翻过来压时不碰泥；内岛与外壳因此成为一个水密连通体（cutter 111,336 面、8.99cm³、单连通）。
- 新增 `--pocket CX,CY,RIN,ROUT,DEPTH`（**模型 mm**，可重复）：`apply_pockets()` 挤出「下窄上宽 0.15mm 拔模」的环形柱体后与底模做 `trimesh.boolean.difference`，在顶面铣出环形沉台；粘土压进去凸起一圈立体环。argparse 里负数坐标必须写 `--pocket=-1.65,...`（空格形式会被当成选项）。
- 口径修正（用户三轮回判）：**「底模要空心」不等于「粘土要空心」** —— 底模通孔只会让粘土顶出泥柱，真镂空只能靠边框的内岛刃；因此 v2 的「全实心封缝」被否，改成「边框双刃闭合 + 底模同位置留空」。挂环也从 v1 的「凸环 + 打孔」改成**环形沉台**（凸模凸起→成品凹陷，凸环只会压出凹槽），孔径改按吸管外径 φ6.0。
- `render_top` 加 `pockets` 参数：俯视把沉台画成浅槽环带（浅灰），并在所有填色**之后**统一把底模内环挖回 0，避免沉台/图案内环把通孔盖掉（这一版预览里 φ6 孔 + 槽一次画对）。
- 文档同步：`guides/design-rules.md` 新增「2b 轮廓闭合但中间要洞（`--void-mask` + 双刃）」、第 3 节改写为「环形沉台 + 打孔通孔」；`README.md` 参数表补 `--void-mask` / `--island-bridge` / `--pocket`，工艺口径表把「圆环」改沉台、新增「轮廓闭合但中间要洞」；`SKILL.md` 的「四件事」第 2、3 条重写并压回 120 行。
- 重出 `print/jobs/angel_dog_100`：底模 86.95×98.40×4.80（20,030 面、水密、16.2cm³、φ6 孔 + 环沉台 r3.0/r4.8 深1.0 + 湾处留洞 5.0×9.0）、边框内腔 88.5×100.0（壁/刃 1.0、外刃 + 内岛闭合刃 + 3.0 顶桥、111,336 面、水密、8.99cm³）；`model.html`、`shot_stacked.png`、`shot_top.png`、`preview.png` 全部重出。

## v11.11 · 2026-11-25 · 工艺四条口径（窄缝实心 / 打孔定位 / 单壁边框 / 镜像分类）+ 修「外轮廓对不上」

- **修「外轮廓和底模对不上」**：根因是底模与边框内腔各自从剪影外扩一次（+1.2 / +2.0），窄于外扩量的 V 尖处两次跨接不一致。改成内腔定基准（`cavity = 剪影.buffer(margin)`，`base = cavity.buffer(-clearance)`），并统一 bbox 偏移（`place()` 与新的 `place_pt()` 共用 `off`，不再逐件居中）。angel_dog 实测：环隙 p95 1.29 / max 3.50 → **全边界 100% 0.80mm**。
- 新增 `--close-gap MM`：窄缝/凹口形态学闭合后**连内腔一起填实**（只封口会留三角洞 + 边框多一圈内刃）。angel_dog 用 1.5mm 填掉 1 个内腔，两腿之间的 V 缝与尾部 2.94mm 缝变实心，尾部真镂空保留。
- 新增 `--hole COL,ROW,D`：底模板开打孔定位通孔，浮雕层同步让位；配合「圈内并剪影做实心 + 同位置凸环」实现圆圈定位打孔（angel_dog：凸环外r4.60/内r3.50，孔 φ3.9 @(-1.6,32.0)）。
- **边框改单壁**：`--cutter-wall` 与 `--cutter-edge` 默认都取 **1.0**（主体与刃口同厚），不再「1.2 主体 + 0.4 薄刃」两种厚度；翼缘 4×1.6 不变。要旧薄刃显式传 `--cutter-edge 0.4`。
- `render_top` 补一笔：图案内环填色会盖掉底模通孔，现在填完图案再把底模内环挖回来，预览里能看见孔。
- 新增 `guides/design-rules.md`（四条口径的原理、阈值依据、实测数据、参数模板）；`SKILL.md` 加「开工前必须钉死的四件事」摘要（并压回 120 行红线）；`README.md` 参数表补 `--close-gap`/`--hole`、改单壁默认；`guides/parts.md`、`guides/printing.md` 的 1.2/0.4 口径同步改 1.0 单壁。
- 重出 `print/jobs/angel_dog_100`：内腔 88.5×100.0（成品高 10cm）、底模 86.95×98.40×4.80（15,408 面、水密、16.5cm³）、边框 98.54×110×15（壁/刃 1.0、水密），`model.html` + `shot_stacked.png` / `shot_top.png` 重出，v1 记录与打印件已归档到 `out/_archive/angel_dog_100/`。

## v11.10 · 2026-11-25 · 三条实机问题：卡死 / 边框 15 / 线条断

- **间隙 0.4 → 0.8**（`--cutter-clearance` 默认改 0.8）。实测证据：`bakers_v5` 底模 84.2 对 85.0 内腔，设计 0.4/边，STL 实测**净间隙 0.28–0.48mm**，FDM 打完（0.2 喷嘴 4 墙，外壁胀 0.05–0.15、内壁缩 0.05–0.1）必然卡死。改成 0.8 后 `bakers_v6` 实测 **0.72 / p05 0.77 / 中位 0.90mm**，全周 ≥0.6。底模随之从 84.2 缩到 83.4。
- **边框高度 12 → 15**（`--cutter-height` 默认改 15）。结构不变：翼缘 1.6 → 主体到 12 → 垂直薄刃 12→15（刃段仍 3mm）。
- **线条"断开"的定性不是几何问题**。把 `bakers_v5` 浮雕层（z>3）投影成 2D（`out\_ref\floor_v5.png`），字母/雪花/雪人全部连续闭合；35 个部件腐蚀 0.44mm 也 0 个消失。实物断口的成因是**顶面熨烫**：熨烫喷嘴贴着顶面走一遍，0.6–0.9mm 窄浮雕会被压塌/削平。三条文档口径同步改掉（`guides/printing.md`、`guides/cavity.md`、`README.md` 与自动生成的 MANIFEST/PRINT.md 文案）：图案件**一律不熨烫**。
- 新增/重写 `src/tools/check_fit.py`：取点规则改成「底模取 z≈0 那一圈（底板外形）、边框取垂直薄刃段（内壁恒等于内腔）」，720 桶 + 相位扫描。旧版按全高度取 max/min 会混入图案顶点与翼缘顶点，误报 −1.66mm（其实 0.28）。新版给出两个判据：gap 分布 + 「最佳旋转/残差」——残差≈中位说明形状吻合，残差远小于中位才是错位。
- 重出 `print/jobs/bakers_v6`（凸）+ `print/jobs/bakers_cav_v6`（凹），各 6.4s / 5.8s，底模 83.40×83.40×4.80（39,174 面）/ 3.00（39,176 面），边框 15mm 水密，`model.html` 与叠放截图齐全。

## v11.9 · 2026-11-25 · 批量再提速：常驻 worker，40 套 96s → 61s

- 新增 `src/batch_worker.py`：一个进程连跑多套，`stamp_pipeline.main()` 与 `make_viewer.main()` 被当作函数重复调用（两者本来就吃 `argv` 列表，无需重构），numpy/scipy/skimage/trimesh 只导入一次。40 套省掉 **188 秒纯 CPU 导入**。
- `batch_molds.py` 改成"任务分片 + N 个常驻 worker"：主进程只拼参数、读报告、写 `INDEX.md`；`--serial` 保留旧法（每套独立进程）供排错。几何字节级不变——同 3 套新旧两法出的 6 个 STL，SHA256 完全一致。
- 多栏预览图改为**默认不出**（`preview.png` 每套 1.9s、40 套 76s CPU），要看加 `--preview`；`model.html` 仍每套都出（Skill 硬规则不变）。
- 实测（i5-13400，40 套 `--no-html`）：8 路 **96s → 60.6s**（−37%）；10 路 54.8s；12 路 51.0s；16 路 46.7s（−51%，但打满 16 线程、桌面明显卡，默认仍是 8）。10 套规模 51s → 22s。
- profile 结论写进 `guides/batch.md`：单套剩余 5s = 轮廓 0.4 + 外框识别 0.5 + 线宽统计 0.8 + shapely 0.2 + OpenSCAD 进程与渲染 1.3 + trimesh 体检 0.3，无单点值得再拆（降采样能省 0.9s 但会动轮廓精度，不做）。
- `make_viewer.main()` 补 `argv=None` 参数，使其可被进程内复用；CLI 行为不变。

## v11.8 · 2026-11-25 · 文档治理（Superpowers Plus 02 口径）＋ 补记 v11.7

- 体积对齐红线：入口 `SKILL.md` 126 → **108**（≤120）；索引 `README.md` 191 → **180**（≤200）。两者都正好压在 90% 预警线，下一条内容必须先拆再写。细节层：`openscad.md` 117、`output-layout.md` 106、`batch.md` 91，全部 ≤300。
- 单一事实来源：删掉 `SKILL.md` 里整张「参数默认值」表（与 README「参数」节重复），改成一条指针 + 三条不许破的口径（手柄只 straight / 刃口只 vertical / 边框引擎固定 mesh）；删掉 `SKILL.md` 里三条 OpenSCAD 坑的复述，改为指向 `guides/openscad.md`。
- 过期内容扫描（搜 `bakers_v3` / `handle_slim` / `φ14` / `1,728` / `2.03`）命中并修：`guides/openscad.md` 实测表改成 **nightly 为默认**（底模 1.0s vs 21.9s、边框 114.7s），补两个坑（nightly 出的边框非水密、2021.01 不认 `--enable=fast-csg`）；`guides/output-layout.md` 补批量两级目录与 `out/<批次>/`，命名表换 `handle_straight*`，示例从已归档的 v3 换成 v5；`guides/parts.md`、`guides/printing.md` 手柄尺寸 φ14→φ15、124×14→130×15、2.03→2.05 cm³。
- 引用完整性：README 指向的 7 个 guides、4 个 tools 脚本、关键 STL 与 model.html 逐个 `Test-Path`，全部存在，无幽灵引用。
- 补记 v11.7 的行为：`batch_molds.py` 比对边框 STL 的 sha256，同形边框在 `INDEX.md` 标「同 `X`，不必重复打」（文件保留，索引仍认配对），避免一批 40 套白打几十个一模一样的边框。

## v11.6 · 2026-11-24 · 批量出模（10–40 套）+ 性能压到 40 套 96 秒

- 新增 `src/batch_molds.py`：读 CSV 清单（`item,input,size,relief,mode`），并行 N 路跑 `stamp_pipeline`，一套一个子进程。实测 i5-13400 / 8 路：**10 套 51s、40 套 96s**（40/40 成功、40/40 水密、40/40 配对齐全）。
- 目录改成两级，配对关系由路径保证：`print/jobs/<批次>/<单号>/{base,cutter}.stl` + `out/<批次>/<单号>/` + `out/<批次>/{INDEX.md,batch.json}`。旧单层结构继续兼容（`make_print_index.py` 先判 `base.stl` 存在则当单套，否则遍历一层当批次）。
- `stamp_pipeline.py` 加 `--job`（可含 `批次/单号`）与 `--no-index`；`write_manifest` 里写死的 `<job>` 全部改成实际 job，不再出现 `print/jobs/<job>/` 这种占位串。
- `make_print_index.py`：两级扫描 + `probe()` 结果按 `mtime+size` 缓存在 `.cache/probe.json`，索引重建 4.1s → 0.4s。
- 性能四层：① OpenSCAD nightly（2026.11.23）+ Manifold 后端，底模渲染 21.9s → 1.0s；② 进程级并行；③ 批量时 `--no-index`，批次结束只刷一次；④ STL 体检缓存。单套剩余 10.3s 里约 4.7s 是 Python 导入，1s 是 OpenSCAD，其余是轮廓提取与布尔——不再深挖（40 套 96s 已够用）。
- 新增 `guides/batch.md`：命名规则、清单格式、性能实测与依据、失败处理、坑。README 加「一次出一整批」段落并修掉手柄表格里残留的 dome 旧数据（φ14/1,728 面）。`.gitignore` 加 `tools/openscad_nightly/`（224MB）与 `.cache/`。

## v11.5 · 2026-11-24 · 全库对齐：旧单归档、凹模重出、层高对比件换定稿手柄

- `bakers_v3` / `bakers_v4` 的打印件从 `print/jobs` 移到 `out/_archive/<job>/print`（只归档不删除），打印清单从此只列当前单：`bakers_v5`（凸模）与 `bakers_cav`（凹模）。
- `bakers_cav` 用新垂直刃口重出：底模 84.20×84.20×3.00、47,980 面、14.90cm³；边框同步换垂直薄刃；`model.html` 重生成，默认叠放视角。
- `print/test/handle_layer/layer_3.stl` 换定稿 straight 手柄重出（65×15×25、4,032 面）；`handle_layer_test.py` 加 `--style`，默认 straight。
- `out/bakers_v4` 目录因浏览器正打开其 html 未能移动，暂留原处作旧刃口对照；它的打印件已归档、不再计入清单。

## v11.4 · 2026-11-24 · 边框改垂直薄刃 + 预览默认叠放 + 打印件不带把手

- 新增 `--cutter-edge-mode`，默认 `vertical`：外壁一次性从 1.2 收薄到 0.4，然后整段垂直到底；内壁全程不动，侧面零斜面。旧 `taper`（8 段阶梯）仅留作对照。实测边框 25,524 → 17,736 面、斜面 0.0%、体积 5.32cm³。
- 参数依据（网上切模资料）：主体壁厚 0.8–1.2mm（软面团 0.8–1.0，≥1.5 会挤压面团而非切开）、刃口 0.4–0.8mm、总高 12–15mm、刃口保持 90° 不做倒角。
- `model.html` 默认打开即**装配叠放 + 近俯视**：边框套住底模，四周 0.4mm 缝一眼可见；按钮初始标签改"装配视图"，切换时相机角度同步；顺手修掉"背面"按钮里 `mode='asm'` 的错值。
- Skill 写入三条硬规则：① 打印件永不带把手（手柄单独出，禁 `--rim-w`）；② 展示图必须叠放；③ 每次出件必留预览 html。
- 新出 `bakers_v5`（同图凸模 85mm）作为新刃口样件；`bakers_v4` 留作旧刃口对照，`shot_stacked.png` 是叠放态截图。

## v11.3 · 2026-11-24 · 新出一单 bakers_v4（圣诞 baker 图凸模，85mm）

- `stamp_pipeline --size 85` 凸模，scad 引擎 21.9s：底模 84.20×84.20×4.80mm、37,876 面、水密、18.56cm³；边框内腔 85.0、壁 1.2 / 高 12.0 / 刃 0.4。
- 外框识别成功（填充比 22.7×），线宽中位 1.54mm、最细 0.59mm，没有一处 <0.5mm；以 0.44mm 腐蚀，35 个部件全存活。
- 与 `bakers_v3` 同图同参、几何完全一致，单独建批次只是为了分开打与验证。

## v11.2 · 2026-11-24 · 手柄定稿（柄 φ10 / 底盘 φ15）+ 出件必配预览 html

- 用户拍板尺寸：握柄 φ10、底盘 φ15、总高 25、顶端 R3。`HANDLE_STRAIGHT` 改成这组值，底盘到握柄用直角台阶（朝上的环面，不算斜面），斜面只剩顶部 3mm 圆角：实测 1,344 面 / 2.05cm³ / 斜面 7.7%（垂直 64.1%）。dome 61.6%、column 9.3% 从此只作留档对照，不投产。
- `make_handle.py` 默认出 `out/handles/<件名>.html` 自包含预览，`--no-viewer` 才跳过；`make_viewer.py` 新增 `--kind handle`，手柄预览不再显示"底板/浮雕 ?"与"已镜像"这类底模字段。
- 定稿件出齐：`handle_straight.stl`（15×15×25）、`handle_straight_x6.stl`（130×15）、`handle_straight_x12.stl`（`--cols 6` 排成 130×38，比 11 列版 245×38 更稳）。
- `bakers_v3` / `bakers_cav` 的 `model.html` 重出，装配视图改挂新定稿手柄。
- 写进 Skill 硬规则：每次真正出件都必须留预览 html（模具 `out/<job>/model.html`、手柄 `out/handles/<件名>.html`），只有用户明确说不要才跳过。
- 删掉 `print/test/handle_shape/compare_3.stl`（三款对比板，用户只打定稿款）。

## v11 · 2026-11-24 · 建体迁到 OpenSCAD（借 PJ1 的参数化建模）

- 参照 3D 打印电脑 `D:\HA1\PJ1`（名字印章生成器 stampgen v2.2.8）的做法：Python 只把位图变成 2D 多边形，挤出与 3D 布尔交给 OpenSCAD/CGAL。新增 `src/scad_engine.py` 与 `scad/{base,cutter,handle}.scad`，`--engine {scad,mesh}` 默认 scad，找不到 openscad 自动回退 mesh。
- 实测收益：凹模从 144.6k 面降到 48.0k 面（切片更快），凸模体积与旧件完全一致（18.56cm³），面数从 56.2k 降到 37.9k。
- 实测代价：底模 19.3s（凸）/ 25.6s（凹），旧 mesh 路径全流程 5.7s。因此 **边框固定走 mesh**（`--cutter-engine` 默认 mesh）：边框全靠 `offset()`，OpenSCAD 8 段阶梯实测 114.7s，trimesh 0.50s，差 229 倍。
- 三个坑写进 `guides/openscad.md`：① 不要用 SVG import——OpenSCAD 2021.01 对多个 SVG 的 y 映射不一致，outline 落 0..84.2、pattern 落 72.37..168.4，union 出 10 个壳；改 `polygon()` 内联。② 参数必须 `-D`，job.scad 里赋值会让 `is_undef(x) ? 默认 : x` 在同作用域自我覆盖（raise/sink 出同一件）。③ 凹模拔模别用多层 offset（59 路径×8 段 >10 分钟），改 `linear_extrude(scale=)` 一次成型，23 秒。
- 手柄新增 `--style straight`（直筒 φ11.8 + 顶 R3）：斜面面积占比从 61.6% 降到 15.8%，垂直面 23.1%→66.6%。呼应 v9.1 的结论——横纹主要来自斜面，改形状比降层高更有效。dome 款出件与旧 revolve 完全一致（1,728 面、2.03cm³）。
- 手柄再加 `--style column`（φ14 直筒贯通、取消收颈、只留顶 R3）：960 面、3.76cm³、斜面 9.3%，是斜面最少的一档；新增 `src/tools/handle_compare_board.py` 出一板三款对比件（`print/test/handle_shape/compare_3.stl`，58×14×25），一次打印即可比手感。
- `scad/` 模板参数用 `is_undef` 声明，可直接在 OpenSCAD GUI 里 F5 预览；`report.json` 新增 `engine` 与 `scad_render_s`。

## v10 · 2026-11-24 · 目录重构（src/ + print 三档 + 层高对比件）

- 之前所有脚本平铺在根目录，产出和代码混在一起。现在代码全进 `src/`：`stamp_pipeline.py`、`make_handle.py`、`make_print_index.py`、`src/viewer/`、`src/tools/`。根目录只剩 `README.md`、`CHANGELOG.md`、`PRINT.md`、`.gitignore` 与四个目录。
- `print/` 拆成三个抽屉，一眼分清生命周期：`standard/`（定稿可复用的标准件，手柄在这）、`jobs/<job>/{base,cutter}.stl`（跟图案走的这一单）、`test/`（试打与对比，随时可删）。件名从 `<job>_base.stl` 简化为 `base.stl`，因为目录已经带单号。
- `make_print_index.py` 重写扫描逻辑：三档分开收集、分三节渲染；`--check` 保留四类问题（读取失败 / 非水密 / 只有底模没边框 / 命名不合约定）。
- 新增 `src/tools/handle_layer_test.py`：生成 3 个手柄一排的对比件（`print/test/handle_layer/layer_3.stl`，62×14×25、5,184 面、水密），并写 `out/handles/layer_test.md` 记录表（0.4/0.16、0.4/0.12、0.2/0.08 三组，靠位置区分）。
- `run_job.py`（Skill）同步新路径；`README`、`guides/output-layout.md`（重写）、`cavity.md` 的命令全部改成 `python src\...`。
- 验证：`stamp_pipeline.py` 出凹模 → 件落 `print/jobs/bakers_cav/`；viewer 出 `model.html`；`--check` rc=0；skill 一条命令端到端跑通。

## v9.1 · 2026-11-24 · 手柄表面观感（层高才是变量）

- 打印出来的手柄一圈圈横纹明显，用户先怀疑建模。核了网格：96 段旋转体、棱面弦高误差 0.0027mm（比 0.16 层高小 60 倍），侧面是折线旋转出的直锥面，几何 z 向只有 10 圈折点——建模不是主因。
- 结论写进 `guides/printing.md`：横纹间距 = 层高；0.4 喷嘴从 0.16 降到 0.12 并且外壁 35–45mm/s、外壁线宽 0.42、开输入整形；要手感就换 0.2 喷嘴 0.08–0.10。反例也记了：0.4 喷嘴别降到 0.05，欠挤出会让 Ra 反而升 18%。
- 补两条位置常识：圆顶与收颈两处斜面临近 45°，FDM 在该角度的粗糙度约是垂直面的 3 倍；用自适应层高只在斜面降层高更划算。
- 模型侧仍留两个可选改进（未做）：圆顶从两段锥面改成真球面、收颈与托盘加 0.4mm 圆角——只改善观感，消不掉层纹。

## v9 · 2026-11-24 · 凹模（成品图案凸起）

- 新增 `--relief-mode {raise,sink}`。raise 是原来的凸印章；sink 把图案沉成凹槽，粘土压进去再取出，成品图案是凸的。用户要的"图案凸起"就是这条路，不需要另起一套流程。
- 新增 `--cavity-draft`（默认 5°）与 `--cavity-segments`（默认 4）。凹槽槽底窄、开口宽，脱模才不卡；依据是 printforgehq（5–15°、深 1.5–3mm）、Meshcast（层纹面 3–5°）、Flashforge（负模必备拔模）。垂直墙能打但细线会被粘土拽断。
- 布尔的坑：图案把顶面切成一堆互不相连的小岛，`trimesh` 的 volume 预检直接报 "Not all meshes are volumes!"，差集出不来。改成 `check_volume=False` 交给 manifold 自己合并多体，才拿到水密单壳。
- 深度自动夹到 `base_thickness - 1.0`，槽底至少留 1mm。
- 凹模样件 `bakers_cav`：84.2×84.2×3.0、144,648 面、水密、14.7cm³；边框与手柄直接复用同一套。
- 预览与查看器认模式：preview 三栏改成「凹模实物 / 压印效果 / 剖面（槽深）」，HUD 显示"底板 / 槽深"与"凹模锥度"。
- 新增 `guides/cavity.md`（几何做法、锥度取值表、深度取舍、打印参数、四条硬限制）；README 增一节；`PRINT.md` / `MANIFEST.md` 自动标「凹模 · 槽深 · 外张」。

## v8 · 2026-11-24 · 纳入 Git，备份到 GitHub 私有仓库

- 本项目此前没有版本管理（`git status` 报 not a repository），改文档只能整份重写来兜底。现在 `git init -b main`，首个提交 53 个文件 / 12.5 MiB，远端为私有仓库 `raomy637/3d-stamp-print`（SSH，`origin/main` 已跟踪）。
- 新增 `.gitignore`：排除 `__pycache__`、`*.pyc`、`_p_*.html` / `probe_*.html` 探针副本、`.vscode`、`*.gcode` / `*.3mf`。STL 与 `model.html` 故意入库——克隆即得完整可打状态。
- 之前踩的"无 git 可回滚"的坑自此关闭：Markdown 改坏了可以直接 `git checkout`。

## v7 · 2026-11-24 · 打包成 Skill（clay-stamp-mold）

- 流程不再只活在这个仓库里：新建 Skill `clay-stamp-mold`（路径 `workspace/.user_skills/clay-stamp-mold`），描述里写死了触发语（粘土印章/饼干模具/曲奇切模/线稿转 STL/底模边框手柄/尺寸与打印参数），下次说"做张模具"就会自动路由过来。
- SKILL.md 只留"怎么跑 + 输出约定 + 汇报三件事 + 默认参数 + 踩过的坑"，细节靠按需读本仓库的 `guides/*.md` 与 `CHANGELOG.md`（不复制，避免双份维护）。
- 新增 `scripts/run_job.py`：一条命令串起 出件 → 3D 预览 → 手柄补料（缺才补）→ PRINT.md 刷新与体检 → 摘要，已在本机跑通（bakers_v3 全绿）。
- `quick_validate.py` 校验通过。

## v6 · 2026-11-24 · 输出目录规范化（print/ + out/&lt;图案&gt;/）

- 以前所有产物平铺在 `out/`，靠 `bakers_v2`、`bakers_v3` 后缀区分几代，肉眼分不清哪个能打。现在**按"能不能打印"分家**：
  - `print/`：只放可打印 `.stl`，命名 `<图案>_base.stl` / `<图案>_cutter.stl` / `handle_*.stl`；
  - `out/<图案>/`：只放给人看的（`MANIFEST.md` 清单、`report.json`、`preview.png`、`lines.svg`、`model.html`、`shot_*.png`）。
- `--out` 语义改为**图案目录名**（`out\bakers_v3` → 目录 `out/bakers_v3`；传 `out\x.stl` 也认并按 `x` 处理）。新增 `--print-dir`（默认 `print`）。
- 新增 `make_print_index.py`：扫 `print/` 生成根目录 **`PRINT.md`** 打印总表（件名/外形/面数/水密/体积/打印要点），两个脚本收尾自动刷新；`--check` 退出码 0=全部可打，能抓命名不合规、非水密、只有底模没边框三类问题（已造违规验证会真报错）。
- 每次运行多写一份 `out/<图案>/MANIFEST.md`：这批出了什么、哪个能打、打什么设置。
- 迁移：现有件搬进新布局；v2 那批、85mm 早期件、旧截图全部归档到 `out/_archive/`（**留档不删**），`handles/`、`out/viewer/` 两个旧目录撤掉，手柄排布脚本移到 `tools/`。
- 文档：新增 `guides/output-layout.md`；README 压到 181 行（索引层），旧的平铺路径全部改掉。

## v5 · 2026-11-24 · 手柄改成小把手（φ14 × 25）

- 按用户要求缩到手部实际需要：**总高 25mm、底盘 φ14**，握柄 φ9.8–11 腰形（原来 φ20–21.2 / 48 高不合理地大）。
- 粘接面从 804mm² 降到 154mm²；单个体积 17.2 → 2.03 cm³，6 联排从 232×32 缩到 124×14mm（一盘能排十几二十个）。
- `HANDLE_PROFILE` 是唯一的数据源，`make_handle.py` 与预览图重跑即可，底模/边框一行不动。
- 预览器 HUD 改为自动读 STL 尺寸 → 手柄行显示 φ14 × 25.0，装配总高 29.8mm。

## v4 · 2026-11-24 · 边框从底模里拆成独立件（三件套）

- **结构性改动**：以前"外沿凸起一道边框"（`--rim-w`）是错的——那道墙跟着底模走，每换一张图就要重打一圈墙，刃口也做不薄。改为**边框独立成件**：只有一圈 1.2mm 墙 + 0.4mm 刃口，专门切粘土外形。
- 新增 `build_cutter()` 与 `--cutter-wall/height/edge/edge-h/flange-w/flange-t/clearance`、`--no-cutter`；`--rim-w` 默认改 0 并标注为淘汰写法。
- **`--size` 语义变更**：以前=底模外形，现在=**边框内腔（切出来的粘土尺寸）**；底模自动内缩 2×0.4mm 环隙（MakerWorld 生成器的 standard clearance）。
- 取值依据（12mm 高 / 1.2 墙 / 0.4 刃口 / 4.0×1.6 翼缘 / 0.4 环隙）连同出处落到 `guides/parts.md`；刃口锥段从 4 段改 8 段，避免明显台阶。
- `make_viewer.py` 支持第三个网格（`--cutter`）：分离视图三件并排、装配视图落进内腔；侧视改低角度平视（看 12/4.8/25 的厚度对比）、背面改从后方看粘接面。
- 实测：底模 84.2×84.2×4.8、56,194 面、水密、18.6cm³；边框 95.4×95.4×12、58,930 面、水密、5.62cm³。
- 文档拆分：README 压回 184 行（索引层），细节进 `guides/parts.md`（尺寸链/参数出处）与 `guides/printing.md`（切片/后处理）。

## v3 · 2026-11-24 · 手柄独立成件

- 新增 `make_handle.py`：手柄从章体流水线剥离，尺寸定死后**一次打一批**（`--count 6` → 124×14mm 联排），换图案不用重打手柄。
- 手柄改瘦长款：底盘 φ32×2.4、握柄 φ20–21.2、总高 48mm（旧款 φ44×33.2 偏矮胖）。**v5 又改成小把手 φ14×25，见下。**
- `stamp_pipeline.py` 移除 `--handle / --handle-height / --handle-flange-r` 与 `*_handle.stl` 输出；json 不再含 handle 字段。旧件 `out/bakers_v2_handle.stl` 已删。
- 预览第三栏改为**半剖（2x，带中心线）**：手柄不再画进章体剖面，底部注明另件路径。

## v2 · 2026-11-24 · 加边框 + 3D 预览

- 新增 `--rim-w / --rim-h`：外沿凸边框限深 0.4mm（我这张 85 盘取宽 4mm）。
- 新增 `viewer/make_viewer.py`：单文件离线 HTML 查看器（three.js 内联、网格 uint16 量化），五视角 + 分离/装配。
- 尺寸精度修正：底板轮廓按 `size - 2*margin` 反算，输出严格等于 `--size`。
- 取舍记录：纹理 PEI 会把纹路翻印到印面 → 追求平整须用光面/玻璃板；但 rim 比浮雕高 0.4mm，与「图案朝下」互斥，二选一。

## v1 · 2026-11-24 · 首发

- 线稿 → 凸印章：`find_contours` 取轮廓 + even-odd 判孔洞 → 2D 布尔 → 分层拉伸 → manifold 并集出单一水密网格。
- 外框识别：铺满整图的闭合连通块转为底面轮廓（扇贝边自动继承），框体丢弃。
- 线宽体检：0.44mm 腐蚀校验部件存亡；`--min-stroke` 只加粗「本来印不出来」的部件。
- 默认 X 镜像（凸印章压出来才正读）。
- 实测：85×85×4.8mm、58,086 面、水密 18.9cm³；线宽 min 0.59 / 中位 1.54mm → 0.2 喷嘴可行。
