# 变更记录

> 只记「改了什么 + 为什么」。现状看 `README.md`，历史细节留在这里，避免 README 膨胀。

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
