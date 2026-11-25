# 变更记录

> 只记「改了什么 + 为什么」。现状看 `README.md`，历史细节留在这里，避免 README 膨胀。

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
